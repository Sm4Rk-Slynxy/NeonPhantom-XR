# Local deepmerge security patch

This is **deepmerge 4.3.1's distributed CommonJS source**, with a narrowly scoped fix for [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4). The npm override resolves the Svelte Vite plugin's `deepmerge` dependency to this directory, including after a fresh `npm ci`.

Upstream source: [TehShrike/deepmerge 4.3.1](https://github.com/TehShrike/deepmerge/tree/v4.3.1), SHA-256 of the unmodified upstream `dist/cjs.js` used as the base: `2e5160f84a1141bd927264afe4d15766f1e6cf07daef182b37ff53fea121de7d`. The included MIT license is unchanged. This is a local fork, not an upstream release.

Change: every write to a result object uses `Object.defineProperty` with an own enumerable, writable, configurable data property. This covers copying the target and merging the source, including nested objects and symbols. A key named `__proto__` therefore cannot invoke an inherited setter and poison the result's prototype. Existing merge rules, array/custom merge behavior, Date/RegExp handling and compiler configuration semantics are retained.

Run `npm run test:security` from `frontend`. The tests reproduce poisoned-target and null-prototype-source inputs, nested cases, constructor/prototype payloads, and normal configuration merges; they verify the plugin resolves this patched module. The exploit was reproduced against the original upstream file before patching.

Local directory dependencies are not independently covered by npm's registry advisory database. The regression suite is a required CI check. Replace this fork with a reviewed upstream fix when one is available; never simply remove the override to silence a warning.
