# Read-only speech Unicode and tokenizer diagnostic

Audits retained raw/pre-rule/final STT stages and recent TTS input text without inference, edits or uploads. Flagged audio header/hash checks prove byte integrity only, not semantic correctness. Logs/reports may contain private transcripts: retain outside source Git.

```sh
python3 -m unittest discover -s tools/speech-unicode-audit/tests -v
```

Observed private run: 438 recent48hSTT (87previous,351Ultra),threeUltra literalunknownmarkers(onewithinword),threeforeign-scriptcases (č/á/Ukrainianі),no Unicode replacement corruption. Six flagged WAV hashes/headervalid. ActualactiveGGUF8193tokens:unknownID0,type2,zeroё/Ёentries,zero bytefallback. Official tokenizer reproduces ё/ёж/ещё as unknown sequences,еще normal. This supports tokenizer alphabet limitation but does not prove every unknown audio token corresponds to ё. Decoder filters CONTROL tags,UNKNOWN type isn't CONTROL,so literal marker leaks into text.

No global unknown->ё replacement/deletion,model/tokenizer surgery or productionrestart performed. No extra ASR/audio listening; full private evidence in ModelForge docs/recent-speech-unicode-audit.md. IncidentINC1390open-diagnosed,notfixed. Three tests verify normalёnotflagged/read-onlystage/hash and boundedGGUFfixtureparsing. No independentmodel-familyreview. No private corpus/sampleIDs/modelweights/tokenizerencodedtables committed.
