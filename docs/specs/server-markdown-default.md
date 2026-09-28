# Server-side Markdown cleanup by default

## Intended result

Clients sending `POST /tts` without `input_format` receive the existing server-side Markdown-to-speech preparation before validation, remote forwarding, or local synthesis. No client/plugin update is required.

## Scope and invariants

- Change only the `/tts` missing-field default to `markdown`. Keep explicit `plain` as an exact preparation bypass and explicit `markdown` behavior; `/prepare` keeps its existing plain default.
- Reuse `markdown_speech` and pulldown-cmark, including existing bounds, admission, language handling, and HTML rejection. Enable strikethrough parsing so common `~~text~~` formatting is removed too.
- Forward already-prepared text with explicit `input_format: plain` to prevent double preparation on an updated primary, including when the original caller explicitly requested plain.
- Preserve plugin behavior (it already sends explicit plain), authentication, voice/text-mode validation, limits, CLI behavior, and inference. No new dependencies or deployment/service restart.
- Default Markdown interpretation may alter literal syntax and punctuation; callers needing literal/prepared input must select plain. This is intentional and must be documented.

## Verification

- Model-free request deserialization and real handler tests cover omitted/explicit formats, cleaned text reaching a mock primary, English task lists, plain bypass, empty/oversized/unsupported HTML rejection, and authorization before parsing.
- Existing Markdown tests cover headings, links/images, code, tables, language spans, and bounds; add emphasis/strikethrough regression coverage.
- Run Rust tests and task-scoped diff checks; verify README default, opt-out, and forwarding semantics against source.
- Review the changed trust-boundary flow locally. No authorized explicit Gemini/Opus tool route is available, so independent review is not claimed.
- Commit only task-owned changes and push a dedicated branch to origin. Live deployment/audio acceptance remains unverified and is not part of this source change.

## Initial evidence

- `/tts` currently uses `#[serde(default)]` with `InputFormat::Plain`, and prepares only `Markdown` requests.
- Plugin synthesis sends explicit `plain`; its preparation call uses explicit `markdown`.
- Remote forwarding currently omits `input_format`; changing the public default without pinning forwarding would prepare twice.

## Results

Implemented against base `cfa3259e18b1e84bbfb8001262fe58db796ec208`; tested implementation `5cff27e744a19d24350ef32dc061f48bc2a23f00` on branch `fix/server-markdown-default`.

- Red: worker revision `913836a`, `cargo test --offline --locked --bin teratts-server input_format_defaults_are_endpoint_specific`, exit 101: actual `Plain`, expected `Markdown`.
- Green: isolated Linux worker checkout of `5cff27e`, `CARGO_BUILD_JOBS=2 cargo test --offline --locked --bin teratts-server`, exit 0: 146 passed, 4 ignored (external converter/model assets required).
- Plugin compatibility: `node --test dsh-plugin/test/prepare-cache-shadow.test.js dsh-plugin/test/clean-markdown.test.js`, exit 0: 47 passed.
- Complete task diff: `git diff cfa3259e18b1e84bbfb8001262fe58db796ec208 HEAD --check`, exit 0. Owning README updated and reviewed against implementation; no new links or dependencies.
- Initial local Cargo attempt was unavailable on PATH (127); discovered toolchain invocation was rejected by the control-plane build wrapper (1). No bypass used. Builds ran on the documented Linux worker with 34 GiB free, exact committed revisions, and two build jobs. No service restart or deployment.

### Focused trust-boundary review

- Inspected the task diff and historical blame of the default (`fd93361e` introduced explicit-format preparation).
- Flow: JSON deserialization -> authorization in handler -> bounded Markdown preparation/admission -> existing text/voice/mode validation -> primary or local synthesis. The change selects the existing bounded path; no new file access, execution, egress destination, logging, or dependency.
- Executed handler tests confirm authorization failure precedes Markdown error handling; empty, oversized, and unsupported block HTML input is rejected before inference. Real loopback mock-primary requests confirm cleaned text, explicit plain forwarding, and unchanged returned WAV bytes. Existing fallback/admission tests pass.
- No new security defect confirmed within this differential review. This is not a full audit of the existing Markdown parser/preparation rules or a security certification.

### Limits and activation

- Existing parser behavior is reused rather than made byte-identical to the plugin cleaner. Literal Markdown syntax and paragraph punctuation can change; explicit plain is the escape hatch.
- Independent review was unavailable through the permitted tool routes; review above is coordinator-only.
- Real model inference, production deployment, and listening acceptance were not run. The source is verified, but the currently running server has not been updated. Next activation step is a separately authorized TTS deployment and live-client smoke check; no DSH restart is needed for this source change.
- Unrelated preexisting untracked files were left untouched. Implementation and tests were pushed to the dedicated origin branch; this record is committed separately without changing the tested source.

