# Activate tested GigaAM Multilingual Large CTC on Steam Deck

## Outcome and authorization

Install and try the exact GigaAM model from the completed paired trial on the normal speech endpoint. The user authorized installation, one gateway restart and stopping/disabling Parakeet after successful staged checks. That activation authorization has been consumed; this completion pass makes only documentation and source-backup changes, plus read-only service checks. No further production restart or rollback is authorized here.

## Scope and invariants

- Model: `ai-sage/GigaAM-Multilingual`, Large CTC, revision `3905cd51c3ed4e88c8edf33f3302969ba480a327`; not legacy GigaAM v3, SAGE or Ultra.
- Isolated Deck Python 3.13 environment, PyTorch/Torchaudio 2.10.0+cpu, float32, two CPU threads. Official inspected classes, offline local weights and `weights_only=True`.
- Weight SHA-256: `c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1`. Official source SHA-256: `6d02e640fbb5738ab11c030520a68654ef32f4ff363723db10534cf8b5d5c0e7`; config SHA-256: `5ea1089c77b60e094352d7fb7bfb6580906b380c4dc7053edb4f7f0a1f59c172`.
- Decoder binds to loopback port 10002; gateway backend `gigaam_multilingual` keeps the existing external transcription route. Exact upstream weight identity checked in readiness and transcription responses; no silent fallback.
- Preserve raw audio, raw/pre-rule/final text, failures and actual model/runtime provenance in the private rolling corpus. Preserve dictionary opt-out, explicit GitHub/Omarchy/plugin/ChatGPT rules and default-off cleanup.
- Retain Parakeet runtime, weights, unit and old gateway/drop-in for an authorized rollback. Do not modify DSH, TTS, credentials/providers, feedback history or unrelated VMs. Do not start retained Spark/LightOnOCR services.
- Decoder unit: MemoryMax 6 GiB, CPUQuota 200%. Submitted WAV limit 10 MiB; gateway upstream timeout 120 seconds. Continuous nonoverlapping chunks at most 25 seconds use quiet-window cuts, not neural VAD. Greedy CTC does not add punctuation.

## Acceptance and evidence

1. Staged decoder speech/silence and bounded long-input checks succeed before activation, without changing the old production path prematurely.
2. Existing Tailnet endpoint serves the new backend; default dictionary and opt-out behave as before. Invalid audio has explicit failure status and model provenance.
3. Enabled/active unit state, source hashes and preserved rollback files are inspected. Startup configuration is not a reboot test.
4. Decoder protocol, gateway/archive, telemetry and spelling tests pass on the changed sources. Preserve private raw evidence locally; never copy audio, natural transcripts, sample identifiers, weights or secrets into Git.
5. Reconcile owning README descriptions and commit/push the source-only snapshot to the existing dedicated task branch.

Observed activation results and limitations are in [the deployment report](<../README.md>). The final completion pass will recheck unit/readiness/source identity, rerun scoped tests, inspect the exact staged file allowlist and record the pushed commit. It will not send new speech or restart services.

## Unknowns and limits

CPU latency is higher than former Vulkan Parakeet. Ordinary-use preference and accuracy remain unverified. Continuous sample coverage does not prove preservation of words at chunk boundaries. No sustained load/concurrency, thermal soak or reboot test. Python socket guarding/offline settings do not prove native network isolation; HTTP thread-flood resistance is unproven. No permitted explicit independent reviewer route is available in this session; in-session review is not independent acceptance. VM300 was unreachable and recovery is out of scope.

## Completion status

Activation completed. Completion checks confirmed enabled/active GigaAM and gateway with unchanged PIDs and zero restarts, disabled/inactive Parakeet, matching deployed decoder/gateway hashes and both local and Tailnet readiness. All 46 ModelForge tests passed. Rollback snapshots are present. Owning README descriptions were reconciled. This source-only backup excludes private recordings, natural transcripts and identifiers; portable test import paths and one removed trailing space in the corpus snapshot differ from ModelForge; deployed decoder and gateway bytes are identical. Commit/push is the final delivery gate.
