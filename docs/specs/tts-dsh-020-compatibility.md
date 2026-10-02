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

## Post-restart client repair
- One approved TERM restart completed: MainPID changed to 1227817, start time Mon 2026-09-28 22:16:48 UTC, active/running. Restart permission consumed. Host Config is now active (schema).
- User reports `TeraTTS voice service is unavailable`. Source inspection shows Remote descriptors still use `schema`, but current Typert Registry requires strict codecs to expose `create()`; the caught mount failure leaves the button without a voice.
- Repair scope: correct Client codec factories, fail explicitly on mount failure rather than leaving a dead action, and add real-runtime Registry/Gateway mounting tests. No synthesis algorithm or credentials changes. No further DSH restart without new approval.
- Reproduced with actual Registry: `strict codec has no create() factory`. Version 0.9.2 fixes all descriptors and propagates mount errors before registering the action. Real Client Gateway test verifies namespace mounting, synthesis RPC dispatch over a stub transport, and removal on disposal. 126 tests pass; no live audio claim.
- Packed 0.9.2 installed from durable workspace artifacts/tts-dsh-020 path. First attempt failed because prior /tmp/0.9.1 archive disappeared across restart; recreated the exact old archive from commit 16d0dc2 (same package hash), then installation succeeded.
- install_bundle still reports restart-required for the package update; because Host source is unchanged, supported set_plugin disable/enable was attempted and BOTH report applied with no warnings. Host Config active, installed bytes match tested 0.9.2, MainPID remains 1227817. This proves Host activation, not browser artifact synchronization. User asked to retry playback/refresh if stale. Await actual browser confirmation.

## Final acceptance
- User explicitly confirmed after the 0.9.2 repair and refresh prompt: «Да, звук есть». Actual browser speech is user-verified; the original unavailable-service symptom is resolved.
- Final delivered version: 0.9.2, active Host, 126 passing tests, byte-matched installed files, one approved DSH restart total. The final Client fix applied without a second restart. Code and evidence backed up to origin/fix/tts-dsh-020-compatibility.
- Limits: no independent visual light/dark audit or exhaustive live seek/rate/pause control testing. Browser playback confirmation comes from the user, not the agent's inaccessible browser tool.

## Installation history (superseded by final acceptance)
- Directory installation created a source symlink whose peers did not resolve. Installing an archive over the same link retained the link; removed only this inactive bundle through Plugin Manager and reinstalled packed 0.9.1. The installed path is now profile-local and imports successfully in a fresh process.
- Plugin Manager first returned restart-required. Live import remains failed after reinstall in the existing process; cached old module resolution is suspected, not proven. No DSH restart performed. Row selection is enabled, but the Host entry is not active.
- User subsequently approved continuing and one DSH restart if necessary, asking to check hot activation first. A supported disable/enable cycle returned applied for disable and failed-to-import for enable. Installed Plugin Manager README explicitly requires restart for package replacements; implementation returns restart-required when the dependency existed before installation.
- Restart handoff: old MainPID=1215155, ExecMainStartTimestamp=Mon 2026-09-28 21:08:43 UTC; Restart=always, User=dsh, KillSignal=15, caller UID=999. Ordinary systemctl restart failed with Interactive authentication required (exit 1); /proc/1215155/status confirms UID=999 and NoNewPrivs=1. The documented single TERM fallback is now being issued to this exact old PID under the user's approval; consider approval consumed if this process disappears. After any successful restart DO NOT repeat it. Check new PID/start time and live ui-teratts Config/service.
- Pre-restart unauthenticated localhost root responds HTTP 401, not 200; preserve the existing auth boundary. Browser tool cannot reach localhost (separate host) or resolve the Tailnet hostname; no credentials searched or changed. Browser/audio acceptance remains unavailable until an authenticated reachable page exists. Do not claim TTS restored based on unit tests alone.
- Visual light/dark contrast and button/player interaction: NOT VERIFIED; existing styling retained, not redesigned. Module contract and lifecycle: PASS. README factual/command review: PASS.
- In-session code review only; no authorized explicit Gemini/Opus delegation route was available for independent review.
