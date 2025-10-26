# Integrating Multiple Pull Requests for Combined Testing

To test the interaction of several pull requests without touching the `master`/`main` branch, create an integration branch and pull each PR there. The workflow below assumes the upstream repository is available as the remote named `origin` and the individual PR heads can be fetched via `refs/pull/<id>/head`.

```bash
# Start from an up-to-date local main branch
git checkout main
git fetch origin
git reset --hard origin/main

# Create a throwaway integration branch
integration_branch="pr-integration"
git switch -c "$integration_branch"

# Merge each PR sequentially (re-run for all PR IDs)
for pr in 1 2 3; do
    git fetch origin "pull/${pr}/head:tmp-pr-${pr}"
    git merge --no-ff "tmp-pr-${pr}" -m "Merge PR #${pr} into ${integration_branch}"
    # Optionally delete the temporary ref after a successful merge
    git branch -D "tmp-pr-${pr}"
done

# Run analysis and tests on the combined changes
# ...

# When finished, delete the integration branch if it is no longer needed
# git switch main
# git branch -D "$integration_branch"
```

This approach keeps the official mainline untouched while giving you a branch where all three pull requests coexist for validation. If conflicts appear during any `git merge`, resolve them within the integration branch before continuing your analysis.

## Choosing a Test Environment

Ext2Fsd is a Windows kernel driver, so the merged code must ultimately be validated on Windows. The options below can help you pick the right setup for your situation:

- **Windows virtual machines** &mdash; Recommended for most development work. A Windows 10/11 VM (Hyper-V, VMware, VirtualBox, or QEMU/KVM) lets you snapshot before installing a new build, attach virtual disks for destructive filesystem testing, and capture kernel debugger output. Make sure the VM exposes a raw disk or VHD so the driver can mount ext* volumes.
- **Physical hardware** &mdash; Use when you need to validate performance, device-specific behaviours, or interactions with real storage controllers. Keep a known-good recovery path (e.g., second OS install or bootable USB) in case the driver destabilizes the system.
- **Linux hosts** &mdash; Useful for building and preparing ext4/ext3 volumes, but they cannot replace Windows for runtime validation. You can create disk images or partitions from Linux and attach them to a Windows VM, yet the driver itself cannot be exercised entirely on Linux.

When possible, run quick smoke tests in a VM for every integration build and reserve physical-hardware passes for milestone regressions or when investigating issues that do not reproduce under virtualization.
