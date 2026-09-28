# Security & Adversarial Review Report

- **Review Run ID**: `run-20260922-1407`
- **Reviewed Scope**: `src/markdown_speech.rs`, `src/server.rs`, `dsh-plugin/lib/coordinator.js`, `dsh-plugin/lib/index.js`
- **Methodology**: Differential Security Review (Grok Adversarial Swarm + Gemini Lead SOL)

---

## 1. Trust Boundaries & Input Validation

### Finding SEC-01 (Severity: High): Output limit bypass via tag balancer appending unclosed language tags
- **Path**: `src/markdown_speech.rs:241-244, 436-445`
- **Mechanism**: The streaming `OutputSink` enforces `MAX_OUTPUT_BYTES = 128 KiB` for parser events. However, `balance_language_tags` executes after parsing on the raw buffer string and appends closing tags (`</ru>`, `</en>`) without checking the byte budget.
- **PoC**: An input with 14,564 unclosed `<ru>` tags (58 KiB input) results in 131,077 bytes output (exceeding 128 KiB).
- **Remedy**: Make `balance_language_tags` fallible or re-check string length against `max_output_bytes` before wrapping in `Ok(PrepareOutcome)`.

### Finding SEC-02 (Severity: Medium): Inline HTML tags copied to warnings
- **Path**: `src/markdown_speech.rs:416-418`
- **Mechanism**: Non-language inline HTML (e.g. `<b>`, `<script>`) is stripped from the spoken text, but the raw tag string is copied into the `warnings` array in the JSON response. While JSON-encoded responses do not execute in browser DOM, excessive inline tags (e.g. 64 KiB of `<b>z</b>`) can generate hundreds of kilobytes of warnings in memory.
- **Remedy**: Replace raw HTML tag copies with an aggregate warning code and count (e.g. `{"code": "inline_html_stripped", "count": N}`).

---

## 2. Network & Denial-of-Service Resistance

- **ReDoS / CPU Exhaustion**: Tested against pathological Markdown (deeply nested lists, blockquotes, 64 KiB of `*`, unclosed code fences). `pulldown-cmark` completed all inputs in $\le 29$ ms without unbounded recursion or stack overflow.
- **Retry Amplification**: Single client retry behavior is strictly bounded (`maxRetries <= 3`, jittered backoff, non-retryable 4xx errors, `backgroundRunning <= 1`). No retry storms observed against the Tokio semaphore.
- **Input Cap**: Enforced upfront before parsing (`raw.len() > MAX_INPUT_BYTES` rejects immediately with 400).

---

## 3. Residual Risks & Hardening Recommendations

1. **Defensive Floor on Leases**: Implement a timestamp purge for expired foreground leases in `isForegroundActive()` so tab crashes cannot indefinitely pause speculation.
2. **Prepare Job Promise Wrap**: Enclose the queue-wait `await` in `coordinator.js` inside the `try/finally` block to prevent rejected promises from being retained as deduplication entries.
