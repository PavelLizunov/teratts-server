# Offline speech teacher pilot

Finite, manual offline experiment, not a background service or production STT replacement. Copies of task-owned tools are backed up here because the Model Forge workspace has no Git repository. Do not store WAV, transcript results, manifest IDs, credentials or private journals in this repository.

```sh
python3 -m unittest discover -s tools/voice-teacher-pilot/tests -v
```

Selection: max 20 unique submitted human-STT WAVs, 2–30 seconds each, 300 seconds total; filters obvious silence/synthetic/TTS/corrupt samples. Runner makes audio-only native Gemini calls, withholds the primary transcript, saves private output/provenance and a durable dispatch marker, and stops after uncertain failure without blind retry. Existing PyYAML is used only for authorized local credential access; no installation occurs.

Host/gateway/corpus paths in the pilot runner are deployment-specific to this private homelab; this is not a generic supported TTS API feature. No credential/model/provider change or gateway restart is made.

First executed pilot: 20 completed, 162.291 seconds, 6,969 reported tokens; 3 normalized agreements / 10 small disagreements / 7 substantial disagreements. These are token-diff categories, NOT accuracy or WER. Gateway is an existing Antigravity subscription route, no new direct paid API enabled; no invented dollar accounting.

Two known synthetic Russian speech controls were independently transcribed. Silence produced hallucinations, so teacher results are pseudo-label candidates only. No weights/lexicon/training updates and no automatic accepted labels. Human technical-vocabulary confirmation is optional and does not certify each proposed occurrence.

Optional `--vocabulary` accepts a JSON file containing a `terms` list. Confirmed terms are hints, not mandatory substitutions; the prompt explicitly forbids inserting them without audio support. Every hinted result stores vocabulary and prompt hash and never sees primary/blind transcripts. Use a distinct destination directory. `compare_voice_teacher_hints.py` verifies paired sample/hash IDs and reports changes without accuracy claims.

Follow-up on the same 20 recordings: 18 completed, two empty-text results left untouched/no retry, 7,674 reported total tokens. Omarchy/Steam Deck/Bonsai each appeared in one additional hinted output; this is not human confirmation of the utterance. On 18 paired records categories remained 3 agreement / 8 small / 7 substantial disagreements. Fourteen tests passed; automatic correction/training and permanent scheduler remain disabled.

Private result artifacts remain outside this Git worktree in Model Forge. The primary user report is in its `docs/voice-teacher-pilot.md`. Tests cover quantity/duration/duplicate/corrupt/path bounds, exact result parsing and secure no-overwrite persistence. Known limits: no nonzero-noise VAD, no independent human gold, no permanent scheduler, no USD billing bound on subscription quota.
