# Runbook: Mac Bonsai 9B Neutral Transcript Normalizer

**Component:** Optional post-STT neutral transcript normalizer on Steam Deck gateway.
**Hardware & Topology:** Steam Deck (`100.110.84.30`) -> Mac mini M4 (`100.116.97.112:8091` or local SSH tunnel `127.0.0.1:18091`).
**Model:** `prism-ml/Ternary-Bonsai-2-9B-mlx-2bit` (`f4e28a59531731c41b6dfac88cf271bd58f0a287`).

**Current status:** the production gateway/module/config are not deployed. The dedicated tunnel is active/enabled. On the owner's request, Mac launchd inference recovered after restart and returned the expected known answer; the previous config-file access wait no longer reproduced, but the OS permission grant itself was not directly observed. An exact temporary normalizer snapshot on Deck made four real requests through the existing tunnel: all four retained manually inspected facts/negations/conditions/order, but only one of three emotion-bearing cases removed the target emotion. Cold client latency was8.674s; warm1.466–3.792s. This is not the actual voice HTTP consumer or general semantic acceptance. Gateway SHA remained unchanged and no config/token/drop-in was installed. Keep rewriting disabled until useful behavior is established. The commands below describe deployment steps not yet executed; lexical guards do not establish preservation of meaning.

---

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

The experimental instruction now explicitly distinguishes removable emotional evaluation from quoted or negated wording, factual failure severity, urgency and necessary conditions. This is a prompt-only hypothesis; the lexical guards and exact accepted-text fallback are unchanged. See the [task record](<spec.md#contrastive-instruction-iteration>) for its finite live screen and measured result before treating it as useful.

The ordered-word check now rejects `Не удаляй базу, перезапусти сервер.` rewritten as `Удаляй базу, не перезапусти сервер.`, despite equal negation counts. Candidate words must occur in source order and cannot reuse a source occurrence; deletions, case changes and punctuation/line-break formatting are still allowed. This also rejects valid synonyms and reordered but equivalent phrases, returning the accepted source unchanged.

This is not semantic equivalence: `Перезапусти сервер только если копия готова.` rewritten as `Перезапусти сервер если копия готова.` still passes after weakening the condition. Deleting facts, clauses, names, units or urgency, changing punctuation, or choosing ambiguous repeated words can still alter meaning. Passing local tests is not deployment approval or semantic validation. Mac inference availability has now been checked, but the lead must still establish useful semantic output before installing the exact checkpoint gateway/module/config via the existing tunnel and verifying the real consumer. Do not activate solely because these protocol tests pass, or change accepted Parakeet/dictionary/Loqira/raw configuration to compensate.
