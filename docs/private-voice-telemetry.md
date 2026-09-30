# Private voice telemetry: activation and verification

## State

Initial homelab collection is already active separately from this TTS binary/plugin update: Deck STT requests and failures, TeraTTS ingress request/audio/error bodies, and complete native DSH journal snapshots. All use one Deck corpus and a 50,000,000,000-byte FIFO quota. This branch provides deeper internal text/draft/playback hooks. **These deeper hooks are prepared, not activated.** No approval for a TTS engine or DSH restart was recorded; the user asked to continue implementation.

## Configuration

Internal TTS metadata: environment `VOICE_TELEMETRY_INGEST=http://<private-tailnet-ip>:<port>/record`. Loopback and Tailnet IPv4 HTTP destinations only; credentials, query strings, public hosts and redirects are forbidden. Existing HTTPS/authenticated TTS serving remains unchanged. Storage encryption is not added; Tailscale secures node-to-node traffic.

DSH plugin: set `telemetryIngest` in the user-owned profile config, leaving `endpoint`, credential reference, voice, language and provider selections unchanged. Empty default disables recording. Install matching Host/client artifact through the normal supported deployment process. Do not silently replace the running package or shipped preset. No dev:web watcher was found, so automatic browser update is not promised.

## Records

- `tts_internal_stages`: original input; post-Markdown input; speech-front/text-mode output; structured preprocessed text/manual spans; chunk strings; voice/language/stress/duration scale; explicit HTTP correlation and server request ID.
- `voice_client_event`: draft and input state, original assistant text at playback request, playback state/rate/segment/error, synthesis request/failure, exact session/message/playback/request IDs if supplied by current hooks.
- `tts_client_result`: text submitted for this audio fragment and exact synthesized WAV bytes, including cached/prefetched results. Explicitly synthetic; no human-reference claim.

No transcript/name/content redaction. No transport token/cookie harvesting. Provider-neutral STT on the current DSH profile is configured as `sensevoice-local`, whereas Deck gateway serves Parakeet. Stock SpeechToText registry has no observation hook; it must not be assumed that every DSH microphone request reaches Deck. This remains a coverage gap requiring a supported wrapper/provider observer rather than core edits or silently switching models.

## Verification

- 136 JavaScript tests passed before final documentation updates, including actual Typert remote registration, real coordinator/cache lifecycle, draft hook render/effect and private transport encoding/failure isolation.
- Remote Linux worker: 152 Rust tests total, 148 passed and 4 model-dependent tests ignored under serial execution. An initial parallel run failed in the pre-existing child-process timeout test; serial rerun passed. No claim that the parallel suite is stable.
- Two new Rust telemetry tests cover private destination rejection and exact UTF-8 binary envelope.
- Release build succeeds on linux-worker; build metadata must be pinned to the task commit before any deployment. Control-plane compilation was blocked by policy and not bypassed.
- Packaged artifacts alone do not prove live client hooks or internal stage recording. No browser reachability/UI verification was available in this session.

## Safety and limits

Queues bounded: 16 internal metadata records, four outstanding plugin records. Errors do not cancel inference/playback. Ingest failure can drop records; this is not guaranteed lossless recording during outages. There is no independent disk spool/second 50 GB quota. Draft events reflect rendered editor state, not each physical keystroke. Playback is browser-observed state, not an acoustic recording.

Cross-service IDs retained where explicit. Shared inference/prefetch may originate before a playback request; client audio result is linked to playback, not falsely relabeled as fresh inference. Missing IDs stay missing, not timing-based fabricated relations.

## Rollout gate

1. Verify immutable release/app commit hashes, all task tests, native model health and on-Deck ingestion.
2. Obtain fresh single-use approval for one TTS engine restart; keep rollback release/config available.
3. Obtain separate explicit DSH activation approval, warning that a DSH restart interrupts all Web chats and running jobs. Prefer verified supported plugin reload if available; do not invent hot reload.
4. Live synthetic tests must show stage text, draft, exact message/session IDs, cache-hit audio and playback events in the managed corpus; remove only those fixtures.

Until step 4 passes, describe these hooks as prepared, not active.
