# Russian translation and speech endpoint

## Outcome and authorization

The owner requests a separate endpoint accepting selected text in any source language and returning Russian speech. Implement `POST /translate/tts` without changing `/tts`, `/prepare`, STT or the existing Mac editor. Source language is detected by the translator; language coverage and semantic quality depend on the configured model, not an unconditional every-language guarantee.

## Design and invariants

- Extend the Rust/Axum server and reuse reqwest and the existing TTS handler. No new dependencies or replacement speech engine.
- Optional operator-configured OpenAI-compatible translation backend with fixed translation instruction, model, URL and token. Callers cannot select destinations, prompts or models. The existing Mac8095 editor is not a generic completion endpoint; do not send translation prompts to its fixed editor route.
- Request: `text`, optional Russian `voice`, `duration_scale`, `russian_stress`, `speech_front`; plain selected source text, maximum 2,400 Unicode characters. Output: existing mono 44.1 kHz PCM WAV with `Content-Language: ru`.
- Authenticate before dispatch. Validate speech options before translation. Bound concurrent translation, timeout and upstream body. No retries, original-language fallback, reasoning speech or truncated translation. Validate final translation length before TTS. Keep existing TTS admission, remote-primary/fallback and cancellation behavior.
- Translation and synthesis have separate bounded stages and a shared 55-second outer response deadline; translation capacity is released before joining the synthesis queue. Existing clients and plugin remain unchanged; document endpoint usage for selected-text clients.
- A separate Python standard-library Mac wrapper reuses the installed QAD Engine.send lifecycle, shared vision.lock and pinned model/runtime. It never calls or edits the editor routes. Native completion retains its six-second deadline, so long translations may fail; this must remain explicit. No model download is currently needed.

## Verification

- Model-free tests using local mock HTTP: authentication, disabled configuration, input and voice validation, fixed prompt/model and unmodified source, final-only parsing, refusal/truncation/empty/oversize response rejection, timeouts, single request/no retry, translation-to-TTS handoff and WAV response.
- Run relevant Rust tests, scoped formatting/diff review, document configuration and limits. Preserve unrelated files and active branch/index; commit and push a separate checkpoint branch and verify remote SHA.
- Inspect available Mac model and live TTS deployment. Attempt an authorized consumer-level check only through supported existing access; record exact deployment and native-verification limits rather than equating mocks with translation quality.

## Search verdict

Verdict: Extend — existing Axum TTS handler plus installed reqwest. The source repository already implements auth, bounded TTS admission, WAV handling and optional HTTP primary. No translation implementation exists here. Mac8095 is a fixed-purpose editor and requires a separate backend route or another configured general completion service.

## Status

Source revision `372b7ef3b555c536a2551b6d84ea4e3e674b202d` is published on `checkpoint/translate-tts-20261029`, with active checkout branch and index preserved. The separate Mac LaunchAgent and CT221 TTS release are active at that revision. Existing activate.sh completed successfully and verified exact-SHA readiness. The acquired Linux worker was released and stopped.

## Verification and deployment observations (2026-10-29)

