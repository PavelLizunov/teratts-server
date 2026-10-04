# Restored Parakeet v3 after personal quality regression

Current production is previous Parakeet TDT0.6Bv3Q8 via NeMo-Speech.cpp0.1.0Vulkan, not Ultra. User reported worse Russian/hallucinations and authorized return; exact pre-Ultra gateway restored (SHA bb69b4defc50709fa2a14d16d90e61f403aedf22df92b1f77bb51c941071478f),olddependencydropin restored,olddecoder enabled/started,onegatewayrestart. Spelling helperv4/config untouched,rawcorpus/feedback preserved. LiveHTTP200~330ms/defaultChatGPTPro/plugin and optoutraw,oldmodelrevisionprovenance checked,two synthetic controls removed. LLM/OCR/TTS/DSH not restarted. No automatic repeat activation.

Root cause not isolated: weights,GGUF conversion and runtime all changed during Ultra migration. Successful smoke wasn't natural-speechquality proof. Ultraweights/runtime retained as research-only;never infer oldParakeet-vsNemotronblindvotes validated Ultra.

Fresh source-card research (not installed/tested): technical RU/EN Whisper codeswitch (synthetic53term adaptation,card notespureRUtradeoff),GigaAMMultilingualLargeCTC (ru/en MIT,PyTorchcustomcode,notoldGigaAMv3GGUF),Qwen3-ASR1.7B (Apache2,GGUFCPU/Vulkan,autoregressivelatency/silencerisk,explicitlanguagehintsnotported),PodlodkaWhisperlarge (naturalRussiantechnicaldomain,heavybackend). No universalbestclaim. Next bounded blindnatural-speech trial before production migration.

Private fullreport ModelForge docs/ultra-rollback-asr-research.md;INC1392recorded.14dictionary+20restoredhandler/archive+9telemetrytests passed. SourceonlynotprivateWAV/modelweight/feedback/configsecrets. HistoricalUltraadapter/deploysnapshot remains in tools/ultra-upgrade for reproducibility,notcurrentactivation.
