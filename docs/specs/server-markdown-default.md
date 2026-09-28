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

### Delivery Gate Verification (Prose)

- PASS: README claims are grounded in code and executed checks; no invented metrics or quotes.
- PASS: Documentation states defaults, opt-out, limits, and forwarding behavior directly.
- PASS: The HTTP section links the default behavior to client usage and its limits without unrelated rewrites.
