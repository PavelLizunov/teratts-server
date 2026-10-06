# Active speech restored to old Parakeet

User rejected GigaAM and requested the old working model. Active backend is again **Parakeet TDT 0.6B v3 Q8_0 / NeMo-Speech.cpp 0.1.0 / Vulkan**, not Ultra. The [gateway snapshot](<gateway-server.py>) is byte-identical to the pre-GigaAM gateway, SHA-256 `bb69b4defc50709fa2a14d16d90e61f403aedf22df92b1f77bb51c941071478f`. The [drop-in](<parakeet-default.conf>) selects Parakeet, SHA `b52a3f8387e9ec13f50cc466373df281dfa92467c59cb0bc27338a73143f8237`.

Parakeet/gateway enabled and active, PIDs 3132587/3132657, zero restarts after activation. GigaAM stopped/disabled, retained only for history; reactivation requires fresh authorization. DSH, TTS, OCR, dictionary config, corpus/feedback and unrelated services unchanged. Restored gateway has native Parakeet punctuation and previous formatting behavior; retained inactive smart-model readiness is not an availability guarantee.

Actual Tailnet transcription of one 5.589-second retained recording succeeded in default and raw+dictionary=false: 0.551/0.596 seconds wall, 384/366 ms STT. Native punctuation and dictionary applied/request_disabled verified. These are smoke checks, not sustained performance or gold accuracy. No audio, natural transcript, corpus identifiers, weights or credentials in this backup.

Current GigaAM source/unit/drop-in were preserved before rollback under `/home/deck/homelab/gigaam-return-parakeet-20261006`, including hashes; corpus and old Parakeet assets remain intact. Only scoped speech units were restarted. Any future disruptive change needs its own authorization.
