#!/usr/bin/env python3
"""Stress test for Ext4Fsd 64-bit superblock counters."""
from __future__ import annotations

import struct
import subprocess
import tempfile
from pathlib import Path

SUPER_OFFSET = 1024
SUPER_SIZE = 1024
EXT4_FEATURE_RO_COMPAT_METADATA_CSUM = 0x2000


def _build_crc32c_table() -> list[int]:
    poly = 0x1EDC6F41
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
            crc &= 0xFFFFFFFF
        table.append(crc)
    return table


CRC32C_TABLE = _build_crc32c_table()


def crc32c(data: bytes, crc: int = 0xFFFFFFFF) -> int:
    """Compute the CRC32C checksum using the kernel's convention."""
    for b in data:
        crc = CRC32C_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
        crc &= 0xFFFFFFFF
    return crc


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def read_super(path: Path) -> bytearray:
    with path.open('rb') as f:
        f.seek(SUPER_OFFSET)
        return bytearray(f.read(SUPER_SIZE))


def write_super(path: Path, sb: bytearray) -> None:
    with path.open('r+b') as f:
        f.seek(SUPER_OFFSET)
        f.write(sb)


def superblock_feature_ro(sb: bytearray) -> int:
    return struct.unpack_from('<I', sb, 0x5C)[0]


def update_super_checksum(sb: bytearray) -> None:
    if not (superblock_feature_ro(sb) & EXT4_FEATURE_RO_COMPAT_METADATA_CSUM):
        return
    checksum = crc32c(sb[:0x3FC])
    struct.pack_into('<I', sb, 0x3FC, checksum)


def truncate_super_counts(image: Path) -> None:
    sb = read_super(image)
    for offset in (0x150, 0x154, 0x158):
        struct.pack_into('<I', sb, offset, 0)
    update_super_checksum(sb)
    write_super(image, sb)


def compute_groups_count(sb: bytearray) -> int:
    inodes_count = struct.unpack_from('<I', sb, 0x00)[0]
    inodes_per_group = struct.unpack_from('<I', sb, 0x28)[0]
    return (inodes_count + inodes_per_group - 1) // inodes_per_group


def compute_free_blocks(image: Path, sb: bytearray) -> int:
    block_size = 1024 << struct.unpack_from('<I', sb, 0x18)[0]
    first_data_block = struct.unpack_from('<I', sb, 0x14)[0]
    desc_size = struct.unpack_from('<H', sb, 0xFE)[0] or 32
    groups = compute_groups_count(sb)
    table_offset = (first_data_block + 1) * block_size
    total_free = 0
    with image.open('rb') as f:
        f.seek(table_offset)
        descriptor_bytes = f.read(desc_size * groups)
    for group in range(groups):
        base = group * desc_size
        free_lo = struct.unpack_from('<H', descriptor_bytes, base + 12)[0]
        free_hi = 0
        if desc_size >= 64:
            free_hi = struct.unpack_from('<H', descriptor_bytes, base + 32 + 12)[0]
        total_free += free_lo | (free_hi << 16)
    return total_free


def repair_super_counts(image: Path) -> None:
    sb = read_super(image)
    blocks_lo = struct.unpack_from('<I', sb, 0x04)[0]
    blocks_hi = struct.unpack_from('<I', sb, 0x150)[0]
    reserved_lo = struct.unpack_from('<I', sb, 0x08)[0]
    reserved_hi = struct.unpack_from('<I', sb, 0x154)[0]
    total_blocks = blocks_lo | (blocks_hi << 32)
    reserved = reserved_lo | (reserved_hi << 32)
    free_blocks = compute_free_blocks(image, sb)

    struct.pack_into('<I', sb, 0x04, total_blocks & 0xFFFFFFFF)
    struct.pack_into('<I', sb, 0x150, total_blocks >> 32)
    struct.pack_into('<I', sb, 0x08, reserved & 0xFFFFFFFF)
    struct.pack_into('<I', sb, 0x154, reserved >> 32)
    struct.pack_into('<I', sb, 0x0C, free_blocks & 0xFFFFFFFF)
    struct.pack_into('<I', sb, 0x158, free_blocks >> 32)
    update_super_checksum(sb)
    write_super(image, sb)


def mount(volume: Path, target: Path) -> None:
    run(['mount', '-t', 'ext4', '-o', 'loop', str(volume), str(target)])


def umount(target: Path) -> None:
    run(['umount', str(target)])


def make_random_writes(target: Path, iteration: int) -> None:
    file_path = target / f'stress-{iteration}.bin'
    run(['dd', 'if=/dev/zero', f'of={file_path}', 'bs=1M', 'count=1'], check=True)


def main() -> None:
    iterations = 3
    if not any(Path('/dev').glob('loop*')):
        print('Loop devices unavailable; skipping 64-bit superblock stress test.')
        return
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        image = tmp_path / 'ext4-64bit.img'
        mount_point = tmp_path / 'mnt'
        mount_point.mkdir()

        run(['truncate', '-s', '5T', str(image)])
        run([
            'mkfs.ext4',
            '-O', '64bit,^meta_bg',
            '-b', '1024',
            '-E', 'lazy_itable_init=1,lazy_journal_init=1',
            str(image),
        ])

        for i in range(iterations):
            mount(image, mount_point)
            make_random_writes(mount_point, i)
            run(['sync'])
            umount(mount_point)

            truncate_super_counts(image)
            bad = run(['e2fsck', '-n', str(image)], check=False)
            if bad.returncode == 0:
                raise RuntimeError('Expected fsck failure after truncating counters')

            repair_super_counts(image)
            good = run(['e2fsck', '-n', str(image)], check=False)
            if good.returncode != 0:
                raise RuntimeError('fsck failed after repairing counters')

        print('64-bit superblock stress test completed successfully.')


if __name__ == '__main__':
    main()
