# Live GigaAM + Loqira dictation trial

## User outcome

On2026-10-14, after reading the35-request screen, the user requested leaving Loqira available for hands-on use and later treating ASR+correction as one combined system. Activate Loqira behind the existing speech endpoint now; leave it enabled without an automatic trial expiry. This supersedes the earlier screen-only scope. ASR remains the exact trained GigaAM RU/EN checkpoint; no retraining or weight merging. Existing Clef and unrelated services remain as found.

## Implementation

Adopt installed llama.cpp b11429 and verified Loqira Q4_0. Add a user systemd service on loopback10004, using the measured context2048/single-slot/two-thread/full-offload profile and original author template with thinking off. ExecStartPre checks pinned model SHA; alias includes its hash prefix. Enabled service restarts on failure. No second weights copy.

Extend the existing pilot gateway with STT_CORRECTOR=loqira; default configuration remains SAGE. Default/smart pilot requests send raw ASR through Loqira's exact author prompt, temperature0/repeat_penalty1. Do not apply SAGE lexical-preservation validation to successful Loqira output. The existing raw opt-out bypasses correction. Existing dictionary and cleanup toggles remain separate and unchanged.

Tokenize rendered prompts using the actual model. Split only at whitespace, targeting <=640prompttokens and leaving1024outputtokens in2048context; use sentence boundaries near the midpoint when available. Preserve source offsets and every segment result. HTTP timeout20s, total correction budget60s. Empty, malformed, incomplete or failed responses fall back per-segment to existing conservative SAGE, with explicit reason/provenance. A pathological unsplittable overlong token falls back rather than silently cropping. These are operational request bounds, not a guarantee of semantic fidelity. No request retry after an unknown response.

Retain raw ASR, corrector input/candidate/output, model revision/hash, segmentation, timings and fallback status in existing corpus. Readiness identifies both models and correction policy; expose correction headers without changing JSON text contract. SAGE remains loaded for fallback and rollback. Gateway restart is part of this activation; ASR model service need not restart.

## Verification and delivery

Commit/push exact source before remote deployment. Verify service enabled/active and SHA, then install gateway module/drop-in and restart only gateway. Observe real public audio transcription, compare default and raw on the same WAV/checkpoint, and inspect retained audio/model/correction provenance. Exercise token splitting and error fallback with small focused checks; do not repeat the completed model-quality campaign. Leave live services running for user feedback. Document one-drop-in return to SAGE and retain Loqira weights. A service-start receipt is not evidence of successful voice editing.
