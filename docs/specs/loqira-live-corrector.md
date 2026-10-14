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

## Activated and observed, 2026-10-14

Implementation commit `5aadab99786de4c0bbe3608ce452cd2545a222ff` pushed and exact remote SHA verified before Deck fetched it. Installed gateway SHA256 `617ea049a4909d6563f5531c1c0cacde75a1c07fe6700ebf458e709f4ce7561b`; correction module `c6bfc5ddc7ba0d9f9fd4905cb7436eae762e9d4610d84b5a0d80103103e3f2a5`. Loqira service active/enabled PID1010886, gateway active/enabled PID1011247, ASR active/enabled PID996158 unchanged; zero automatic restarts. No trial expiration scheduled.

Five focused checks passed: lexical changes accepted, transport failure falls back, incomplete candidate retained but not emitted, segmentation covers original offsets, unsplittable token falls back. Python compilation and task diff whitespace checks passed. Actual native `/apply-template` and `/tokenize` transport confirmed on the permanent service before routing activation.

Public audio observation used the retained6-second WAV, with dictionary/cleanup disabled to attribute changes. `/readyz` identifies the unchanged trained ASR hash and pinned Loqira hash with status ready. Default response status applied: wall1.850s, ASR600.25ms, Loqira1123.99ms, SAGE0ms. Raw response wall0.646s, same ASR text, both corrector timings0. Actual private archive inspection verified audio hash, model hashes, raw/candidate/final text, completion finish=stop and status. The observed output matches the earlier quality screen including its known imperfect word edits; this is deployment verification, not a new quality claim.

Evidence retained privately under `loqira-live/public-observation/`: request-start receipts, HTTP responses, native corpus metadata and summary. All download/deploy/request jobs collected, live services intentionally remain running. Full corrected-text quality, long natural dictation and cold-boot behavior remain unverified. User feedback is next; no additional benchmark or training scheduled.

### Delivery Gate Verification (Prose)

- PASS: activation claims and timings come from actual service/HTTP/corpus receipts.
- PASS: documentation describes configuration, fallback mechanism and rollback directly.
- PASS: current activation is distinguished from the historical screen and from weight merging.
