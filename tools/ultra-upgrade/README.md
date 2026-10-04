# Historical Parakeet Ultra migration: source-only backup

**Current state: rolled back to old Parakeet v3 / NeMo-Speech.cpp0.1.0Vulkan after user-reported quality regression.** Files below preserve the historical experiment, not current configuration. See ../stt-dictionary/rollback/README.md. Active dictionary/corpus preserved;nounverifiednewmigration.

User approved Ultra + updated compatible engine and explicitly one gateway restart/old decoder stop. Actual active runtime is **transcribe.cpp0.2.4 + ParakeetUltraQ8 Vulkan**, not NeMo0.2.0: ready-made UltraGGUF has architectureparakeet and NeMo model-info rejected it. Published converter does not support this specific safetensors source; no custom converter or relabeling. NeMo0.2.0 staged separately,never claimed successful Ultra runtime.

Pinned Ultra artifactNairod785/parakeet-ultra-gguf@b03613ba size739508704 SHA283562ac9b513f39244fe23c6632738c167d32731a5f4693319a10ca498550a8. Parentmoondream/parakeet-ultra@73175eb7 distinctsourceprovenance. Native0.2.4LinuxCPU/VulkantarSHA28b22a523a25b41d59ff91147b6f79f35330663c92c22e483d15d6f4dc0cfc9a;PythonbindingSHAe4bde0002fea09dc2b573f9b18c9d5d1163630b3096392b3dc82eb5dce25be9d. Weights/nativebinaries notGit.

Thin adapter verifies modelSHA/arch/variant,one session/lock,16kPCMresampling,metadataaccurate. Existing OCRvenv unchanged;staged0.2.4Python viaPYTHONPATH+TRANSCRIBE_LIBRARY. Publicgatewayroute/rules/corpus/smart/OCRretained. Oldmodelunit/weights preservedforrollback,oldparakeet-defaultdropin archivedafterverification,oldservice stopped/disabled. GatewayenablednewPID2125614/NRestarts0,TTS/DSH/LLM/OCRnotrestarted. Rebootnotexecuted;configurationpersistentis-enabledchecked.

Tests:

```sh
python3 -m unittest discover -s tools/ultra-upgrade/tests -v
```

45tasktestspassed acrossadapter2/gateway20/telemetry9/rules14;CPU/Vulkanloadtwofixedhumanclips+silenceempty. Live defaultChatGPTPro/plugin and optoutrawverified,statusultra,3changes,317.1ms/257.7msSTTsmoke,archive54.5/57.7ms. CorrectUltraQ8Vulkanmodelmetadata/hash in success/failurecorpus,invalidWAV400,only3syntheticrecordsremoved. No qualitygain/concurrencysoak claims,oldblindvotesnotUltraevidence.

Deploy templates deployment-specific,not genericTTSinstallation. Full operatingreport in private ModelForge docs/parakeet-ultra-upgrade.md with exactrollbacksteps/freshrestartgate. No private rawspeech/feedback/weights/credentials included. Next evaluate naturaluse or bounded blindUltraqualitysample before superiority claims.
