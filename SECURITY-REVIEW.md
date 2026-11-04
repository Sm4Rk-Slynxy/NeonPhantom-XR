# Release security review — 2026-11-04

Scope: the 0.1.0 alpha source (security update: alpha.2), desktop HTTP/WebSocket API, uploads/imports, local media decoding, optional-model installation, Windows overlay controls, Quest pairing/static/media/download/conversion endpoints, and release contents. This is an agent-performed code review with automated checks, not an independent penetration test.

## Findings addressed

| Finding | Change and evidence |
| --- | --- |
| Desktop origin validation did not cover DNS rebinding | Validate the loopback Host and port before serving any request; reject cross-site Fetch Metadata and foreign browser origins. API regressions verify rejection. |
| Local video files could reference playlists or network inputs | Restrict FFmpeg/ffprobe to local file/pipe/descriptor protocols and an explicit video/frame format allowlist. HLS, DASH and concat input playlists are rejected. Regression checks cover disguised playlists and HTTP input; M4S assembly still passes. |
| Player IPC/log fallback used a shared temporary location | Move to a private per-app runtime directory with mode 0700. |
| TLS key permissions were tightened only after writing | Protect the TLS directory and create new private keys with mode 0600. Tests check directory/key permissions and paired HTTPS flows. Windows uses the signed-in user's filesystem permissions. |
| Older dependency locks included security advisories | Update rembg to its Pillow-13-compatible 2.0.86 release, Pillow to 13.0.0, certifi to 2026.10.23, Tokio to 1.53.3, and Quest Vite to 6.4.5. Remove the unused SvelteKit server/adapters, update the studio build tooling, and keep exact npm lockfiles. |
| Working installation contained personal records and historical artifacts | Create a separate allowlisted repository with fresh Git history. Exclude all footage, state/job history, caches, certificates, keys, model weights, virtual environments, screenshots from the private installation, backups, machine notes and old release archives. Only regenerated synthetic screenshots are included. |
| Compiled executables could retain source-machine paths | Strip release binaries, remove the compile-time app-root fallback, remap build paths, and scan final archive contents. |
| Deepmerge prototype poisoning in the Svelte build tooling | Replace the transitive package with a locally attributed patch that defines result keys as data properties. Exploit reproduction succeeds on upstream and fails on the patched copy. Six security/compatibility regressions are required in CI, including module resolution after a fresh npm install. |
| Download helpers did not explicitly enforce HTTPS through redirects | Route source/depth/checkpoint downloads through a shared HTTPS-only helper with credential/port checks, redirect validation, timeouts and atomic writes. Tests cover downgrade/file redirects, interrupted transfer and checksum failure without destroying existing files. |
| MatAnyone checkpoints were loaded without a pinned checksum | Pin the publisher's SHA-256 and verify before installation completes and before the third-party loader runs. The existing official weights match. Reject tampered files before importing the model loader. |
| WeVisOne weight downloads followed a mutable default branch | Pin the 2B/4B Hugging Face revisions and record them in installation metadata. Existing installations remain available. |
| Stalled HTTPS connections could create unbounded workers | Limit the LAN companion to 32 simultaneous request workers before TLS handshakes/headers. An integration test stalls connections, verifies excess connections are rejected, then verifies service recovery. Normal pairing, streaming and conversion still pass. |

The studio also sends a restrictive CSP, anti-framing, no-referrer and MIME-sniffing headers. It uses argument arrays for subprocesses rather than a shell. The Quest companion retains TLS, random per-run sessions, constant-time token comparisons, HttpOnly/Secure/SameSite cookies, pairing rate limiting, same-origin mutation checks, path boundaries, and library membership checks before media/download access.

## Automated results

- CPU and GPU Python lockfiles: **no known vulnerabilities** reported by pip-audit after updates. These checks cover the pinned base stacks; optional MatAnyone/WeVisOne install dependencies resolve separately and must be audited after installation.
- Rust lockfile: **no known vulnerabilities or warnings** reported by cargo-audit/RustSec after the Tokio patch.
- Quest npm dependency tree: **zero advisories** reported.
- Studio npm dependency tree: **zero registry advisories** reported with the patched override. The upstream [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4) has no published fix, so the app uses an explicit, private local fork. Local directory dependencies are not independently covered by npm's advisory database: the six regression tests and the provenance recorded in [the patch README](frontend/vendor/deepmerge-safe/README.md) cover this component. No audit-ignore rule is used; CI now fails all npm advisory severities.
- Bandit static analysis: no high-severity findings and no remaining medium findings for URL handling. The two remaining medium reports identify the intentionally LAN-bound HTTPS listener; disabling LAN binding would remove requested headset access. Generic low-severity subprocess reports were reviewed for argument arrays and fixed executables. Local interpreter overrides remain trusted configuration.
- Conversion (including real Classic inference on synthetic footage), API and HTTPS regression tests, real synthetic depth conversion, and stereo/controller browser emulation pass. The CPU lockfile and Windows x64 setup requirements were checked with pip’s resolver. See [VALIDATION.md](VALIDATION.md).
- The source/index and generated archives are checked by `scripts/release_audit.py` for allowlist violations, key/token signatures, personal home/workspace paths and private LAN addresses. This targeted scanner is not a universal DLP or secret scanner. Screenshots were visually inspected and contain generated figures and invented metadata only.

## Review limits

CodeRabbit CLI 0.7.5 was present but signed out. Its separate remote review **was not run**, and no source was sent to that service. Manual review and the automated checks above were performed locally.

Physical Quest behavior, native Windows execution, model quality on real footage, third-party model code/weights, driver security and every optional transitive Python dependency were not exhaustively assessed. FFmpeg and other native runtime tools remain external dependencies and should be kept current. The companion is intended for a trusted LAN and should not be exposed to the internet.

The original private installation and its local library are preserved outside the publishable repository. Excluding those files from a fresh release is not secure erasure of the working drive, old backups, browser profiles, or previous exports.
