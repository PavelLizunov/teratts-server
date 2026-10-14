# Deploy the trained RU/EN pilot for human use

## Authorization and result

On 2026-10-14 the user explicitly asked to deploy the just-trained model into their normal speech endpoint so they can use it and provide feedback before later training. The user knows the measured pilot is worse on the retained comparison. This request supersedes the prior no-deployment decision. Do not substitute a different GigaAM checkpoint. The subsequent clarification prioritizes strong native Russian GigaAM recognition plus English technical names, not aggregate superiority to Parakeet. Record this for the next training stage; do not silently change today's requested pilot.

## Contract

- Same endpoint `https://steamdeck.tail9fd337.ts.net/v1/audio/transcriptions`, model SHA256 `b1e64f5b0e6349deefc3534358cbe97becac78349ae5ddc3a28c380ac9974a6d` (883211055 bytes).
- CPU inference on Steam Deck; reuse installed CPU Torch2.10 and official GigaAM commit7447938d791c4f3e643386ee22c33777004293a5, no GPU-server relocation or new training now.
- Reuse historical WAV/chunk/loopback HTTP adapter; extend only checkpoint loading. Extend the observed live gateway with an explicit pilot backend, hash-checked ready/transcribe responses and honest model/segment provenance. No silent Parakeet fallback, lexical hints or new dictionary rules. Existing dictionary/cleanup controls and raw-text retention remain; SAGE/smart rewriting is bypassed for this pilot so its output stays attributable.
- Preserve endpoint, upload API, OCR/TTS, corpus and retained Parakeet weights/unit. Enable a named pilot service and route drop-in; stop Parakeet after live pilot readiness to release memory. Keep explicit reversal instructions; no auto-timeout during user use.
- No natural speech/audio or trained weights in Git; artifacts private. Separate checkpoint branch, preserve active worktree/index. Worker fetches exact committed code SHA.

## Relevant observations and implementation decision

The live Deck gateway currently supports only Parakeet and legacy GigaAMv3; it differs from an older multilingual snapshot. Patch the exact observed current source rather than replacing it with the older one. Current native Parakeet10001/gateway10000;10002 free. Deck available memory3329MiB and home disk39GiB at inspection. Existing GigaAM CPU venv has Python3.13.5/Torch2.10.0+cpu/Torchaudio2.10.0+cpu, Hydra/OmegaConf/SoundFile, but no official gigaam module. Official source is checked out separately via Git.

Verdict: Extend — existing GigaAM WAV/HTTP adapter and live gateway — existing chunking, input handling and corpus integration fit; only local checkpoint loading and explicit pilot routing/provenance are missing.

## Verification

Direct observed acceptance, not a new benchmark campaign: verify transferred SHA and public CPU model load; readiness reports exact trained SHA; one short known WAV and a >25s request exercise decoder and chunk path; actual public endpoint returns pilot header/SHA and retains correct raw/final/model metadata. Observe service state and Deck memory/temperature. Confirm Parakeet is stopped but preserved. Compare deployed source SHA with committed code and remote Git commit. If load fails, keep production Parakeet until resolved. Cold boot, long soak and subjective quality remain unverified.

## Status

Implementation in progress. Old live source and drop-in observed under the private task artifact directory. Model transfer/official-source setup job bash-332 must be collected, not duplicated.
