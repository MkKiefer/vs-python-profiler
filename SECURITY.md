# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/MkKiefer/vs-python-profiler/security/advisories/new)
(Security tab → "Report a vulnerability"). Include the version, your OS and Python version, and
steps to reproduce.

The extension runs and attaches to local Python processes, so issues that matter most are ones
where opening a workspace, a launch configuration or a saved `.vspyprof` profile makes it run
code, attach to a process or read data the user did not ask for, in particular in an untrusted
workspace (Restricted Mode).

## Verifying a release

Every `.vsix` on the [releases page](https://github.com/MkKiefer/vs-python-profiler/releases) has
a signed build provenance attestation and is listed in `SHA256SUMS.txt`:

```bash
gh attestation verify python-profiler-X.Y.Z.vsix --repo MkKiefer/vs-python-profiler
```
