# Security policy

NeonPhantom XR is an alpha local application. The desktop studio binds only to loopback. The optional HTTPS companion exposes paired playback and conversion on your LAN. Run it on a trusted local network; do not forward its port to the internet. A paired browser can view and download the shared library and start derived stereo conversions. The companion limits simultaneous requests to 32 to bound stalled-connection resource use. Stop it to end sharing and invalidate its sessions.

Video processing stays on the PC. Setup, package installation, and model downloads contact upstream providers. These optional dependencies execute locally with your user privileges. MatAnyone and WeVisOne inference sources are pinned; their dependency resolution and model downloads still depend on the upstream publishers. App download helpers require HTTPS through redirects; MatAnyone checkpoints are checksum-verified before loading, and new WeVisOne installs pin weight revisions. Use current FFmpeg and Python runtimes.

Private runtime data includes `samples/`, `deskdanced/state*`, `.quest/`, `.models/`, `.venv*/`, `.runtime/`, logs, backups, and machine notes. Never attach these to an issue. Use generated clips when reproducing a problem. Clear browser local storage separately if sharing a browser profile.

Report suspected vulnerabilities through the repository's **Security → Advisories → Report a vulnerability** when private reporting is enabled. If it is unavailable, open an issue asking for a private reporting channel without including exploit details, personal clips, certificates, or pairing codes. No private contact address has been published.

Only the current alpha is maintained. A review and clean scan do not guarantee that all vulnerabilities have been found; see [SECURITY-REVIEW.md](SECURITY-REVIEW.md) for scope, results, and known limitations.
