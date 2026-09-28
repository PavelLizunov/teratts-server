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

Pending implementation and checks.
