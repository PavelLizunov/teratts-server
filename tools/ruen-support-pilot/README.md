# Trained GigaAM RU/EN support pilot on Steam Deck

User-requested hands-on deployment of the 2026-10-14 trained checkpoint, **not a quality winner**. This is SSL220M with a newly trained RU/EN CTC head, not the earlier pretrained GigaAM Large trial. Training used monolingual support data; preservation of pretrained Russian ASR quality and natural mixed technical-name accuracy are not established.

The user ended this pilot on2026-10-14 because dictation quality was poor. Its service is stopped/disabled and files retained. [Parakeet with Loqira](<../../docs/specs/parakeet-loqira-live.md>) is the replacement. The gateway source below now supports Loqira for both backends.

## Components

- [Server](<server.py>) subclasses the retained [WAV adapter](<../gigaam-multilingual/gigaam_multilingual_server.py>) and loads the exact local checkpoint through official GigaAM. SHA-256 must be `b1e64f5b0e6349deefc3534358cbe97becac78349ae5ddc3a28c380ac9974a6d`.
- [Gateway snapshot](<gateway-server.py>) extends the observed production Parakeet gateway with backend `ruen_support_pilot`. The existing `/v1/audio/transcriptions` URL and upload contract remain.
- [Service](<ruen-support-pilot.service>) uses the retained Python3.13 / PyTorch2.10 CPU environment, four threads, loopback10002, and the pinned official GigaAM checkout `7447938d791c4f3e643386ee22c33777004293a5`.
- [Routing drop-in](<zz-ruen-support-pilot.conf>) selects the pilot. The previous Parakeet routing file is retained unchanged outside the active drop-in directory; systemd dependency lists cannot be cleared with an empty `Wants=` drop-in. No silent fallback to Parakeet.

`/readyz` and each successful transcription verify the trained checkpoint hash. Responses include `X-STT-Backend`, `X-STT-Model`, `X-STT-Model-SHA256` and `X-STT-Experimental`. Private corpus records retain exact model identity, runtime, chunk intervals, raw output, existing dictionary result and final output. This keeps human feedback attributable to the right weights. Existing dictionary rules and cleanup opt-out remain unchanged; no new lexical rules are added. Normal and smart-mode pilot requests use [Loqira](<../loqira-trial/README.md>) when the installed drop-in sets `STT_CORRECTOR=loqira`. It may change words; source/candidate/output and model identity are retained. If disabled or a correction chunk fails, the retained SAGE95M ONNX [formatter](<../gigaam-multilingual/speech_formatting.py>) supplies conservative punctuation/case restoration. SAGE accepts punctuation/case only and preserves source tokens; this restriction does not apply to successful Loqira output. `mode=raw` or `format=false` (without `smart=true`) bypasses formatting. Smart LLM structuring remains bypassed; existing dictionary opt-out is separate. This restores ordinary dictation formatting without pretending the acoustic model learned punctuation or missing English terms.

## Installation layout

The deployment repository is checked out at `/home/deck/homelab/ruen-support-pilot-20261014/deployment` on a committed SHA. The official GigaAM source is the sibling `GigaAM` checkout; weights are the sibling `model.ckpt`, outside Git. Install the unit into the user's systemd directory, start it, and verify loopback readiness before installing the gateway/drop-in and restarting `voice-gateway.service`. Parakeet is stopped/disabled only after the new decoder and public gateway respond, while its weights/unit remain available.

## Return to Parakeet

No model files need to be downloaded again. After an explicit request to return:

```sh
systemctl --user enable --now parakeet-stt.service
curl --fail http://127.0.0.1:10001/ready
```

Remove only the pilot route drop-in `/home/deck/.config/systemd/user/voice-gateway.service.d/zz-ruen-support-pilot.conf` after verifying that exact path. Restore `/home/deck/.config/systemd/user/ruen-pilot-disabled-routing/parakeet-default.conf` to `/home/deck/.config/systemd/user/voice-gateway.service.d/parakeet-default.conf`; its contents remain unchanged. The extended gateway still supports Parakeet. Reload systemd, restart the gateway, verify the public `/readyz` backend is `parakeet`, then stop/disable `ruen-support-pilot.service`. Preserve corpus and model files.

## Limits

Float32 CPU inference; no quantized/GGUF/Vulkan conversion. Input is PCM16 mono/stereo WAV at8–96kHz, max10MiB, decoder timeout120s. Longer inputs are split into continuous nonoverlapping chunks up to25seconds at a quiet window. This is not streaming and can lose words at boundaries. Raw ASR is lowercase and unpunctuated; normal output has post-ASR punctuation/case restoration, which adds latency and can make punctuation mistakes. SAGE fallback does not repair wrong recognized words. Loqira can repair words but can also substitute or omit them; neither stage guarantees English spelling. Cold boot, sustained load and human preference are not verified by installation. Do not silently expire the user trial.

[Task and observed verification](<../../docs/specs/gigaam-ruen-pilot-production.md>) records deployment status. No private speech, trained weights or corpus records are included in this repository.
