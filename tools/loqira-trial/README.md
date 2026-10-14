# Loqira dictation corrector

## Live user trial

The user requested hands-on activation after the initial screen. [Live task record](<../../docs/specs/loqira-live-corrector.md>) describes deployment and consumer verification. [Corrector](<corrector.py>) sends raw pilot ASR through the author's prompt and accepts lexical edits. It is a two-model cascade, not merged weights. The existing public speech URL and JSON `text` response stay unchanged.

Install [loqira-corrector.service](<loqira-corrector.service>) from the pinned deployment checkout into the user systemd directory, then `systemctl --user daemon-reload` and `systemctl --user enable --now loqira-corrector.service`. The model is checksum-verified before launch; listen address is127.0.0.1:10004. Install `corrector.py` as `/home/deck/homelab/gateway/loqira_corrector.py`, the updated pilot gateway as `gateway/server.py`, and [zz-loqira-corrector.conf](<zz-loqira-corrector.conf>) into the gateway drop-in directory. Reload systemd and restart only `voice-gateway.service` after Loqira is ready.

`STT_CORRECTOR=loqira` selects the corrector for normal and smart pilot requests. `mode=raw` or `format=false` without `smart=true` bypasses it. The existing dictionary/cleanup options remain independent. Each chunk gets a fresh single-turn prompt. Prompts above640native tokens split at whitespace, generation is bounded to1024tokens in2048context. Failed/incomplete chunks use conservative SAGE and carry `fallback_sage`, reason and provenance. Successful Loqira responses are not passed through SAGE's lexical rejection filter. A fluent output can still alter meaning; the initial screen observed this.

`/readyz` exposes corrector identity/status. Transcription headers expose `X-Corrector-Model`, `X-Corrector-Model-SHA256`, `X-Corrector-Policy`, `X-Corrector-Status` and `X-Corrector-Latency-Ms`. Corpus records retain source, candidate, output, offsets, usage and fallback separately from raw ASR. No automatic trial expiry.

To return to SAGE without changing ASR: verify the exact installed `/home/deck/.config/systemd/user/voice-gateway.service.d/zz-loqira-corrector.conf`, remove that drop-in, reload systemd, restart the gateway, confirm `formatting_policy=punctuation-case-only-v1`, then disable/stop `loqira-corrector.service`. Existing SAGE source and weights remain installed.

## Historical bounded screen

[Screen contract](<../../docs/specs/loqira-corrector-trial.md>) fixes the initial model, prompt, runtime, private paired inputs and limitations. The screen runner owns10004; do not run it against the active live corrector on that port.

[Runner](<run.py>) starts a separate loopback llama-server, verifies the author's exact rendered single-turn template, records every request before sending, and preserves response/usage/resource evidence. It stops its own child server in `finally`; it never stops shared speech or Clef services. Every output directory must be new. Do not repeat a request after an unknown result; inspect its saved receipt first.

```sh
python3 tools/loqira-trial/run.py \
  --engine /home/deck/homelab/clef-flash-pilot/runtime/llama-b11429/llama-server \
  --model /home/deck/homelab/loqira-trial-20261014/Qwen3.5-0.8B-GEC-KAZ-RUS-ENG.Q4_0.gguf \
  --cases /home/deck/homelab/loqira-trial-20261014/cases.jsonl \
  --output /home/deck/homelab/loqira-trial-20261014/run-01
```

Summarize existing receipts without repeating inference:

```sh
python3 tools/loqira-trial/summarize.py /path/to/run-01 /path/to/new-comparison.json
```

On2026-10-14 the pinned model completed35/35 requests on Deck. Postprocessing median0.916s (34 nonsmoke cases), range0.695–1.710s. The small paired sample improved mixed/English aggregate source edit counts, slightly worsened Russian counts, and did not restore any of24reference Latin tokens in12mixed snippets. Difficult corruptions and occasional wrong word replacements remained. It was not promoted to production; see task record for detailed results and limits.

Input is JSONL with unique `id`, `input`, `kind`, `language`, optional `reference` and `preserve` literals. Cases and outputs can contain private speech and must remain outside Git. Reference edit counts use one punctuation-insensitive Unicode tokenizer with ё normalized to е; these are not human-gold WER. Literal retention is only a diagnostic; human review must assess additions, lost negations, meaning and rare names. This runner is a short selection screen, not a soak or deployment.
