# TTS compatibility with DSH 0.2.0-rc.1

## Intended result
Restore the existing TeraTTS assistant-message action on the active DSH Web profile without restarting DSH or bypassing its version gate.

## Scope and invariants
- Own `dsh-plugin/` compatibility changes, regression tests, the root README's plugin instructions, and this record.
- Use the repository's 0.8.8 implementation as the source of truth (the installed 0.8.8-rc1.local.2 package is a divergent older deployment).
- Preserve synthesis, cancellation, bounded caching, playback controls, endpoint restrictions and host-only credentials. Do not change the Rust server, credentials, unrelated plugins or user files.
- Install through plugin_manager only. No profile-file edits, runtime-core changes, compatibility exemptions or DSH restarts.

## Observations and unknowns
- Plugin Manager reports installed TTS disabled: peers target 0.1.x, runtime is 0.2.0-rc.1.
- Current Settings service removed installSection; Config-derived settings replace manual registration.
- Repository client imports private UI primitives; replace that dependency with local controls to avoid module-loader failure.
- The existing integration suite has three failures because it constructs the new Settings service using the obsolete contract; four tests pass, including real Host imports.
- Live assistant-actions slot exists with messageId/useChat/useSession props. A subsequent Client Service query hung and was cancelled; do not repeat unbounded Client queries.
- Browser playback and visual light/dark acceptance are deferred until the plugin is active; unit/module checks are not visual or audible verification.

## Verification
- Red/green runtime compatibility and client module-load tests; run the complete plugin Node test suite against the actual runtime.
- Verify manifest peers against installed dependencies, real Cordis mount/disposal and Remote methods.
- Install the exact tested package through plugin_manager and inspect its application/warnings; confirm live Host Config/service registration.
- Exercise bounded synthesis if existing credentials and runtime afford it without exposing secrets. Distinguish server audio from browser playback.
- Review task-only diff, commit and push a dedicated branch to origin; preserve all pre-existing untracked files.

## Implemented
- Version 0.9.1 pins the tested DSH 0.2.0-rc.1 peers and replaces the removed client-runtime activation dependency with client-ui-renderer.
- Host reads Loader Config directly instead of calling removed settings.installSection.
- Host disposal uses ctx.effect, not the obsolete dispose event; a real Cordis test reproduced the missing cleanup before this correction.
- Client unwraps RemoteResult for synthesis and lease calls, removes private Harness UI imports, and renders styles/player within its React ownership instead of factory-time DOM mutation/body portals.
- Runtime tests use DSH_TEST_NODE_MODULES or the actual DSH_PROFILE_DIR rather than a stale release path.

## Verification evidence
- Initial runtime suite: 4 passed / 3 failed against the new Settings contract.
- New client regression cases: 3 failed before the fix (unavailable private UI import).
- `node --test dsh-plugin/test/*.test.js`: 123 passed, 0 failed.
- `node --check dsh-plugin/lib/client.js`, `node --check dsh-plugin/lib/index.js`, `git diff --check`: passed.
- Installed archive Host import succeeds in a fresh Node process. A further isolated check imports the profile-installed archive, mounts it with real Cordis, verifies effective Config and then disposes it, confirming removal of terattsVoice (exit 0; no synthesis/network request). No version exemption used.
- Read-only live check still reports ui-teratts inactive while dsh-web.service is active/running. journalctl cannot open the service journal under current permissions (exit 1); no privilege escalation attempted.

## Installation and remaining acceptance
- Directory installation created a source symlink whose peers did not resolve. Installing an archive over the same link retained the link; removed only this inactive bundle through Plugin Manager and reinstalled packed 0.9.1. The installed path is now profile-local and imports successfully in a fresh process.
- Plugin Manager first returned restart-required. Live import remains failed after reinstall in the existing process; cached old module resolution is suspected, not proven. No DSH restart performed. Row selection is enabled, but the Host entry is not active.
- Next step requires explicit single-use approval for a DSH restart, then inspect live Host activation and exercise actual browser synthesis/playback. Do not claim TTS restored based on unit tests alone.
- Visual light/dark contrast and button/player interaction: NOT VERIFIED; existing styling retained, not redesigned. Module contract and lifecycle: PASS. README factual/command review: PASS.
- In-session code review only; no authorized explicit Gemini/Opus delegation route was available for independent review.