- Existing QAD8095 and Bolt8094 both enforce fixed editing contracts, so neither can accept a translation instruction. A separate loopback8096 adapter reuses the pinned LFM3-1.7B QAD-Q4_0 runtime without modifying either service. Shared lock, resource checks and exact child cleanup remain in Engine.send. The separate process replaces only its native response reader to validate the complete envelope before normalization; installed editor files/processes are unchanged.
- Independent source review identified upstream429 flattening, CRLF incompatibility with russian_only, and loss of refusal/function_call/choice-count metadata in the reused native transport. These were corrected before source372b7ef: preserve429, normalize newline encoding, and validate the raw translation envelope in the separate adapter. Regression fixtures cover all three. Independent focused re-review confirmed the corrected Python blobs match deployed372b7ef and resolved the transport defect. Besides4/4 committed tests, an in-memory integration exercised actual main wiring→Handler→Engine.send/_send_owned with mocked OS/network/process calls: valid200, refusal/function_call/tool_calls/multiple-choice502, exactly one submission, normal child/monitor/listener cleanup, and fatal lock retention after injected reap failure. The original editor transport/module objects were not mutated. This is lifecycle simulation, not a second live deployment check; no serious introduced defect was found in that bounded scope.
- Python adapter tests passed4/4 on control-plane and Mac. Rust compiled with pinned dependencies on Mac:150passed/4ignored. Linux worker exact committed source:152passed/4ignored (two additional Linux-specific tests), release build succeeded. Ignored checks require installed converter/assets; none is a newly skipped translation check. Binary SHA256 `3796f0f6a4e23082e653e81c040082c6a47af2eb1240614c21fc6772c1d0f268`.
- Native short translation checks returned200 for English, German and Chinese. German and Chinese preserved the save-file/do-not-restart instruction; a second English case preserved17lines and backup negation. The first English case added an unsupported morning qualifier to 'at ten'. This quality miss is retained, not hidden by successful protocol tests. Observed complete requests were2.32–2.44seconds; these four short cases do not establish all-language or long-text quality/latency. All four child processes were reaped, listeners closed, loaded:false afterward. Receipts are under `evidence/translate-tts-20261029/`.
- CT221 still uses telemetry8090→TTS8088, with60second upstream timeout. No Serve/telemetry change. Existing CPU settings, two chunk slots, speech-front/russian_only configuration and bearer remain intact. Translation has55second total wait.
- Mac HTTPS8443 publication was tried but CT221 had DNS failure and TLS timeout even with explicit resolution. The task-owned Serve mapping was removed; original empty Mac Serve state restored. Use the verified SSH tunnel instead: CT221127.0.0.1:18096→Mac127.0.0.1:8096. Dedicated key permits only forwarding to8096; Mac host key was pinned from the authenticated management path. `teratts-translation-tunnel.service` is enabled. Authenticated health from CT221 through this actual consumer path returned200, model `lfm3-qad-translate-ru-v1`, loaded:false.
- Translation configuration was appended to existing CT221env without replacing any prior value. Token transferred in memory/stdin, not command-line arguments or evidence. Timeout25000ms.
- Linux worker initially waited for the existing Windows owner. After acquisition, its Tailscale SSH/DNS were unavailable; verified QGA LAN192.168.0.99 and original host key worked. A committed Git bundle supplied exact source without mutable-source transfer. Worker release requested after binary collection.
- Existing verified ORT1.27 dylib was reused rather than downloading another archive; its pinned SHA256 `4061866361d9a8d2872f5f419c5515ce35a830a0c5c77ce1723320ac0dbabfc7` and new binary hash checked before immutable release installation. Activation uses existing activate.sh with health gates and rollback to170d123f6488ca56fe7e37ace00588c99985c7ea.

## Remaining acceptance limits

Real native translations were checked, and translation-to-WAV byte handoff passed with mock HTTP synthesis. Actual end-to-end production audio and physical playback are not yet verified: this session's available local audio generator targets YuE2/Music3/Drama3 rather than the installed TeraTTS endpoint, and the session requires local audio generation through that tool rather than shell/browser POSTs. Do not substitute an unrelated voice model or label mock WAV as real production speech. Deployed public HTTPS health confirmed exact runtime372b7ef and translation_configured:true; unauthenticated/empty/English-voice/unknown-option requests returned401/400/400/422 respectively. Initial smoke expectation400 for unknown fields was corrected to Axum's actual422; application behavior was not altered to match the test. Receipt: `evidence/translate-tts-20261029/deployed-http.json`. No Omarchy hotkey/provider configuration was changed. Source language is auto-detected but no model can be claimed to support every language from these samples; long text may exceed the retained six-second native deadline.

## Documentation delivery gate

PASS: no fabricated quality/performance claims; actual tests and native observations are separated. PASS: API, limits, failure behavior and deployment state are explicit. PASS: existing README structure retained, task-specific additions only.
