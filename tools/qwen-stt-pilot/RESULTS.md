# Expanded personal Russian STT comparison — 2026-10-08

## Scope and interpretation

The user approved all viable previously presented candidates and a listening
page. Same fixed five original WAVs, 74.620875 seconds, plus exact one-second
silence/weak-noise controls. No transcript hints, no invented human references,
no WER against prior ASR text. No private audio uploaded outside homelab. No
production speech service restart/switch or worker memory reconfiguration.

The private page embeds original audio and actual receipt text, supports model
filters, local preferred-text selection, optional human correction and export.
Generated private payload is excluded from source Git. Browser verification
covered audio metadata/decoding, vote preserving playback, local correction,
JSON export, control filtering, 390px mobile layout and zero page errors.
HTTP was verified through the direct Tailnet interface; that is not proof of
user-device reachability. The user approved independent port 8290.

## Matrix

| Candidate | Exact run path | State |
|---|---|---|
| Parakeet TDT v3 | retained NeMo 0.1.0, Q8_0 Deck Vulkan | 7/7 reused verified outputs |
| Qwen3-ASR 1.7B | pinned original BF16, native C CPU | 7/7 reused verified outputs |
| Qwen3-ASR 0.6B | pinned original BF16, same native C CPU | 7/7 |
| Nemotron 3.5 ASR 0.6B | official Q8_0, NeMo 0.2.0 CPU, explicit ru-RU | 7/7; clip/offline mode, not live streaming test |
| GigaAM v3 CTC | documented Q8_0 native conversion, greedy CTC | 7/7 |
| GigaAM v3 RNNT | documented Q8_0 native conversion | 7/7 |
| T-one | official ONNX, onnx-asr, 8kHz explicit resample, greedy no LM | 7/7; not its recommended beam/LM configuration |
| Canary 1B v2 | documented Q8_0 native conversion, explicit ru | 7/7 |
| Whisper large-v3 turbo | mature whisper.cpp Q8_0, explicit ru, no VAD | 7/7 |
| Whisper large-v3 | mature whisper.cpp F16 | 7/7 |
| Russian Whisper antony66 | exact original fine-tune, inspected upstream F16 conversion | 7/7; source/converted SHA verified |
| Voxtral Mini 4B Realtime | documented native Q8_0, CPU | 7/7; offline requests, not live streaming evaluation |
| OmniASR CTC 300M v2 | pinned community HF F32 conversion | Attempted; cannot load unknown `omniasr_ctc` architecture in installed Transformers 5.17 |

Cohere Transcribe excluded as inapplicable: Russian is not a declared language.
Retained rejected GigaAM Multilingual and technical codeswitch Whisper are
historical, not silently substituted for these models.

Final total: 13 candidate variants represented, 12 complete (84 successful
model/clip pairs), one genuine loader failure (OmniASR). No pending target on
final page. The two invalid experimental Whisper-port branches are preserved
separately and are not counted as completed candidate quality tests; their
mature-engine replacements each completed all seven clips.

## Decoder integrity and preserved failures

Initial common transcribe.cpp Whisper attempts exposed an implementation
boundary: turbo produced non-UTF8 text and multilingual gibberish; large-v3
returned one word for a complaint WAV. Stop invalid port work, preserve all raw
stdout/stderr/receipts and mark those outputs diagnostic, not a model quality
ranking. Mature upstream whisper.cpp is a separately recorded corrected-engine
retry, not erased history. Large invalid decoder cancellation was targeted to
only the exact owned process group after collection; no speech service touched.

The native CLI prints metadata to stdout as well as text. Its parser was corrected
to extract exactly one `text:` field. Existing successful GigaAM outputs were
reparsed from retained raw stdout, without rerunning inference or fabricating
texts. Tests now cover that parser boundary.

The exact antony66 converter first failed because its upstream NumPy conversion
assumed float32/float16 and the checkpoint has BF16 tensors. A bounded adapter
changes only `.squeeze().numpy()` to `.float().squeeze().numpy()` per tensor,
preserving upstream F16 file format and tensor naming. Original failure log,
converter/adapter SHA and converted asset SHA are retained; this is not a
substitution of another Russian fine-tune.

OmniASR checkpoint config declares `transformers_version=5.19.0.dev0`; installed
5.17 has no architecture mapping, and the public main source lookup for that
architecture was unavailable. No remote code guessed, architecture rewritten or
other model substituted. Its failure is visible on the page, with no transcript.

## Negative controls in completed variants

| Model | Digital silence | Weak deterministic noise |
|---|---|---|
| Parakeet | empty | nonempty English fragment |
| Qwen 1.7B | nonempty | nonempty |
| Qwen 0.6B | nonempty | nonempty |
| Nemotron | empty | empty |
| GigaAM CTC/RNNT | empty | empty |
| T-one | empty | empty |
| Canary | nonempty | nonempty |
| Whisper turbo, mature engine | nonempty | nonempty |
| Russian antony66, mature engine | nonempty | nonempty |
| Whisper large-v3, mature engine | nonempty | nonempty |
| Voxtral Realtime Q8_0 | empty | empty |

These are finite synthetic controls without VAD, not real-world hallucination
rates or proof a model can never work with a suitable speech gate. Real speech
outputs must be assessed by listening. Fine punctuation is not a substitute for
recovering actually spoken words.

## Verification and known limits

All completed paired outputs have exact original WAV and frozen manifest SHA,
zero process exits, actual runtime/model revision and observed memory/time.
One heavy inference at a time, two threads, nice19, 8GB sampled-RSS stop and
15-minute per-variant budget. Sampled RSS is not a hard OS limit. Startup and
model load are repeated per clip; timings are diagnostic, not a fair resident
latency benchmark. Current CPU tests cannot establish Vulkan-on-Deck speed.

Working speech service PIDs remain 3132587/3132657 with NRestarts=0 at inspections.
Root cause of reported degradation and Omarchy capture configuration remain
unproven. Manual user preference/reference evaluation is pending.
