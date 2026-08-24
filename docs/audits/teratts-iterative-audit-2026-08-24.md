# Iterative swarm audit — 2026-08-24

Three read-only rounds, 15 Gemini workers (`ninitux/gemini-3.7-flash-high`): adversarial code review, test-gap/mutation review, release/runtime consistency. Lead verified all High/Critical and implemented approved remediation. No runtime restart/deploy occurred.

## Closed findings

- Cancellation: async handler owns admission permit; Drop guard signals cancellation; bounded workers check between chunks, always join, panic broadcasts cancel, root error outranks generic cancellation. Current ORT `Session::run` remains non-interruptible mid-chunk.
- Thread-product: slots automatically clamp so `slots × ORT_THREADS ≤ available_parallelism`.
- SSRF: exact TeraTTS Tailnet host or HTTP loopback only; bearer resolved only after validation; HTTP redirects rejected.
- Host response: 16 MiB bound for Content-Length and streaming; AbortError preserved; safe client errors; Retry-After rejects non-finite values.
- Client cleaning: preserves `<ru>/<en>`, converts snake_case boundaries, cleans table cells, preserves comparison expressions and leading years, handles parenthesized Markdown links, removes Russian symbol/code injection, delegates units to speech-front.
- Speech-front: ISO dates, decimal units, URL lexicon boundary, hyphenated technical identifiers; ISO datetime is preserved whole instead of corrupted.
- Textnorm: manual stress no longer disables bounded chunking; untagged gaps around language spans are wrapped in request language instead of dropped.
- Numbers: Russian decimals ending in 21/51 retain tens; integers ≥10^12 fail closed instead of panicking.
- Auth scheme now case-insensitive (`Bearer`, `bearer`, `BEARER`).
- DSH profile: taskboard tgz moved from `/tmp` to persistent package store; `time-context` converted to valid `insert`, and `dsh --dump-config` succeeds. No DSH restart performed.

## Critical rejected

Swarm alleged punctuation-index misalignment in RUAccent. Rejected: pinned Python neural corpus explicitly covers punctuation followed by later words (`ёлки-палки, замок!`, `...столе, а это...`, `Все пришли, и всё...`) and passed 7/7 on model assets. `src/ruaccent.rs` was unchanged in remediation. Any mapping change requires a new pinned Python differential case first.

## Remaining limitations / Medium backlog

1. Native ORT call cannot be interrupted mid-chunk; cancellation takes effect before the next chunk.
2. Active runtime remains older release until an announced TeraTTS deployment.
3. DSH plugin 0.7.2 and time-context config require an announced external DSH restart.
4. Linux final test/clippy could not run because linux-worker DNS could not resolve static.crates.io; full macOS suite passed and Linux must be repeated before deployment.
5. FP32 remains production; INT8 synthetic calibration is invalid for encoder and not deployed.
6. Crossfade need remains hypothesis pending waveform boundary analysis/listening.
7. Speech-front additional Medium cases remain: ISO year suffixes, ranges with unit suffixes, abbreviation sentence-period preservation.
8. Client error retries are surfaced but no automatic bounded retry is implemented.

## Verification

- Node plugin tests: 31/31 passed.
- Rust macOS: 80 passed, 1 model-backed ignored; strict Clippy clean.
- Existing pinned RUAccent model-backed differential: 7/7 (prior verified evidence); re-run on Linux model worker required before deployment.
- Profile dump-config: exit 0; time-context present; taskboard dependency persistent.
