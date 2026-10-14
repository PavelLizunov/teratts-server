# Deploy the trained RU/EN pilot for human use

## Authorization and result

On 2026-10-14 the user explicitly asked to deploy the just-trained model into their normal speech endpoint so they can use it and provide feedback before later training. The user knows the measured pilot is worse on the retained comparison. This request supersedes the prior no-deployment decision. Do not substitute a different GigaAM checkpoint. The subsequent clarification prioritizes strong native Russian GigaAM recognition plus English technical names, not aggregate superiority to Parakeet. Record this for the next training stage; do not silently change today's requested pilot.

## Contract

- Same endpoint `https://steamdeck.tail9fd337.ts.net/v1/audio/transcriptions`, model SHA256 `b1e64f5b0e6349deefc3534358cbe97becac78349ae5ddc3a28c380ac9974a6d` (883211055 bytes).
- CPU inference on Steam Deck; reuse installed CPU Torch2.10 and official GigaAM commit7447938d791c4f3e643386ee22c33777004293a5, no GPU-server relocation or new training now.
- Reuse historical WAV/chunk/loopback HTTP adapter; extend only checkpoint loading. Extend the observed live gateway with an explicit pilot backend, hash-checked ready/transcribe responses and honest model/segment provenance. No silent Parakeet fallback, lexical hints or new dictionary rules. Existing dictionary/cleanup controls and raw-text retention remain. Initial SAGE bypass is superseded by the user's formatting correction below; restore normal punctuation/case editing while retaining raw ASR separately.
- Preserve endpoint, upload API, OCR/TTS, corpus and retained Parakeet weights/unit. Enable a named pilot service and route drop-in; stop Parakeet after live pilot readiness to release memory. Keep explicit reversal instructions; no auto-timeout during user use.
- No natural speech/audio or trained weights in Git; artifacts private. Separate checkpoint branch, preserve active worktree/index. Worker fetches exact committed code SHA.

## Relevant observations and implementation decision

The live Deck gateway currently supports only Parakeet and legacy GigaAMv3; it differs from an older multilingual snapshot. Patch the exact observed current source rather than replacing it with the older one. Current native Parakeet10001/gateway10000;10002 free. Deck available memory3329MiB and home disk39GiB at inspection. Existing GigaAM CPU venv has Python3.13.5/Torch2.10.0+cpu/Torchaudio2.10.0+cpu, Hydra/OmegaConf/SoundFile, but no official gigaam module. Official source is checked out separately via Git.

Verdict: Extend — existing GigaAM WAV/HTTP adapter and live gateway — existing chunking, input handling and corpus integration fit; only local checkpoint loading and explicit pilot routing/provenance are missing.

## Verification

Direct observed acceptance, not a new benchmark campaign: verify transferred SHA and public CPU model load; readiness reports exact trained SHA; one short known WAV and a >25s request exercise decoder and chunk path; actual public endpoint returns pilot header/SHA and retains correct raw/final/model metadata. Observe service state and Deck memory/temperature. Confirm Parakeet is stopped but preserved. Compare deployed source SHA with committed code and remote Git commit. If load fails, keep production Parakeet until resolved. Cold boot, long soak and subjective quality remain unverified.

## User-reported formatting correction, 2026-10-14

The user reported the loss of text editing and punctuation in normal dictation. The agent-selected raw-only pilot route changed ordinary consumer behavior unnecessarily. Restore the existing conservative SAGE95M formatting path for default/smart pilot requests; preserve original ASR words, English spelling, existing dictionary controls, raw opt-out and separate corpus stages. Do not change the trained checkpoint, install an untrained E2E head, introduce transliteration rules or call formatted text a newly trained E2E model. The user also asked whether E2E could be attached: explained that a trained E2E head is not a drop-in compatible editor; postprocessing is reversible without changing weights, while ASR-initialized/E2E training is a later distinct experiment.

Acceptance: observed normal public request is formatted, raw request still bypasses; both use the same pilot SHA and retain raw/formatted/candidate metadata. Public readiness must report the warmed formatter. Deployment fetches a committed change and restarts only the gateway, leaving the decoder/model untouched. No additional benchmark campaign. Formatting quality on arbitrary wrong recognizer text remains unverified.

## Observed initial deployment, 2026-10-14

Completed model transfer SHA verification and actual public endpoint inference. Worker initially fetched exact code commit d8402229ce3552733f94ab3d66bdfdbac365fc36; subsequent commit records dependency correction and evidence without changing model/server/gateway code. Gateway deployed SHA e373f51a1a6b8ae47f93b8c832635efc1f10828e268afb47260db23c140b0e34 matches its committed snapshot.

Direct six-second WAV: 0.779s wall. Thirty-second repeated-input check:2.656s, two continuous nonoverlapping segments [0,23.8],[23.8,30], all samples covered; this checks chunk mechanics, not natural long-form accuracy. Normal public default request:0.768s wall, trained backend/model SHA confirmed in response and private native corpus; raw/final audio association and quantization none verified. SAGE/smart bypass explicit. Natural transcripts and audio retained only in private artifacts.

Pilot and gateway active/enabled, zero observed restarts. Parakeet stopped/disabled with all files retained. A live `Wants` inspection found that empty Wants in a drop-in did not remove the historical Parakeet dependency; moved the exact existing routing file unchanged to `/home/deck/.config/systemd/user/ruen-pilot-disabled-routing/parakeet-default.conf`. Reloading systemd confirmed Wants now contains only the pilot; no gateway restart was needed for this correction. Rollback README reflects the moved routing file.

After releasing Parakeet: available3378MiB; pilot cgroup memory2212253696bytes, gateway351645696bytes. Peak observed temperature after bounded requests62C. Prior overlap while both models loaded had1396MiB available and was ended by stopping Parakeet. These are observations, not soak guarantees. No extra benchmark campaign or nighttime schedule created. User trial stays active until changed explicitly.
