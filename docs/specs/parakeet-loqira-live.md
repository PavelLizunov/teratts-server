# Restore Parakeet and retain Loqira

User request2026-10-14: the trained pilot is too poor; return the previous working setup and put the new corrector on top. Restore retained Parakeet Q8_0 and existing personal dictionary at the same endpoint. Disable trained GigaAM service after route recovery; preserve files. Retain permanent Loqira and apply it to Parakeet default/smart requests. SAGE is a fallback only, not another normal editing pass. Raw bypass remains.

Restore availability first with the existing Parakeet-capable gateway and exact retained routing file, then deploy the small correction extension from a committed/pushed SHA. Existing Loqira drop-in remains; initial gateway version bypasses Loqira for Parakeet until extension is deployed. Existing dictionary config must not be overwritten. Read current config and recent corpus receipts to distinguish dictionary failures from ASR/correction errors. Normalize existing approved aliases before Loqira and keep the existing final dictionary pass; no invented aliases. Store both passes separately, preserve raw ASR provenance.

Observe real public default/raw audio requests, exact active backend/corrector, original/final/dictionary stages and service enabled states. This is restoration and integration verification, not a new model comparison. Leave Parakeet+Loqira active for human trial with no expiry. No training or weight merging.

## Owner acceptance, 2026-10-14

After live use, the owner reported a large subjective improvement, including fast and less distinct dictation, and explicitly requested keeping this result and updating homelab/project documentation. **Parakeet + approved dictionary + Loqira is now the accepted current speech configuration**, not an expiring experiment. The trained GigaAM pilot remains stopped/disabled.

The benefit is attributed to the combined stack: Parakeet restoration, dictionary preprocessing and Loqira were changed together. Parakeet consumes audio; Loqira only edits text and cannot hear speech rate or re-listen to missing words. No paired Parakeet-only/Parakeet+Loqira quality comparison was run. Keep the owner's positive feedback separate from measured fidelity and performance claims.

Documentation-only confirmation at2026-10-14T12:54:28Z found the same gateway/Parakeet/Loqira PIDs active/enabled with zero automatic restarts, pilot inactive/disabled, unchanged source/dictionary hashes and public readiness showing Parakeet plus Loqira ready. No services restarted, inference requests added, weights changed or training scheduled for acceptance recording.

## Restoration evidence, 2026-10-14

Parakeet was started and its native readiness returned `ready=true`, device `vulkan:0`. The exact retained Parakeet routing file was restored; the trained-pilot routing file was moved outside the active drop-in directory. Public readiness confirmed Parakeet before the correction extension was deployed. The pilot service was disabled/stopped, files preserved.

Worker fetched implementation `0623c2b47a54cbd71c448549aea178975f717cf9` after exact GitHub SHA verification. Installed gateway SHA256 `0fee7132c77769bff880607a0f41afe4ab308230ed4c5cd3d229c11ecf05f6c1`. Final observed services: gateway PID1017249 active/enabled, Parakeet PID1015817 active/enabled, Loqira PID1010886 active/enabled; trained pilot inactive/disabled with PID0. Gateway Wants contains Parakeet and Loqira, not the trained pilot.

Personal dictionary config SHA256 `adb26bce32710cd6bc4ecc214b3036d49f64cc15940c13fc98d696f94d10dd82` unchanged. Inspection of the user's complaint record showed active rules, not a detached dictionary: pilot outputs contained unlisted corrupt spellings. Another retained example produced a partial GPT replacement, demonstrating the dictionary was executing. No new aliases were added as a substitute for restoring recognition.

Public transcription reused the user's retained short ChatGPT recording, previously producing badly corrupted pilot text. Parakeet raw output was `Chat Gpt.`; pre-correction dictionary changed it to `ChatGPT.`, Loqira preserved it, final dictionary made no further change. Default response wall0.870s (ASR121.45ms, Loqira640.96ms, dictionary2.88ms, SAGE0ms). Raw+dictionary=false returned `Chat Gpt.` in0.216s with correction bypassed. This is one short integration observation, not a general speed or quality claim.

The native archive was checked against the source WAV hash and returned HTTP text. Backend, corrector SHA, pre/post dictionary stages, successful completion and raw opt-out were verified. Private evidence: `parakeet-loqira-live/public-observation/` contains request-start records, responses, provenance and result. Compilation and task-owned diff checks passed. All tracked deployment/request jobs collected. No new training, benchmark campaign or trial expiry scheduled.

### Delivery Gate Verification (Prose)

- PASS: states, hashes and timings are backed by observed service, HTTP and corpus receipts.
- PASS: restored recognizer, dictionary preprocessing and separate correction are described directly.
- PASS: one-recording verification is distinguished from broad quality and cold-boot validation.
