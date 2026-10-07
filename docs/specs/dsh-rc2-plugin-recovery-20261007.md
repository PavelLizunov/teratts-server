# Restore TeraTTS after failed unrelated bundle installation

## Requested result and authorization
User asked whether the earlier bundle installation broke TTS, then explicitly ordered repair. Restore existing TTS behavior in current DSH GUI without restarting chats or changing voices/endpoints. Then finish original authorized system-contract installation.

## Observed cause
Failed plugin_manager operation-lUDlwH installed then rejected an unrelated execution-contract bundle because dsh-client-ui-teratts@0.9.2 pins six DSH peers to 0.2.0-rc.1 while runtime is 0.2.0-rc.2. Manager restored manifest/lockfile but node_modules reinstall failed. Package files remain and manifest enables bundle, but live Config has no dsh-client-ui-teratts entry, Service has no terattsVoice and Client assistant-actions Slot contains feedback only. Do not claim that files existing proved TTS functional.

## Baseline evidence
Full current-runtime suite: 129 passed, 1 failed of 130. Sole failing test is peer-manifest mismatch. Real Cordis Host mount, Typert descriptor/client gateway and playback regressions pass. Local installed source and repository plugin are version 0.9.2.

## Implementation scope
- dsh-plugin/package.json: new 0.9.3 release, exact rc.2 peers only after behavioral compatibility suite.
- test runtime wording/helper, peer packaging regression as needed; keep behavioral checks intact.
- owning README target/version and local verification evidence.
- Durable npm-packed archive installed via plugin_manager. No manual profile mutation, version exemption or TTS server deployment.
- Record incident about disabled feature after failed installer rollback; no raw secrets/session export in ledger.

## Verification
All 130 plugin tests pass against actual rc.2 dependencies, including strict Remote codec integration, Host lifecycle and player controls. Manager application live result, Config/Service presence and Client Slot action registration must be observed. One short synthesis via actual Host logic and existing authorized credential retrieval: assert nonempty WAV/audio, no bearer printing. Browser-client confirmation if available through authorized tools; do not equate Host synthesis to physical audible playback. Existing TTS endpoint/voice unchanged. No DSH restart without fresh authorization.

## Delivery
Dedicated task branch commit/push of task-owned changes only; retain prior user artifacts. Update original audit delivery report accurately, then install system-contract once the dependency gate is genuinely resolved. Restore TTS first.

## Result
- 0.9.3 exact rc.2 peers; 130/130 tests passed; packed SHA256 b339113cbcf85226cb145c2152c0796c92d678eded754c1975146385e8016d9c.
- plugin_manager operation-FENDgi installed successfully but returned restart-required. User declined a restart; no restart performed.
- Isolated invocation of installed TeraTtsVoiceService using documented existing credential returned valid audio/wav: 306256 bytes in 556 ms. Gateway health ready, primary_configured=false (CPU synthesis available); no remote server configuration changed.
- Subsequent authorized execution-contract installation operation-QU756O returned application=applied and recomposed Host graph. Live include:ui-teratts fiber active; Client assistant-actions Slot contains teratts action. The execution-contract fiber is also active. No version exemption or manual profile patching.
- terattsVoice is not declared in the static Service catalog: catalog absence alone cannot establish missing runtime service. Client registration plus active Host entry and synthesis checked; physical playback on user's device unverified.
- Incident INC-1404 recorded; ledger digest notes earlier mistaken assumption that files remaining meant feature functional.
