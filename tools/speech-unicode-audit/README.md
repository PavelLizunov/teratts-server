# Read-only speech Unicode and tokenizer diagnostic

Audits retained raw/pre-rule/final STT stages and recent TTS input text without inference, edits or uploads. Flagged audio header/hash checks prove byte integrity only, not semantic correctness. Logs/reports may contain private transcripts: retain outside source Git.

```sh
python3 -m unittest discover -s tools/speech-unicode-audit/tests -v
```

Observed private run: 438 recent48hSTT (87previous,351Ultra),threeUltra literalunknownmarkers(onewithinword),threeforeign-scriptcases (č/á/Ukrainianі),no Unicode replacement corruption. Six flagged WAV hashes/headervalid. ActualactiveGGUF8193tokens:unknownID0,type2,zeroё/Ёentries,zero bytefallback. Official tokenizer reproduces ё/ёж/ещё as unknown sequences,еще normal. This supports tokenizer alphabet limitation but does not prove every unknown audio token corresponds to ё. Decoder filters CONTROL tags,UNKNOWN type isn't CONTROL,so literal marker leaks into text.

Subsequent user-authorized recheck completed five exact WAVs (three unknowns,two lettercontrols;32.595s) with two independent local no-hint CPU decoders (Nemotron3.5 and preserved oldParakeetv3). Ten successful calls,82.821swall,909.3MiBpeak,temporarytaskended. One unknown position had basev3ее vs Nemotronон hypothesis,othersomittedunknownwithpauses/punctuation;lettercontrolsйо/Йж/Яunstable. Does not establish every marker asё or provide humangold. Six source tests passed including recheckIDs/path/hash/no-productioncalls. Private per-case sourceaudio/resultreport in ModelForge docs/unknown-token-audio-recheck.md;rawaudio/transcripts notGit.

No global unknown->ё replacement/deletion,model/tokenizer surgery or productionrestart performed. No extra ASR/audio listening; full private evidence in ModelForge docs/recent-speech-unicode-audit.md. IncidentINC1390open-diagnosed,notfixed. Three tests verify normalёnotflagged/read-onlystage/hash and boundedGGUFfixtureparsing. No independentmodel-familyreview. No private corpus/sampleIDs/modelweights/tokenizerencodedtables committed.
