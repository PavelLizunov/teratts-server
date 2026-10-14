# Loqira 0.8B correction trial

## Authorization and decision

User: take Loqira0.8B and test it (2026-10-14). Determine whether the independent text corrector improves the currently deployed trained RU/EN ASR pilot without losing technical terms, negations or content. No production routing change, ASR weight change or training. Keep Deck voice, Clef and unrelated services active. Prior results are contextual only, not a Loqira baseline.

Verdict: Adopt — published GGUF plus installed llama.cpp b11429 d81235049; stdlib Python request runner only. Native model template, exact author system prompt, fresh single-turn requests, temperature0/repeat_penalty1/thinking off. Model repo loqira/Qwen3.5-0.8B-GEC-KAZ-RUS-ENG revision ced469768d40dffc899fe459efb66a4a07aeabee, Q4_0 file563035616bytes SHA893f573db88f587e823b66847e06049cdb3029eff6177d92f6577179f7178871. Author training context2048 takes precedence over generic GGUF context262144. Apache2.0. Model card promises are not measured guarantees.

## Bounded iteration

- One configuration: Deck Vulkan full offload, context2048, one slot, f16 KV, two CPU threads, batch256/ubatch128, no speculation. Separate loopback10004; server owned by runner and terminated in finally. Existing Clef8092 is active (old role document is stale), do not stop it.
- Same intended integration API: /v1/chat/completions, Jinja embedded template, explicit enable_thinking=false, temperature0, repeat_penalty1, max_tokens512, stop im_end. Request returns corrected text, no conversation history. Native apply-template receipt must match author empty-thinking prefix before inference.
- One known-answer smoke, then first12mixed+first6RU+first6EN retained predictions (source references NOT human gold), six hand-written synthetic controls and four user-supplied corrupted-text examples. No cherry-picked model outputs. Preserve raw/source/corrected rows privately; no audio/text from private corpus in Git.
- Compare paired normalized source-word edit counts using one Unicode word tokenizer, per-language totals, Latin-token retention, negation/number/code controls, literal outputs and actual wall latency. Semantic judgments explicitly qualitative. Not a production WER claim, no statistically powered benchmark.
- Agent-selected fast-mode budget: smoke120s, screen600s; no load/soak/other models. Per-request45s. Stop active iteration on timeout, context overflow/truncation, OOM, identity/template drift, temperature>=85C, MemAvailable<1536MiB or swap growth>256MiB; preserve records. These are bounded-run guards, not user-imposed permanent limits. Memoryheadroom chosen against3176MiB observed available.
- Report engine/model hashes, timings, peak resources, raw evidence, supported decision and gaps. Check production readiness before/after. Retain installed weights but leave no temporary inference process after trial.

## Observed result, 2026-10-14

Committed worker source343c39cfe649d219d2a6f8c54f2302a60c242c09, model checksum verified. Cases manifest9cec475f9f3c28e2fece62873887d8687e8a5cca75191b1abf657450b474aef6. All35requests completed with stop finish and no exposed reasoning; exact apply-template string matched author contract. Model Q4_0, context2048, one slot and no speculation confirmed in props. Vulkan build and full-offload command selected; default log does not expose a per-layer device-allocation receipt, so no independently measured GPU-memory claim.

Run wall37.02s; nonsmoke34requests median0.916s/min0.695/max1.710s. Process cgroup peak767.2MiB, process swap0MiB; minimum system available2481.60MiB, system swap growth0MiB, observed temperature peak59C. This is not a sustained thermal/throughput guarantee.

| Paired source group | Cases | Reference words | Raw edits | Corrected edits | Improved/equal/worse |
|---|---:|---:|---:|---:|---:|
| mixed |12|166|109 (65.66%)|93 (56.02%)|9/2/1|
| Russian |6|27|6 (22.22%)|7 (25.93%)|0/5/1|
| English |6|189|29 (15.34%)|25 (13.23%)|3/3/0|

These use one new Unicode tokenizer and source references, not adjudicated WER and not directly comparable to earlier pipeline metrics. Mixed reference Latin tokens24:raw0/corrected0. Correct existing technical names, URL, numbers, command text and negations survived the corresponding synthetic controls; the exact-case missing-literal diagnostic flagged lowercase kubernetes becoming Kubernetes, which is not a lost name. This does not establish general fidelity. The known-answer smoke was fluent but lost part of the greeting question; API completion is not quality acceptance. Four user-supplied corrupt texts were only partly repaired, including an incorrect verb substitution. No prompt/parameter tuning or additional cells used.

Temporary server terminated successfully, port10004closed; gateway998878, pilot996158 and Clef3211342remained active with unchanged PIDs/zero restarts. Production remains trained pilot+conservative SAGE, not Loqira. Weights and exact-run evidence retained privately on Deck and in task artifacts. All launch/download/collection jobs collected. Decision: installed and tested, not sufficient as a reliable repair layer for severely corrupted mixed speech; no automatic promotion. Next potential task is a user-selected live trial or a separately selected stronger model, not unrequested continued benchmarking.

## Remaining unknowns

Q4_0 correctness and practical performance on Deck Vulkan not yet observed; trained mixed-script limitations acknowledged by author. Reference transcription boundaries may inflate edit ratios. Reference-free user examples need user judgment of intended wording. The fixed lexical-preservation filter used by current SAGE must NOT reject all Loqira word corrections in this isolated trial.
