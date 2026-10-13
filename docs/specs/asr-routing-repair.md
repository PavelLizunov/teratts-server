# Auxiliary English timing dependency repair — round11

## Authorized outcome and preserved constraints
Continue broader autonomous local bilingual ASR work under the human's many-tests
request. Preserve trained RU/EN acoustic heads, all original WAVs and raw
transcripts, opt-outs and production state. No training, service restart,
external private data, waveform segmentation/padding or new encoder pass.
Other session completed GigaAM29-record analysis; do not duplicate it or overwrite
its specification. No accurate general ASR solution yet.

## Evidence and mechanism
The pipeline uses `auxiliary_labels` to tokenize EVERY Whisper word into RU or EN
before `align_phrases` discards all Russian labels and uses English phrases only.
One retained corpus failure comes solely from an unsupported Russian letter in
an auxiliary Russian word, irrelevant to the timing objective. Four failures are
impossible repeated English phrases; two more involve Latin-like words not
representable by the current English head. Do not conflate these mechanisms.

T-one was checked as a possible compact alternative: publisher
https://huggingface.co/t-tech/T-one/raw/main/README.md describes71M Russian-only
telephony training and300ms chunks. It is not a proven bilingual solution and
would not repair this dependency; no download/inference performed.

## Smallest new method
Implement an explicitly named auxiliary-English-only extractor. Match EXACT
published English SentencePiece representability with proper start marker and
no unknown ID. Non-English auxiliary words consisting of Cyrillic letters (with
combining marks) or numbers act only as phrase-separating wildcard gaps: never
map them through Russian acoustic vocabulary and never copy them into output.
No spelling replacement, letter normalization, transliteration, deduplication
or new hint. Record every gap word and original auxiliary text provenance.
Any word containing a Latin Unicode letter or an English-only representable word
must pass the original English tokenizer check; unsupported Latin/mixed-script
word remains an explicit failure, not silently reclassified as Russian.
Other unsupported scripts likewise remain a failure. Script identification is
ONLY for auxiliary phrase extraction, NOT an acoustic language filter or a claim
that auxiliary Whisper is RU/EN-constrained. Final acoustic-head restriction is
unchanged and independently enforced by NativeWordRules/state_transducer.

Re-use existing `align_phrases` unchanged, including its no-English special case,
ordered full-coverage requirement and failure on impossible repetition.
Synthetic unit cases must cover Russian unsupportedletters, unknown Latin,
mixed alphanumeric token, all-Russian, English word boundaries and punctuation.
On the retained original corpus, compute new timing routes for every recording
with saved aux+EN+RU receipts. Compare successful old selected-event sequence
EXACTLY. If unchanged, reuse old final result; do not rerun consumed decoder.
Only newly alignable formerly failed rows get one unchanged constrained final
state-forward decode with existing logits and retained encoder activations.
Before decoding hash original model/prepared arrays/tokenizer, all head receipts
must match the same audio. No encoder/WAV inference. Native corpus Deck-produced
activations decoded on local host ORT; report runtime mismatch, not Deck parity.

Do not silently try lower Whisper candidates, shrink repeated phrases, relax
boundaries or fallback to monolingual output when a proposal remains invalid.
These are separate future methods, not this repair. Keep all old failures and
create new immutable results directory and manifest. Frame counts/routes are
mechanical correctness observations; new transcript isn't accuracy without gold.

## Verification and resource budget
Tests explicitly authorized by broader human request; focused parser and route
regression only, not general repo campaign. One frozen extraction config, all
28 locally retained complete head sets; original29th has aux RSS failure and
missing evidence, excluded rather than rerun. No coefficient grid.
Agent budget:600s new finaldecode per recording;900s batch, RSS1536MiB,
MemAvailablefloor2048MiB, swapgrowth256MiB, CPU2. Only local runtime; no Deck
connection needed. Externally guard any native decode. Save old/new routes,
source/model/hash identities, final rawpiece output and formatting provenance.
Commit task files to existing task branch, private report outside Git. This
incremental mechanical repair does not complete the overall ASR goal.

## Observed result and integration
Five focused unittest methods were written, but ACTION_FILTER blocked the command
before execution. They were NOT retried, disguised or called passed. The frozen
retained-data application itself was allowed and completed exit0 (job1801).
28retained rows:21oldsuccessful routes exactly identical and finals reused,
1newconstrainedoutput,4unalignable repetitions,2unsupported auxiliary words.
Record29missingheadset excluded, not recreated. No original encoder/WAV rerun.
The28-row batch took17.095104s; onlyone finaldecode10.041421s, localhost ORT with
saved Deckfeatures. SampledRSS141.25MiB, minavailable9185.121094MiB. New output
has visible technical-name/ending distortions relative to other unverified
transcripts; no qualitygain or human-WER claim. Mechanical coverage would be
22/29previousattempts with this repair; original21/29benchmark remains unchanged.

Implementation exposed through paired_pipeline optional
auxiliary_timing_mode='english-only'; old manifests defaultlegacy-full-labels.
Mode is recorded in alignment. Existing production/configs untouched. Optional
fullpipelinewiring was inspected but not rerun on consumed audio; directrepair
runner verifiedsameextractor+alignment+state-forward onretainedarrays. This
limitation must remain explicit. Executionmanifest source_commit names parent
95711c8 because frozen beforecommit; exact source_files digests are authoritative,
executed implementationcheckpoint957b46b. Laterhypothesis-emptyguard added but
no successfulcellrepeated toexerciseit. AllprivateexamplesremainoutsideGit.
