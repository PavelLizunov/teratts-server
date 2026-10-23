# Experimental FrogNano STT editor

This optional server-side stage edits accepted Russian dictation after Parakeet,
the approved dictionary, Loqira, the final dictionary and optional opening cleanup.
It uses the existing transcription API; it does not require a client hook or access
to the owner's computer. Only effective smart mode selects it. Default and raw
routing, including the existing `smart=true` precedence, remain unchanged.

## Status and limits

The owner authorized a separate experimental trial of
`capyctl/FrogNano-4B-2609-MLX-4bit` at
`7175ee2b94eae649dfd1e7605cd2dc3dcd1e3e2f`. In the earlier four-request native screen,
the smoke request completed; meaning was retained on three task texts, but full
emotional cleanup succeeded on only one of two emotional texts. The neutral
control was unchanged. This is partial usefulness, not reliable editing.

The R73 server trial is installed. Two new once-only synthetic requests through
installed gateway source and real FrogNano HTTP completed at EOS. The emotional
candidate retained an emotional descriptor and introduced a misspelling, so the
word-order guard rejected it and the gateway returned exact accepted text (6.782 s
optional-stage time). The neutral quoted control was returned exactly unchanged
(4.129 s). Thus new full cleanup was 0/1 emotional inputs and neutral abstention
1/1; a useful new emotional edit was not demonstrated. See the sanitized
[verification receipt](<r73-verification.json>). The trial remains explicitly
smart-only, not an automatic replacement for ordinary dictation.

The R74 exhaustive-removal prompt was rejected and the exact R73 client/service
restored. It removed outside-quote profanity in both fresh texts, but changed a
protected quote and deleted a substantive instruction in one text; the lexical
guards accepted that unsafe deletion. Complete useful edits were therefore 1/2,
not 2/2. The [R74 receipt](<r74-verification.json>) records the failed attempt and
verified rollback. The original missed-profanity defect remains unresolved; do not
activate the rejected prompt from its retained candidate commit.

The [client](<../bonsai-normalizer/frognano_normalizer.py>) reuses the unchanged
historical transport and lexical guards. It rejects protocol markers, incomplete
responses, identity drift and selected lexical changes. Successful content is not
trimmed or repaired. Deletions and punctuation can still change meaning despite
passing these checks. Paragraphs are optional and not established as useful.
Every error, rejection or non-applied result returns the exact accepted
post-cleanup text, never raw ASR. Owner-field insertion and actual Voxtype routing
have not been verified by these server checks.

## Mac service

[Service source](<frognano_service.py>) uses the existing interpreter and MLX overlay,
not a new dependency installation. It binds explicitly to the approved Mac Tailnet
IPv4 address on port 8093 and requires a bearer token for health and inference.
Requests are serial, with a fixed prompt, greedy seed 42, fresh KV state, prefill
512, at most 3072 prompt tokens and 512 output tokens. Only a normal known EOS
succeeds. Health and model metadata do not load weights.

Each request verifies the externally pinned setup/runtime manifests and all their
listed files before native imports, then loads under the shared vision lock.
Admission requires at least 6.5 GiB available; sampled reserve is 2 GiB and maximum
new swap is 0.25 GiB. Cleanup closes generation, drops native references, collects
objects and clears the MLX cache before releasing the lock. The cooperative
20-second deadline includes hashing, loading, generation and cleanup. Native calls
cannot be interrupted mid-call; this is not hard cancellation or transient-peak
protection. The gateway uses a socket-operation timeout capped at 20 seconds and
never retries an uncertain inference.

The setup manifest pin is
`56617103d9262356d1e59c7afc57fa555acf284350d08d068313d06203996547`.
The mandatory runtime-manifest pin is
`fe00323f4b127d36f882d71860e1f0b157e4008516b1f04c91f9695a1101273a`.
It covers selected retained MLX-LM source files, not complete dependency equality.
No model-repository Python is executed; tokenizer loading is local-only and remote
code is disabled.

Example launch with the retained host layout:

```sh
/Users/slovn/.localforge/minicpm-v47-mlx/venv/bin/python -B frognano_service.py \
  --host 100.116.97.112 --port 8093 \
  --model-path /Volumes/ssd_512gb/LocalForge/frognano-2609-4bit-trial \
  --setup-manifest /Users/slovn/.localforge/alternative-round70/setup.json \
  --runtime-manifest /Users/slovn/.localforge/alternative-round70/runtime-manifest.json \
  --runtime-manifest-sha256 fe00323f4b127d36f882d71860e1f0b157e4008516b1f04c91f9695a1101273a \
  --packages /Users/slovn/.localforge/alternative-round36/packages \
  --token-file /Users/slovn/.localforge/bonsai9/token --deadline-seconds 20
```

## Gateway configuration

Install both the historical base client and the separate FrogNano client in the
`gateway` package. Set only the new optional selector in a dedicated gateway
systemd drop-in:

```ini
[Service]
Environment=FROGNANO_NORMALIZER_CONFIG=/home/deck/homelab/config/frognano-normalizer.json
```

Example JSON (the token file must match the authenticated Mac service):

```json
{
  "enabled": true,
  "endpoint_url": "http://100.116.97.112:8093",
  "token_file": "/home/deck/homelab/config/frognano.token",
  "model": "capyctl/FrogNano-4B-2609-MLX-4bit",
  "revision": "7175ee2b94eae649dfd1e7605cd2dc3dcd1e3e2f",
  "timeout_seconds": 20,
  "max_timeout_seconds": 20,
  "max_input_chars": 6000,
  "max_tokens": 512
}
```

Configuration is read at gateway startup. The new selector takes precedence over
historical Bonsai configuration, including invalid/disabled FrogNano config; it
never applies both editors. The rejected Bonsai deployment recipe is not a
FrogNano recipe. Keep token files private (0600); do not publish their contents.

Use the same `POST /v1/audio/transcriptions?mode=smart` multipart contract and
`response_format=json` or `text`. No new mode or automatic default switch is added.
`X-Text-Editor-Status`, `X-Text-Editor-Model`, `X-Text-Editor-Revision` and
`X-Text-Editor-Experimental` identify this stage. Legacy `X-Bonsai-*` headers and
corpus keys remain for compatibility; the model value is the actual FrogNano ID.
The gateway readiness field `bonsai=configured` means local configuration only,
not native readiness or a model load.

## Checks and rollback

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/frognano-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -O -m unittest discover -s tools/frognano-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/bonsai-normalizer/tests
```

These are model-free checks; full ASGI tests require the existing Deck web
packages and explicit opt-in. Native acceptance uses fresh frozen synthetic texts,
installed gateway source and real FrogNano HTTP with deterministic ASR/Loqira
stubs. That verifies the server seam, not actual acoustic recognition or the
owner's active field.

For integration rollback, disable only the dedicated FrogNano drop-in, reload
user systemd and restart only `voice-gateway.service`. Verify Parakeet/Loqira
readiness and ordinary/default/raw bypass. If source restoration is needed,
restore the exact pre-install gateway copy recorded by the deployment receipt.
Stop only the new `com.localforge.frognano-stt-r73` LaunchAgent; retain its source,
configuration, models and evidence. Do not touch Parakeet, Loqira, Clef, TTS,
Kodak or the existing Bonsai tunnel. A client timeout alone is not evidence that
the remote model has unloaded; observe service settlement before another native
request.

### Documentation verification

- PASS — Claims use recorded source limits, deployed hashes and separate emotional/control denominators.
- PASS — Configuration and failure mechanisms are described directly.
- PASS — Server checks are separated from owner-client acceptance; no owner-field success is claimed.
