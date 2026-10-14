# Loqira correction screen

A bounded user-requested experiment, not an activated production backend. [Task contract](<../../docs/specs/loqira-corrector-trial.md>) fixes model, prompt, runtime, private paired inputs and limitations.

[Runner](<run.py>) starts a separate loopback llama-server, verifies the author's exact rendered single-turn template, records every request before sending, and preserves response/usage/resource evidence. It stops its own child server in `finally`; it never stops shared speech or Clef services. Every output directory must be new. Do not repeat a request after an unknown result; inspect its saved receipt first.

```sh
python3 tools/loqira-trial/run.py \
  --engine /home/deck/homelab/clef-flash-pilot/runtime/llama-b11429/llama-server \
  --model /home/deck/homelab/loqira-trial-20261014/Qwen3.5-0.8B-GEC-KAZ-RUS-ENG.Q4_0.gguf \
  --cases /home/deck/homelab/loqira-trial-20261014/cases.jsonl \
  --output /home/deck/homelab/loqira-trial-20261014/run-01
```

Input is JSONL with unique `id`, `input`, `kind`, `language`, optional `reference` and `preserve` literals. Cases and outputs can contain private speech and must remain outside Git. Reference edit counts use one punctuation-insensitive Unicode tokenizer with ё normalized to е; these are not human-gold WER. Literal retention is only a diagnostic; human review must assess additions, lost negations, meaning and rare names. This runner is a short selection screen, not a soak or deployment.