## Authorized activation follow-up

User explicitly requested activation after source delivery. Deploy tested source `5cff27e744a19d24350ef32dc061f48bc2a23f00` to the existing CT221 TTS service only. This extends the initial source-only scope; no DSH, GPU, tunnel, model, credential, or runtime tuning changes.

Preflight: live Tailnet health reports ready, current app `fd93361eeff9b3141c7e6298eca97d0044c66411`, full RUAccent, no remote primary, empty queue. CT221 service PID 57138, current immutable release matches health, 12 GiB free. Linux build worker has 33 GiB free and a clean exact tested checkout, Rust 1.98.0 / Debian glibc 2.36. `/srv/staging` is absent (read-only listing exit 2); use a dedicated task staging directory instead.

The deployed baseline predates the source branch: release also contains the branch's existing speech-front normalization/converter and lexicon-refresh changes (reviewed deployment delta, all covered by the previous full suite); no model assets or dependency lock changes. Installed activation/install/common/health/ORT metadata helpers hash-identically match the reviewed repository versions. The installed ORT dylib matches the pinned hash; official archive independently downloaded and verified for the standard installer. Both builder and target use glibc 2.36.

Plan: build exact-SHA CPU release on the worker; verify artifact hash, preserve pinned ORT and old release; install new immutable release; check queue idle immediately before invoking the existing verified activation/health/rollback mechanism over management SSH. A brief TTS interruption is authorized; DSH remains untouched. On failed activation, restore the exact old release using the activation script's rollback. Live acceptance: exact new SHA/readiness, authenticated default Markdown WAV equal to explicit Markdown and cleaned plain WAV, unsupported/empty Markdown rejection, and unauthorized request rejection. Use credentials only in-memory on the service host and do not print/store them. Record results and push the task branch.

### Activation evidence (completed 2026-09-28)

- CPU release built on Linux worker from clean `5cff27e744a19d24350ef32dc061f48bc2a23f00` using `CARGO_BUILD_JOBS=2 CARGO_NET_OFFLINE=true deploy/linux/build-release.sh`; build exit 0. Binary SHA-256 `246020e9eed54f271f34e71870ec56019fe31b09ecba4cad8e1a88cd4b422d2a`. Dynamic dependencies resolve on Debian 12, no ELF-linked ONNX Runtime.
- Verified hash again after authenticated transfers. Standard installer exit 0 published immutable release on CT221 with pinned ORT SHA-256 `4061866361d9a8d2872f5f419c5515ce35a830a0c5c77ce1723320ac0dbabfc7`.
- Exact-old-release/current-link/idle-queue guard passed immediately before activation. Existing activation script completed its single TTS restart and exact-SHA health gate, exit 0. No rollback was necessary; old immutable release remains available.
- Runtime: `teratts.service` active/running, PID changed 57138 -> 92474, start 2026-09-28 22:48:34 UTC, listener remains 127.0.0.1:8088. Tailnet HTTPS health independently returns ready, exact new SHA, verified model, full RUAccent, and no primary. This proves reachability from the management host, not a browser on the user's device.
- Live acceptance script (Python stdlib, bearer read in-memory from service environment, no credential output) exited 0. `/prepare` returns `Проверка. Это важно и ссылка.` from a heading, bold text, and a Markdown link, preparation revision `prep-v2-cmark-0.13.4`.
- Real `/tts` in the retained default `russian_only` mode: omitted format, explicit Markdown, and prepared plain each returned HTTP 200 and identical 222,668-byte mono 16-bit 44.1 kHz WAV (2.5240816326530613 seconds), SHA-256 `3da605a6137dd25538780825dee20d703ebd18f3d33ea651b70135dfd3a3cde2`.
- Empty Markdown and unsupported block HTML return 400; unauthenticated TTS returns 401; plugin-style plain `Проверка API.` returns 200 with nonempty WAV, exercising the retained technical-term pipeline.
- DSH, credentials, configuration, models, and GPU services were not modified/restarted. Listening acceptance and the user's particular third-party client remain untested; server-side inference and format equivalence are verified. Current source-only deployment limitation above is superseded by this activation evidence.

### Delivery Gate Verification (Prose)

- PASS: README claims are grounded in code and executed checks; no invented metrics or quotes.
- PASS: Documentation states defaults, opt-out, limits, and forwarding behavior directly.
- PASS: The HTTP section links the default behavior to client usage and its limits without unrelated rewrites.
