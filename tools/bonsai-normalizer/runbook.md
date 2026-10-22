# Runbook: Mac Bonsai 9B Neutral Transcript Normalizer

**Component:** Optional post-STT neutral transcript normalizer on Steam Deck gateway.
**Hardware & Topology:** Steam Deck (`100.110.84.30`) -> Mac mini M4 (`100.116.97.112:8091` or local SSH tunnel `127.0.0.1:18091`).
**Model:** `prism-ml/Ternary-Bonsai-2-9B-mlx-2bit` (`f4e28a59531731c41b6dfac88cf271bd58f0a287`).

**Current status: rejected for activation.** No production normalizer, configuration or drop-in is installed; accepted speech and the dedicated tunnel remain unchanged. The unchanged constrained selector passed its first narrow screen but then deleted literal meaning in 3/4 fresh held-out outputs. All four responses passed syntax, identity, finish and schema acknowledgement and reached `applied`; no fallback caught the errors. Complete useful edits were 1/3, with 0/1 literal-only abstention. See the [held-out receipt](<constrained-heldout-20261021.json>) and [task record](<spec.md#fresh-contextual-held-out-selector-screen-round-8>). Keep all deletion editors disabled. Native constraints control response shape, not semantic eligibility.

The deployment commands below are unexecuted instructions for the older free-text normalizer, not an activation recipe for the tested subclass: the factory does not select the constrained editor. Mac inference is available, but useful meaning-preserving editing, logical structuring and the actual voice/UI consumer are not accepted. No new deployment follows from protocol tests or the earlier narrow success.

---

## Actual dictation client

The owner uses **Voxtype on their own Omarchy computer, holding Insert, with online transcription**, not the DSH built-in microphone. The actual endpoint, installed version, output driver, newline behavior, timeout and auto-submit configuration have not been inspected: the online owner machine currently refuses SSH. The separate `omarchy-test` VM is not that client and has no Voxtype binary/service. No Voxtype/STT settings were changed.

[Current upstream configuration documentation](https://github.com/peteonrails/voxtype/blob/dev/docs/CONFIGURATION.md) describes a native stdin/stdout post-process hook with source fallback and profiles, but its availability in the owner's installed build is not yet verified. Inspect those owning settings only when a useful candidate is ready; preserve existing Insert recording, online recognition and active-field insertion. Do not silently replace it with DSH voice or infer its endpoint from the name alone. The deployment instructions below concern the separate gateway experiment, not an executed Voxtype integration.

## 1. File Placement on Steam Deck

| Source Path (Repo) | Target Path (Host) | Permissions |
|---|---|---|
| `tools/ruen-support-pilot/gateway-server.py` | `/home/deck/homelab/gateway/server.py` | `0644` |
| `tools/bonsai-normalizer/bonsai_normalizer.py` | `/home/deck/homelab/gateway/bonsai_normalizer.py` | `0644` |
| `tools/bonsai-normalizer/normalizer_config.example.json` | `/home/deck/homelab/config/bonsai-normalizer.json` | `0644` |
| Token (Bearer) | `/home/deck/homelab/config/bonsai.token` | `0600` |
| Systemd drop-in | `/home/deck/.config/systemd/user/voice-gateway.service.d/zz-bonsai-normalizer.conf` | `0644` |

---

## 2. Configuration & Activation

### 2.1 Systemd Drop-in
Create `/home/deck/.config/systemd/user/voice-gateway.service.d/zz-bonsai-normalizer.conf`:
```ini
[Service]
Environment=BONSAI_NORMALIZER_CONFIG=/home/deck/homelab/config/bonsai-normalizer.json
```

### 2.2 Config File (`/home/deck/homelab/config/bonsai-normalizer.json`)
```json
{
  "enabled": true,
  "endpoint_url": "http://127.0.0.1:18091",
  "token_file": "/home/deck/homelab/config/bonsai.token",
  "model": "prism-ml/Ternary-Bonsai-2-9B-mlx-2bit",
  "revision": "f4e28a59531731c41b6dfac88cf271bd58f0a287",
  "timeout_seconds": 12.0,
  "max_timeout_seconds": 20.0,
  "max_input_chars": 6000,
  "max_tokens": 1024,
  "temperature": 0.0,
  "top_p": 0.8,
  "top_k": 20,
  "min_p": 0.0,
  "presence_penalty": 0.0,
  "repetition_penalty": 1.0,
  "seed": 42
}
```

Configuration is read at gateway startup, not hot-reloaded. `enabled` must be a JSON boolean. The exact model and nonempty revision above are mandatory; temperature must remain `0.0`. Limits may be reduced but cannot exceed 6,000 input characters or 1,024 output tokens. Timeout/sampling fields must be finite JSON numbers with valid ranges, not quoted strings. Invalid configuration disables Bonsai and leaves accepted dictation available.

The optional client call runs in `asyncio.to_thread`, so its synchronous HTTP wait does not occupy the gateway event loop. Existing ASR/Loqira stages are unchanged and may still be synchronous. Concurrent Mac requests remain serialized by its service; this change is not a throughput claim, admission-control policy or remote-cancellation guarantee.

Timeout defaults to 12 seconds and clamps to a 0.1–20-second socket-operation timeout. It is not a measured end-to-end deadline against a server that trickles a body, and does not cancel remote inference. Bodies larger than 64 KiB, HTTP redirects, wrong response identity/revision and incomplete generations all return the accepted post-cleanup text. No retries or alternate model calls are made.

### 2.3 Token File
Ensure `/home/deck/homelab/config/bonsai.token` contains the Bearer token matching `mm4`'s `~/.localforge/bonsai9/token`. A configured unreadable, missing or empty token file returns `token_unavailable` without sending the transcript; it does not silently use an inline token. Omitting both token settings allows an unauthenticated request (normally rejected by the Mac service):
```bash
chmod 600 /home/deck/homelab/config/bonsai.token
```

### 2.4 Reload & Restart
```bash
systemctl --user daemon-reload
systemctl --user restart voice-gateway.service
```

---

## 3. Operational Verification

### 3.1 Check Readiness
```bash
curl -s http://127.0.0.1:10000/readyz | jq .
```
Expected output includes:
```json
{
  "status": "ok",
  "stt": "ready",
  "stt_backend": "parakeet",
  "corrector": {
    "status": "ready"
  },
  "bonsai": "configured"
}
```
*(Note: `/readyz` does NOT ping the Mac over the network to prevent cold-starts or latency spikes on health checks).*

### 3.2 Verify Default Dictation Bypass
Send standard dictation request:
```bash
curl -s -i -X POST "http://127.0.0.1:10000/v1/audio/transcriptions?mode=default" \
  -F "file=@test.wav"
```
Headers must show:
- `X-Bonsai-Status: bypassed`
- `X-Bonsai-Latency-Ms: 0.0`

`mode=raw` and `format=false` without `smart=true` also bypass Bonsai. Existing routing precedence is unchanged: explicit `smart=true` selects smart mode even with `mode=raw` or `format=false`. Dictionary and opening-cleanup opt-outs remain independent. Bypass time is the reported Bonsai-stage time, not a measured claim that adding response headers has literally no CPU cost.

### 3.3 Verify Opt-in Smart Rewriting
Send smart dictation request:
```bash
curl -s -i -X POST "http://127.0.0.1:10000/v1/audio/transcriptions?mode=smart" \
  -F "file=@test.wav"
```
Headers must show:
- `X-Bonsai-Status: applied` (or `fallback` if Mac is unreachable)
- `X-Bonsai-Latency-Ms: <ms>`
- `X-Bonsai-Model: prism-ml/Ternary-Bonsai-2-9B-mlx-2bit`
- `Server-Timing: ..., bonsai;dur=<ms>`

---

## 4. Rollback Procedure

If Mac Bonsai 9B experiences outages, instability, or is taken offline:
1. **Fallback in this source:** After a Bonsai error, rejection or socket timeout, the gateway returns `accepted_stt_text`. The smart request may wait for the timeout; this does not establish that the installed service already has this patch.
2. **Clean service rollback (disable integration):**
   ```bash
   rm -f /home/deck/.config/systemd/user/voice-gateway.service.d/zz-bonsai-normalizer.conf
   systemctl --user daemon-reload
   systemctl --user restart voice-gateway.service
   ```
3. Check `/readyz`: `"bonsai": "bypassed"`.

---

## 5. Troubleshooting & Status Codes

| `X-Bonsai-Status` | Reason | Diagnostic & Remedy |
|---|---|---|
| `bypassed` | `mode_bypassed` | Normal for `mode=default` or `mode=raw`. Expected. |
| `bypassed` | `unconfigured` | `BONSAI_NORMALIZER_CONFIG` is unset or invalid. |
| `fallback` | `timeout` | A socket operation timed out. Check Mac load / network; this does not prove inference was stopped. |
| `fallback` | `http_error_503` / `network_error_ConnectionRefusedError` | Mac service down or tunnel broken (`127.0.0.1:18091`). |
| `fallback` | `token_unavailable` | Configured token file was unreadable/empty; no transcript sent. |
| `fallback` | `response_too_large` / `http_error_30x` | Oversized body or redirect rejected; no redirect followed. |
| `fallback` | `model_mismatch` / `revision_mismatch` | Pinned weights on Mac changed; verify git revision on Mac. |
| `fallback` | `invalid_content_encoding` | JSON string contains a lone surrogate or other strict UTF-8 encoding failure; retain accepted text without character replacement. |
| `fallback` | `validation_numeric_missing` | Model omitted a numeric occurrence or changed its sign. |
| `fallback` | `validation_numeric_added` | Model added or duplicated a numeric occurrence. |
| `fallback` | `validation_latin_missing` / `validation_latin_added` | Latin identifier counts changed, including unexpected tags such as "Notes:". |
| `fallback` | `validation_negation_lost` / `validation_negation_added` | Negation count changed. |
| `fallback` | `validation_qualifier_lost` | One of the selected uncertainty/condition/order markers was omitted. |
| `fallback` | `validation_word_order_changed` | Candidate contains new, substituted or reordered word tokens, or no word tokens. Retain source instead of accepting rephrasing. |

## 6. Local regression checks and semantic limits

Run from the repository root without models or network:

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 -m unittest discover -s tools/bonsai-normalizer/tests -v
```

The default suite mocks HTTP and executes the actual gateway function AST with hardware dependencies stubbed, using the real dictionary and cleanup functions. The three full-ASGI cases are skipped unless `BONSAI_ASGI_TEST=1` is set in an environment already containing FastAPI, Starlette, httpx, multipart, numpy and Pillow:

```bash
BONSAI_ASGI_TEST=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/bonsai-normalizer/tests -p test_gateway_asgi.py -v
```

This optional test imports the full gateway module with only model/hardware initializers stubbed and exercises real FastAPI decorators, multipart/query handling, text/JSON serialization and two concurrent in-process ASGI requests. It opens no sockets, performs no model calls and does not start or patch production. Passing is framework-boundary evidence, not hardware startup, real audio/STT/model quality or the owner voice UI.

The default checks cover stage ordering, default/raw bypass, smart/format precedence, source fallback, headers and private corpus metadata. They do not establish installed FastAPI startup, the tunnel, pinned Mac identity or prompt compliance.

Observed optional framework check: the committed `da4d613a45ba89cf306a388541ef44ca632cd248` snapshot passed all3ASGI cases in1.089s using the existing Deck Python3.13 environment (FastAPI0.141.1,Starlette1.7.0,httpx0.28.1,python-multipart0.0.32). Real multipart/query routing, both response serializations, surrogate/exception fallback and a raw request finishing while smart normalization waited passed. The first snapshot had a test-only NumPy reimport isolation error after its first passing case; native imports were moved outside temporary module restoration before the complete rerun. No model/HTTP-socket calls, production mutations or restarts occurred; production gateway hash remained unchanged. The full actual voice consumer and semantic usefulness remain unverified.

A separate, factory-unselected literal-selection experiment is in [bonsai_literal_editor.py](<bonsai_literal_editor.py>). It inventories a finite set of locally shielded source spans, asks Bonsai only for deletion IDs, and copies all unselected characters exactly. Its frozen four-text screen produced2/3expected useful edits and1/1correct literal-meaning abstention. One fenced JSON response was rejected, so exact expected results were3/4and this candidate remains undeployed. No parser repair/retry hid that rejection; see the [screen receipt](<literal-screen-20261021.json>). Its transport and final lexical guards are inherited from the normalizer. With no eligible spans it bypasses the model; empty selection is `unchanged`, not successful editing. This is not a general neutral editor or a production configuration option: vocabulary is finite, unquoted literal evaluations still require contextual model abstention, and logical/newline formatting is deferred. See the [round-6 contract](<spec.md#literal-selection-mechanism-iteration-round-6>).

The further isolated [constrained editor](<bonsai_constrained_editor.py>) requests the fixed `bonsai_literal_selection` JSON-schema profile from the Mac adapter's native mlx-vlm/llguidance hook. It keeps the same prompt, finite inventory, strict ID parser and exact reconstruction, and requires the response to acknowledge the exact canonical schema SHA256; missing/wrong acknowledgement returns `response_format_unverified` with the exact accepted source. The normalizer factory does not select it and existing clients send no response format. Shape/type/range constraints do not prove a chosen deletion preserves meaning; duplicate/order checks remain client-side. No production Deck configuration enables this class. Its first frozen screen passed3/3exact useful deletions and1/1literal-story abstention in14.195s, with4/4complete schema-acknowledged responses and no fallback. Exact committed Deck tests passed99/99including3stubbed-framework cases; this is not actual voice/UI acceptance. That narrow success was superseded operationally by the [fresh contextual held-out screen](<constrained-heldout-20261021.json>): 1/4 exact expected outputs, 1/3 complete useful edits, 0/1 literal-only abstention and 3/4 literal-meaning deletions, with all outputs syntactically valid and `applied`. Reject activation; do not retune the consumed cases or add story-word exceptions. Logical structuring and actual consumer verification remain separate gates. See the [round-7 contract](<spec.md#native-schema-constrained-selector-round-7>) and [historical first receipt](<constrained-screen-20261021.json>).

The separate factory-unselected [paragraph structurer](<bonsai_paragraph_structurer.py>) is an insertion-only experiment, not a neutral editor. It inventories existing prose sentence boundaries and asks for `break_after` IDs; Python inserts exactly two LF characters at selected offsets while preserving every source character, including existing whitespace/newlines. It does not request the service's deletion-only schema profile, so malformed/fenced responses are rejected rather than repaired. Technical/markup or ambiguous quotation input is bypassed conservatively. These finite shields do not establish general scope safety or useful grouping; newlines can affect meaning and rendering. The production factory, gateway, modes and configuration do not select this class. See the [round-9 contract](<spec.md#literal-preserving-paragraph-selection-round-9>); no live grouping acceptance or production integration is claimed. Exact committed Deck framework tests passed 111/111 with model/hardware stages stubbed. At the historical round-9 preflight, the four-case live screen was not submitted: available memory remained 5.488968GiB after reclaiming only the idle dedicated Bonsai owner, below the chosen unchanged 5.5GiB admission threshold. No case was consumed in that preflight, so it yielded no quality score or throughput result. The [preflight receipt](<paragraph-preflight-20261021.json>) separates that stop from later evidence. The owner's subsequent native LFM unload supplied sufficient memory; the unchanged four-case [live screen](<paragraph-screen-20261021.json>) then completed without resource failure, but useful grouping and exact grouping plus expected status were 0/4. Two fenced responses fell back exactly; two split every sentence. Keep this candidate unselected; resource recovery did not establish useful grouping.

### Frozen paragraph screen collector

The separate [collector](<bonsai_paragraph_screen.py>) is dry-run by default. It validates the fixed private round-9 manifest and three runtime-module hashes without inference, a token or a result file:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/bonsai-normalizer/bonsai_paragraph_screen.py \
  --inputs "$FROZEN_INPUTS" --output "$NEW_PRIVATE_RECEIPT"
```

Execution requires `--execute --admission "$FRESH_ADMISSION" --admission-sha256 "$ADMISSION_SHA256"` and the existing Mac bearer token on stdin, not a command-line argument. The coordinator must produce and hash the admission receipt through the management path; the collector checks its age (at most 60 seconds), pinned source/service identity, unloaded health, free-lock attestation and at least 5.5 GiB available memory. The CLI and callable both reject a different manifest hash. This is not a headroom polling tool or permission to lower admission bounds.

The collector exclusively creates a private receipt, fsyncs intent before each submission and records bounded exact response bytes/status before parsing. It never retries or repairs outputs. Received HTTP rejection or invalid complete response stops with a known outcome and attempts unload/health settlement; transport/body-read failure remains unknown and forbids further calls or unload. Receipt-save errors do not skip known-outcome settlement or replace the primary failure. JSON nonfinite constants and exponent overflow are rejected before storing parsed data. This does not guarantee recovery from process or filesystem crashes.

The 600-second screen budget is checked before submission and after each response, including the last. Remaining time bounds socket-operation timeouts, not trickling responses or remote cancellation. Selection rejections remain in the four-case denominator. HTTP unload/health and local Deck preservation checks do not verify the final Mac vision lock; the coordinator must check that independently. Existing receipts block same-path replay; a new path is not authorization to repeat a consumed case. The round-16 screen has now consumed all four frozen cases once; its [receipt](<paragraph-screen-20261021.json>) records 0/4 useful grouping. Do not reuse those inputs or change the result path to replay them. The collector remains dry-run by default, and its pinned baseline-source admission would need a separately specified new experiment before any future execution.

### Single-target discriminator (round 35)

The factory-unselected [target editor](<bonsai_target_editor.py>) exposes full source plus one exact eligible before/text/after slice as local id0. The existing native deletion schema permits only [] or [0], and the unchanged strict parser runs before remapping to the authoritative original span. It is a diagnostic, not a deployable neutral/structured editor: multiple spans would require multiple serial requests, and no paragraph formatting is provided. The separate [target collector](<bonsai_target_screen.py>) accepts only its new hash-frozen private manifest and reuses durable once-only capture/unknown handling/settlement; it is dry-run unless explicitly executed under the [round35 protocol](<spec.md#single-target-contextual-deletion-discriminator-round-35>).

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/bonsai-normalizer/bonsai_target_screen.py \
  --inputs "$ROUND35_INPUTS" --output "$NEW_PRIVATE_RECEIPT"
```

The four decisions on two texts have now been consumed once. The [round 35 receipt](<target-screen-20261022.json>) records 1/4 useful decisions: literal retention 1/2 and emotional deletion 0/2. All four raw selections/schema acknowledgements and exact-copy plans were valid; the last literal property was nevertheless deleted and delivered as applied. Reject activation. Do not replay these fixtures under a new receipt path or repair/tune their outputs. A single exposed target did not establish useful selection; no general causal or speed ranking follows. The shared collector admits an optional schema/assessor/prompt; default paragraph payloads/scoring remain covered by their original model-free tests. Its round 31 wrapper pins the updated helper without changing frozen inputs or historical executed source. Production factory/gateway/STT and services remain unchanged. Known outcomes were unloaded and separately verified by final Mac lock/hash/unloaded observation; private raw inputs/results remain outside Git.

The isolated contrastive-instruction candidate explicitly distinguishes removable emotional evaluation from quoted or negated wording, factual failure severity, urgency and necessary conditions. Its four-call live screen did not pass: only 1/3 emotion-bearing cases produced the expected useful edit; two content-losing raw candidates fell back to the exact accepted text, and the protected-use control passed. Do not deploy this candidate. Lexical guards and exact accepted-text fallback are unchanged. See the [task record](<spec.md#contrastive-instruction-iteration>) and [result receipt](<contrastive-screen-20261021.json>); the older first screen above is historical context, not the latest acceptance result.

The ordered-word check now rejects `Не удаляй базу, перезапусти сервер.` rewritten as `Удаляй базу, не перезапусти сервер.`, despite equal negation counts. Candidate words must occur in source order and cannot reuse a source occurrence; deletions, case changes and punctuation/line-break formatting are still allowed. This also rejects valid synonyms and reordered but equivalent phrases, returning the accepted source unchanged.

This is not semantic equivalence: `Перезапусти сервер только если копия готова.` rewritten as `Перезапусти сервер если копия готова.` still passes after weakening the condition. Deleting facts, clauses, names, units or urgency, changing punctuation, or choosing ambiguous repeated words can still alter meaning. Passing local tests is not deployment approval or semantic validation. Mac inference availability has now been checked, but the lead must still establish useful semantic output before installing the exact checkpoint gateway/module/config via the existing tunnel and verifying the real consumer. Do not activate solely because these protocol tests pass, or change accepted Parakeet/dictionary/Loqira/raw configuration to compensate.
