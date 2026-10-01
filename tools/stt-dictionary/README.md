# Explicit GitHub spelling rule

Private deployment adapter, not a new TTS engine feature. Only the user-approved GitHub term: standalone Гитхап, Гитхаб, Гит Хаб and case variants of github → GitHub. No fuzzy matching, other-term promotion, training or second inference. Codes/URLs/paths/emails/identifiers protected by conservative text regex. Declensions and гетхаб intentionally not whitelisted.

Current gateway applies after formatting; raw_text preserved, pre_dictionary_text/final_text/correction offsets/config hash retained locally. `dictionary=false` bypasses on a request even for raw-mode. Local JSON `github:false` disables without restart; bad/missing config returns original. Standard JSON/text response shapes unchanged; dictionary headers exposed.

Tests:

```sh
python3 -m unittest discover -s tools/stt-dictionary/tests -v
```

Six rule tests passed; Model Forge actual-handler/archive suite 17 passed and telemetry suite 9 passed. Live default/optout same synthetic WAV: two гитхаб substitutions, helper 0.32 ms; original/pre-rule/final metadata verified, only synthetic test samples removed. First word гетхаб remained unchanged; no false claim of full GitHub recognition. One gateway-only restart explicitly authorized/performed; model/DSH/TTS unchanged. No independent reviewer, full code parser or long real-voice soak.

Source snapshot in deploy/ is specific to current homelab gateway and assumes existing dependencies/services; do not install as generic CLI. Full private rollout details in Model Forge docs/github-stt-rule.md. DB, private corpus, transcripts and credentials never included in this source backup.
