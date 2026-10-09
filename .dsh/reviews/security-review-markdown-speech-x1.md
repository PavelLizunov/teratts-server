# Security review: markdown speech preparation (reviewer X1)

- **Range:** `6432ad33a423703e6bf9059b69f8787315decfce..5e0490e27d5b1e0bc114c73e47f332fdc9c9b440`
- **Scope:** `src/markdown_speech.rs`, `src/server.rs` (`prepare`, markdown branch of `tts`), downstream `textnorm` / `russian_only` only where prepared text reaches them.
- **Method:** source read plus a local harness that compiled `src/markdown_speech.rs` against the already-built `pulldown-cmark 0.13.4` rlib and called `prepare_markdown_to_speech`. No server was started. No network.
- **Not proven:** live `/prepare` and `/tts` HTTP, model inference, or a panic inside ORT. Parser timing is local CPU only.

## Findings

### 1. HIGH — Confirmed — `MAX_OUTPUT_BYTES` is bypassed after the sink

- **Claim:** `balance_language_tags` appends one `</ru>` / `</en>` per unmatched opener with no byte check. `prepare_markdown_to_speech` returns `Ok` for that string.
- **Violated invariant:** output must be at most 128 KiB (`MAX_OUTPUT_BYTES`).
- **Path:** `POST /prepare` with `input_format=markdown` (`server.rs` 460–475 returns `outcome.text` unchanged). Markdown `POST /tts` assigns the same string to `request.text` before the 2400-character gate.
- **Lines:** `src/markdown_speech.rs` 241–244, 436–445. Callers: `src/server.rs` 460–475, 522–538.
- **Causal explanation:** `OutputSink::push_str` enforces the cap, but the balancer runs on the trimmed sink and is infallible. Each `<ru>` is 4 bytes in and 9 bytes out once the closer is appended (plus one trailing period from `ensure_sentence_end`).
- **Evidence (executed):**
  - 14,563 openers (58,252 bytes) → 131,068 bytes (under the cap).
  - 14,564 openers (58,256 bytes) → **131,077 bytes** (`Ok`, 5 bytes over 131,072).
  - 16,384 openers (exactly 65,536 bytes) → **147,457 bytes**, 16,385 over, 18 ms.
  - Same for `<en>`. `<ru><en>` repeated to 64,000 bytes → 144,001 bytes, `Ok`.
  - 600 openers = 2,400 input chars → **5,401 output chars**, so markdown `/tts` fails the later `MAX_TEXT_CHARS` check (`server.rs` 1050–1053) rather than synthesizing. `/prepare` has no character gate and returns the oversized body.
- **Attacker:** any caller who can POST markdown (bearer only if `TERATTS` token is configured; `authorize` allows all requests when no token is set, `server.rs` 1114–1116).
- **Recommended action:** run the byte cap after balancing (and after `collapse_whitespace`), or make the balancer fallible and stop at `effective_max_output`. Add a regression that `<ru>` × N under 64 KiB never returns `Ok` above 128 KiB.

### 2. MEDIUM — Confirmed — count-balancing does not make tags well-nested or well-ordered

- **Claim:** equal open/close counts are treated as balanced. Crossed, nested, and reordered `<ru>`/`<en>` pairs pass through. `textnorm::validate_language_tags` then errors. That is a handled `invalid-text` failure, not a panic or a silent drop, but it rejects inputs the balancer claims to repair, including nested spans it itself creates.
- **Violated invariant:** “balance and sanitize `<ru>`/`<en>`” (`markdown_speech.rs` 228) so downstream tag validation accepts the linear text. `textnorm.rs` 322–376 requires a matching stack, no leftovers, and no cross-language close. `russian_only::flatten_tags` (`russian_only.rs` 429–433) rejects an open while already inside a span.
- **Lines:** `src/markdown_speech.rs` 228–254, 437. Consumers: `src/textnorm.rs` 89–94 and 324–376; `src/tera.rs` 194–204; `src/server.rs` 1041; `src/ruaccent.rs` 175–177 (nesting rejected only on the test-only `russian_tag_spans` path; production `russian_span_ranges` is first-close, `textnorm.rs` 185–196).
- **Evidence (executed):**
  - `<ru><en>x</en>` → `<ru><en>x</en>.</ru>` (balancer introduces nesting).
  - `<ru>a</en>` × 3 → `<ru>a <ru>a <ru>a.</ru></ru></ru>` (counts match, languages cross).
  - `</en><ru>a</ru><en>` → `</en> <ru>a</ru> <en>.` (closer left in front; opener left at end).
  - `<Ru>текст</rU>` → `<ru>текст</ru>.` (case fold is exact-string only; the parser lowercases real tags, so this shape is rare).
  - Case-fold `replace` runs before counting, so it cannot inflate the output on its own.
- **Impact:** markdown `/tts` returns 400 at preprocess (`tera.rs` `invalid-text`), not a worker panic. `/prepare` returns the malformed tags as `text` with no warning. No silent deletion of the enclosed words was observed: the words stay inside the broken markup.
- **Recommended action:** walk a real stack (the same rules as `validate_language_tags`) and emit only non-nested, same-language pairs, or refuse. Do not append closers onto a string that already passed the byte cap. Add the three strings above as tests that either validate or return `PreparationError`.

### 3. MEDIUM — Confirmed — inline HTML is stripped as markup, but the raw tag is copied into the JSON warning

