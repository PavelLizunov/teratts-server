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

Implementation pending. Backend availability and safe deployment path are being inspected separately.
