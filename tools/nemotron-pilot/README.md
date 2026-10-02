# Isolated Nemotron 3.5 ASR pilot

Source-only private homelab experiment, not a production backend or automatic migration. Fixed eight human clips (62.79 seconds) plus a one-second silence control; plain decoding and boost 2 with six phrases. No complete human reference, so no accuracy/WER claim. CPU device, one-core-equivalent quota, nice 19, MemoryMax 3 GiB, finite 1200-second cap. Cold CLI loads are not comparable to warm Vulkan endpoint latency. Production Parakeet/gateway processes remained unchanged.

```sh
python3 -m unittest discover -s tools/nemotron-pilot/tests -v
```

## Findings

The indexed old artifact at revision `1c8deae` (741,548,352 bytes; SHA-256 `a5c435f294eea8f88ce68dd27b8c3bfea7f777cb2fbba04fcd30eaa555f429ae`) lacked an embedded SentencePiece tokenizer. All nine hinted calls explicitly disabled boosting and matched plain results. Generic documented `boosted-words` flags were unsupported; actual repeatable `speech-context` flags were used. The pre-inference option failure was preserved.

A separate verified official artifact at revision `ea30d66` (742,090,464 bytes; SHA-256 `3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1`) completed 18 calls / nine pairs with no disabled-context warnings. Six human transcripts changed; both silence outputs were empty. Plain cold wall time totaled 88.103 seconds; context totaled 109.356 seconds; peak memory was 941.5 MiB. Hints occasionally introduced an irrelevant term. This does not justify promotion. Three tests cover limits, disabled-context detection and absence of false accuracy claims.

## Consultation and research

Configured ChatGPT Project consultation returned `MODEL_UNVERIFIED`; no answer received. Recovery used the same request ID, without blind resubmission. Independent public model cards identify `coriollon/whisper-large-v3-turbo-russian-codeswitch` and `bond005/whisper-large-v3-ru-podlodka` as possible later candidates. Neither was installed/tested here. Do not attribute this research to the unavailable advisor.

## Boundaries

Script paths are deployment-specific. WAVs, weights, transcript manifests, private paired results and Oracle state stay outside Git. Full report: Model Forge `docs/nemotron-asr-pilot.md`. No production restart, cloud audio call, training or provider change. A later model trial needs a bounded authorized scope; this exploratory sample must not replace production automatically.
