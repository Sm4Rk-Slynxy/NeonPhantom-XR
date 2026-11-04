# Preparing a GitHub release

1. Build both browser interfaces and the backend as described in README. For Windows, build natively on Windows or use a configured cross-toolchain. The GitHub workflow builds separate Linux and Windows artifacts.
2. Run `npm run test:security --prefix frontend`, the conversion tests, `scripts/test_api_runner.py`, Rust tests, and Quest browser smoke tests. For the browser tests install Playwright in a temporary tools directory and set `PLAYWRIGHT_MODULE` to its entry module. `CHROME_PATH` can select Chrome; `QUEST_PYTHON` selects the companion interpreter. Emulation dependencies are installed with `npm ci` in `quest/app`.
3. Validate installation from each requirements file in an isolated Python 3.12 environment, then run npm audit for each UI, pip-audit for both Python lockfiles, and cargo audit with warnings denied. The local deepmerge patch must pass its exploit tests; npm audits must pass at every severity. Do not silently waive new findings.
4. Run `python scripts/release_audit.py --git`. It checks every source file in the allowlist and verifies the Git index contains exactly that source set. Runtime data and built assets must never enter Git.
5. Run `python package_release.py --platform source`, then `--platform Linux` and `--platform Windows` on the corresponding build hosts. Each command checks the archive and writes a SHA-256 sidecar. Keep the entire extracted app folder together.
6. Publish only the sanitized repository and these freshly generated archives. Tag `v0.1.0-alpha.2`, mark the release as a **prerelease**, and attach the source, platform ZIPs and checksum files. Describe Windows/Quest hardware validation limitations honestly.

The workflow runs on pull requests, pushes to main, tags, and manual dispatch. It uploads build artifacts for review and does not publish a release automatically. Its permissions are read-only. Enable GitHub secret scanning, push protection, Dependabot alerts, and private vulnerability reporting in the repository settings where available.

## Screenshots

`python scripts/generate_demo.py --output /tmp/neonphantom-demo` produces geometric figures and invented library metadata. It refuses a nonempty directory. This is a separate disposable library; never copy real library state into a screenshot fixture. The checked-in screenshots contain no real people or personal media. Do not present them as a model quality comparison.

## Private installations

The release script uses a source allowlist and refuses credentials, personal home/workspace paths, private LAN addresses, and unexpected tracked files. It does not publish the working installation, old archives, cache, runtime certificates, media, or Git history from another folder. Preserve upstream attribution in the third-party notices.

If a secret has ever been pushed, removing it from the current tree is insufficient: revoke it and clean history before making the repository public. This prepared repository starts from new history.

The prepared initial Git commit uses a generic release identity rather than a personal name or email. Configure your desired GitHub noreply identity before future commits. No remote is configured until the repository destination is supplied.