- **Claim:** non-language inline tags do not survive in `text`. They do survive verbatim in `warnings`, and `prepare` serializes that vector (`server.rs` 487–492).
- **Violated invariant:** stripped markup must not be reflected to the client. Block HTML is rejected; inline HTML is reflected instead.
- **Lines:** `src/markdown_speech.rs` 413–417; `src/server.rs` 487–492.
- **Evidence (executed):**
  - `see <script>alert(1)</script> now` → text `see alert(1) now.`, warnings `stripped_inline_html: <script>` and `stripped_inline_html: </script>`.
  - `hi <!-- SECRET --> there` → text `hi there.`, warning contains `<!-- SECRET -->`.
  - `<b ` + 4,000 `A` + `>z</b>` → text `z.`, warning length 4,026 (the whole opener).
  - 64 KiB of `<b>z</b>` (9,362–16,384 tags depending on padding) → text stays small, **warning payload 417,792 bytes** from a 65,536-byte input (6 ms). Response is uncapped relative to `MAX_OUTPUT_BYTES`.
  - Block forms (`<script>…</script>` at line start, `<div>`, `<!-- … -->` at line start) return `UnsupportedHtmlBlock` and do **not** reach `text`. The error string is the first HTML event, so a long opening line is echoed (`<div ` + 2,000 `A` → error length 2,030) via `server.rs` 472–474 and 534–535.
- **Not a browser XSS finding:** this service returns JSON for speech text, not an HTML document. The leak is reflection into the API body plus a response-size amplifier.
- **Recommended action:** warning text should be a fixed code (`stripped_inline_html`) plus a count. Cap the warning list. Truncate `UnsupportedHtmlBlock` to a short tag name before `ApiError::bad_request`.

### 4. LOW — Confirmed — entity-encoded markup is not a tag bypass; it is spoken as angle-bracket words

- **Claim:** `&lt;ru&gt;…&lt;/ru&gt;`, `&#60;en&#62;…`, and `&#x3c;…&#x3e;` do **not** become language tags and do **not** inject markup. pulldown splits them into separate text events (`"<"`, `"ru"`, `">"`). `clean_prose_text` then turns each bracket into `меньше` / `больше`.
- **Lines:** `src/markdown_speech.rs` 168–192, 364–375.
- **Evidence:** `&lt;script&gt;alert(1)&lt;/script&gt;` → `меньше script больше alert(1) меньше /script больше.` Same for `&lt;img src=x onerror=alert(1)&gt;` and `&lt;!-- secret --&gt;`. Direct `<ru>ок</ru>` stays a tag; the entity form next to it does not.
- **Residual:** attributes and `javascript:` URLs are spoken aloud when written as entities (`меньше a href=javascript:alert(1) больше click…`). Link/image destinations in real Markdown are dropped (`[click](javascript:alert(1))` → `click.`). Not markup injection.
- **Recommended action:** none for injection. If spoken entity debris is unwanted, drop text events that are only `<` or `>` produced by entity decoding, or decode-and-reject before `clean_prose_text`.

### 5. LOW — Confirmed — prose comparisons and code fences rewrite `<` / `>` and literal language tags

- **Claim:** outside code, `x < 0` is speech-rewritten, not parsed as HTML. Inside code, `<en>…</en>` is deliberately detagged. Neither path panics. Unclosed fences are consumed as code to EOF by pulldown and still finish.
- **Lines:** `src/markdown_speech.rs` 147–166, 168–192, 293–296, 331–333.
- **Evidence:** `if x < 0 and y > 1` → `if x меньше 0 and y больше 1 then stop.` `` `if x < 0` `` → `if x меньше 0.` Unclosed `` ``` `` + `<en>not a tag` → `en not a tag.` 64 KiB fenced body prepared in 3 ms.
- **Recommended action:** accept as intended speech normalization. Do not treat it as an HTML filter.

## Checked, not reproduced

| Question | Result |
|---|---|
| ReDoS / stack blow-up from nested Markdown, unclosed fences, 64 KiB `*`, `_`, `` ` ``, links, tables, blockquotes | No. pulldown-cmark 0.13.4 walks a heap tree; link paren depth is capped at 32 in the crate. Worst local `prepare_markdown_to_speech` on a 64 KiB input was **29 ms** (list of `- x`). No timeout, no panic. |
| `MAX_INPUT_BYTES` (64 KiB) | Held. `prepare_markdown_to_speech` rejects `len > 65536` before parse (`markdown_speech.rs` 262–266). Both handlers check first (`server.rs` 438–440, 513–515). Axum `BODY_LIMIT_BYTES` is 128 KiB (`server.rs` 30, 387), so the JSON envelope can exceed 64 KiB and still be refused by the text check. |
| Plain `input_format` vs the 128 KiB output cap | Plain `/prepare` returns `text.trim()` with no output cap (`server.rs` 447–458). Input is still ≤ 64 KiB, so this does not bypass 128 KiB. Plain `/tts` never enters the markdown limiter and is cut at 2,400 chars. |
| HTML injection into model text | Inline tags are removed from `text` (finding 3). Block tags abort. Entity forms become words (finding 4). No path observed that leaves `<script>…</script>` in `text`. |
| Malformed / empty tables and OOB slices | No panic. Empty cells are skipped. `| | |` with a separator yields empty text plus `no_speakable_content`. A row whose separator column count does not match is **not** a table: it is spoken as literal pipes (`| a | b | | --- | | c | d |.`). `table_cells` indexing is iterator-only (`markdown_speech.rs` 345–355). |
| Tag-induced crash or silent word drop | No panic in the balancer or table loop. Downstream invalid tags fail closed at `validate_language_tags` (finding 2). Words inside the spans remained in the prepared string. |

## Coverage

- Reviewed the markdown diff in the two named files. Did not audit synthesis, auth storage, or the plugin.
- Reproduction linked the current `src/markdown_speech.rs` (HEAD `5e0490e`, balancer unchanged since `f1dd904`) to the workspace `pulldown-cmark` rlib. It is not a `cargo test` run; local Cargo builds are blocked on this host.
