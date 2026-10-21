# Runbook: Mac Bonsai 9B Neutral Transcript Normalizer

**Component:** Optional post-STT neutral transcript normalizer on Steam Deck gateway.
**Hardware & Topology:** Steam Deck (`100.110.84.30`) -> Mac mini M4 (`100.116.97.112:8091` or local SSH tunnel `127.0.0.1:18091`).
**Model:** `prism-ml/Ternary-Bonsai-2-9B-mlx-2bit` (`f4e28a59531731c41b6dfac88cf271bd58f0a287`).

**Current status:** the gateway/module/config are not deployed. The dedicated tunnel is active/enabled; the lead verified authenticated Mac health through it with `loaded=false`, which is not inference. The installed Mac launchd service cannot complete its model-config open on the external SSD; TCC logs deny its Python full-access preflight, and the owner has been asked for the OS permission. Kodak routing was restored to its previous setting. The commands below describe deployment steps not yet executed. Keep the integration opt-in. Prior semantic rewrite failures remain relevant: lexical guards do not establish preservation of facts, names, units, urgency, order, uncertainty or negation/condition scope.

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
| `fallback` | `validation_numeric_missing` | Model omitted a numeric occurrence or changed its sign. |
| `fallback` | `validation_numeric_added` | Model added or duplicated a numeric occurrence. |
| `fallback` | `validation_latin_missing` / `validation_latin_added` | Latin identifier counts changed, including unexpected tags such as "Notes:". |
| `fallback` | `validation_negation_lost` / `validation_negation_added` | Negation count changed. Equal counts can still hide a scope reversal. |
| `fallback` | `validation_qualifier_lost` | One of the selected uncertainty/condition/order markers was omitted. |

## 6. Local regression checks and semantic limits

Run from the repository root without models or network:

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 -m unittest discover -s tools/bonsai-normalizer/tests -v
```

The suite mocks HTTP and executes the actual gateway function AST with hardware dependencies stubbed, using the real dictionary and cleanup functions. It checks stage ordering, default/raw bypass, smart/format precedence, source fallback, headers and private corpus metadata. It does not establish that the installed FastAPI service imports, the tunnel works, the Mac reports the pinned revision, or the model follows the prompt.

The finite guards still accept `Не удаляй базу, перезапусти сервер.` rewritten as `Удаляй базу, не перезапусти сервер.` because the negation count is unchanged. Other facts, names, units, task order, uncertainty and urgency can also change without detection. Passing local tests is not deployment approval or semantic validation. The lead must first settle Mac OS access and establish useful semantic output, then install the exact checkpoint gateway/module/config via the existing tunnel and verify the real consumer. Do not activate solely because these protocol tests pass, or change accepted Parakeet/dictionary/Loqira/raw configuration to compensate.
