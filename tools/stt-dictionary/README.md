# Explicit personal spelling rules and optional cleanup

Private deployment adapter, not a TTS engine feature or new recognizer. Canonical GitHub whitelist includes user-reviewed гитха/гетха/гетхаб/Гитхаба/git hub in addition to earlier forms. Omarchy retains the original exact standalone forms and now accepts explicitly user-confirmed aliases from the owning JSON; ordinary мерч, Git/GitLab/gitab/hub git and protected code/URLs/paths/emails/identifiers remain untouched. No fuzzy replacement, training, provider changes or second inference.

Gateway applies after formatting, preserves raw/pre-dictionary/pre-cleanup/final and per-stage before/after/offset provenance. `dictionary=false` bypasses spelling; local JSON `github:false`/`omarchy:false` disables each without restart. Malformed/missing config preserves original. Standard JSON/text shapes unchanged, dictionary/cleanup headers available.

Default-off `cleanup=true` removes at most two punctuation-delimited leading Ну,/Смотри, only with at least two words remaining. It preserves Maria, content commands, interior words, short phrases and quoted/code forms. No confidence that model-recognized Maria was really smotri; Maria-to-smotri is review-only. By subsequent explicit user choice, standard Russian plugin inflections (плагин/плагины/плагина/плагинов/плагинами/etc.) now normalize to the single English plugin, intentionally losing number/case. English plugins/Plugin also normalize. Truncated плаги/плагинок, identifiers/code/paths do not. Independent config plugin:false or dictionary=false disables this rule.

Tests:

```sh
python3 -m unittest discover -s tools/stt-dictionary/tests -v
```

Ten rule/cleanup tests, 18 actual-handler/archive, six name-evidence,18 bank/review,nine telemetry regressions passed (61 total). Live same WAV default/off/cleanup: short GitHub aliases normalized, punctuation opening removed only on opt-in, original fields verified. Dictionary smoke 0.25–0.27 ms. Synthetic Omarchy was decoded морчи and left unchanged, гитхабе remains outside whitelist: not all speech errors fixed. One approved gateway restart, Parakeet/LLM/OCR unchanged; no DSH/TTS restart. Five synthetic fixtures removed, no real data deletion.

Plugin v3 acceptance:12 rule tests,2 opening repair,18 gateway/archive,18 bank/review,6 names,5 technical (61 total) passed. Live default produced three plugin substitutions, optout kept inflections, leading Ну remained with cleanup disabled; raw provenance verified, four synthetic samples removed. Rule smoke0.28ms. One explicitly approved gateway restart, model PIDs unchanged. Opening history repair documented in vocabulary-bank tooling.

Version4 adds exact ChatGPT spellings (chat gpt/чат GPT/чат джи пи ти/чат джибити etc.) and explicit Pro/про suffix -> ChatGPT Pro, no loss of Pro or invention from Plus. Standalone GPT/джибити and protected URLs/code/IDs untouched. Config chatgpt:false/ dictionary=false optouts. Live default ChatGPT/ChatGPT Pro/plugin versus raw optout verified,3 changes0.44ms; original metadata checked/four synthetic samples removed.14 spelling tests plus handler/review regressions passed. One gateway-only authorized restart, model PIDs unchanged.

Production subsequently rolled back to previous Parakeetv3/NeMo0.1.0Vulkan afteruserqualityregression. Currentdeploysnapshot exactrestoredsource,currentspellingv4rulesuntouched. HistoricalUltraadapter/deploysnapshot retained under tools/ultra-upgrade onlyforreproducibility,notactive. See rollback/README.md;natural-speechqualitynotguaranteedbyearliersmoke.

Version5 repairs the reported phonetic-name coverage gaps with a bounded `aliases` mapping in the existing JSON. Keys are exact literal words/phrases (maximum256 entries,80 characters each), values limited to the five existing canonical names and enabled rule toggles. Longest match first preserves joined Pro forms. No regex injection, fuzzy match or automatic promotion of review feedback. New explicit aliases include чат-джипти/чат-джиптипро/Чар Джи Пяти про and Амарче/Амарчи/Марчи/Амарчик, plus plug in. Ordinary marks/merch/Maria, unrelated GPT, code, Markdown links, URL/path/email/identifier boundaries remain protected.

The review bank historically collected preferences/candidates but did not activate every saved correction as a runtime spelling rule. Version5 does not erase or silently reinterpret those votes. New approved aliases can be added to the live JSON without another restart; this code addition needed one explicitly approved gateway-only restart.

Live acceptance: replayed the three exact retained complaint WAVs. Default produced four ChatGPT corrections including preserved Pro, one ChatGPT Pro from Чар Джи Пяти про, and four Omarchy corrections. `dictionary=false` returned the exact prior uncorrected text. Dictionary overhead0.60–1.82ms, no LLM/second ASR.16 scoped tests plus14 project mirror regressions pass. ParakeetPID3132587 unchanged; gateway alone restartedPID3989971; backups/receipts private. No original corpus or review feedback deleted. See [repair record](repair-spec.md).

Only task source snapshot in deploy/; not a generic CLI installation. Private full report in Model Forge docs/personal-spelling-cleanup.md. No private corpus/DB/keys included. No independent reviewer/long natural-voice soak. Routine non-disruptive work needs no repeated user confirmation; future disruptive restarts still require fresh single-use authorization.
