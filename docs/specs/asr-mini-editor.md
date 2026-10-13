# Local sub-billion ASR editor and embedding evaluation

## Contract
The human authorized as many useful tests as possible, including a <=1B local
editor or similar method, then specifically suggested EmbeddingGemma2. Preserve
raw ASR, original audio, provenance, opt-outs and trained RU/EN acoustic-head
restriction. Editing is a separately labeled experiment, not acoustic truth.
No production change/restart, external private audio/text upload, training,
waveform segmentation or appended waveform padding.

Shared disk has another session's compact-ASR/Deck/corpus work. Reuse its saved
outputs, do not repeat or claim ownership of its jobs. Keep this branch's files
separate; do not overwrite the other session's ASR spec or continuity record.
The overall goal remains active and unmet. Its 20-round cap is agent-selected,
not a user deadline or an instruction to request blanket reapproval.

## Frozen models and runtime
- llama.cpp b11429, source d81235049384534c167caea52b85a694f6103d14.
  Official CPU archive SHA256
  f6d25dde8f51133143d1453da4fd5f73b145127177612a283bf7995957af3392.
- Qwen2.5-0.5B-Instruct Q8_0, revision
  9217f5db79a29953eb74d5343926648285ec7e67. Artifact 675710816 bytes,
  SHA256 ca59ca7f13d0e15a8cfa77bd17e65d24f6844b554a7b6c12e07a5f89ff76844e.
  Actual native GGUF tensor count: 630167424 parameters, below 1B.
- Qwen3-0.6B Q8_0, revision 23749fefcc72300e3a2ad315e1317431b06b590a.
  Artifact 639446688 bytes, SHA256
  9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031.
  Actual native GGUF tensor count: 596049920 parameters.

Use native /v1/chat/completions and Jinja exactly once, context4096, CPU2,
KV-f16 defaults, temperature0, seed42, top_p1, repeat_penalty1, no GPU/MTP.
Qwen3 enable_thinking=false. Preserve model/runtime digest, payload, server
props/template, model metadata, raw response, usage, finish reason and timing.
The rendered prompt for each request was not separately exported; do not claim
it was. Greedy is a deliberate task setting, not a universal publisher setting.

## First batch: fixed text controls and two saved ASR Nbest
Compare conservative free editing and index-only selection for each model.
Ten synthetic cases cover negation, numbers, unknown names, Latin identifiers,
spelling, grammar, slang and incomplete phrases. Freeze inputs, candidates and
expected outputs before inference; never identify the correct candidate in the
prompt. Two real inputs use saved closed-word ASR Nbest, not the newer
state-forward decoder; no human gold exists.

Observed: 24 requests per model, 48 total. Normalized reference matches:
free editing Qwen2.5 3/10, Qwen3 5/10; selection 9/10 and10/10. These scores are
synthetic text control scores, not WER or audio accuracy. Free edits translated
Russian and dropped content. Qwen2.5 selection completed an unfinished thought.
Neither corrected the persistent ordinary-word error in the longer ASR text.
Whole batch wall36.243/48.316s; sampled peak RSS817.355/1152.723MiB.

## EmbeddingGemma 2: native whole-audio/text comparison
Primary sources:
- https://huggingface.co/google/embeddinggemma-2/tree/914f7f89142e33e77833254d9c9b90c3cef7303b
- https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2?hl=en

Verified repository is ungated, Apache2, 744371512 BF16 parameters in full
checkpoint. Weights1488915288bytes, SHA256
197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79.
Text+audio selective load disables vision; nominal size570M. It emits embeddings,
not generated text. Use one native FP32 CPU2 configuration, Transformers5.19.0.
Torch2.5.1 was incompatible (torch.accelerator missing); install Torch2.8.0 CPU
inside the new isolated environment, leaving the acoustic environment unchanged.

Whole original mono16k PCM16 WAV, no waveform padding, segmentation, resampling
or truncation. Explicitly disable batch padding and default truncation. The
native feature extractor's half-window semicausal STFT padding remains part of
the model. Audio gets no task prefix; candidate texts get the published
SentenceSimilarity prefix. Mean pool using attention mask, then FP32 L2
normalize to768D. Preserve vectors and raw cosine scores, not confidence labels.

Completed ten text controls and both original audio passes. Controls selected
expected candidate10/10. Audio forward1.300317/3.575227s, valid feature frames
580/1808, audio tokens145/452. Two whole recordings were not cropped.
Short clip preferred an ASR candidate with an extra trailing conjunction. Long
clip's negation-removed probe scored0.692962 against unchanged0.690761; a name
replacement probe also ranked higher. Probes were fixed minimal modifications,
not actual ASR candidates and not passed off as human references.

Original process exited1 AFTER both per-clip receipts and vectors were saved:
Transformers loading_info contained a set that JSON could not serialize. Partial
summary retained; recovered summary assembled only from existing observations.
Full-run wall time, peakRSS and loading details did not survive and are unknown.
No inference rerun for cosmetic evidence. Serialize sets for future executions;
that code fix has not itself been exercised by another embedding inference.
Do not use embedding cosine alone for word correctness or automatic editing.

## Corpus selection and attributable order diagnostic
Freeze all20 locally available successful corpus final Nbest at selection time,
with source hashes, plus3 new synthetic controls. Exclude missing/failed results;
no additional acoustic inference. Later another session completed an additional
corpus item; that item is not part of this frozen editor batch.

Same Qwen3 model, prompt and inference settings. First display candidates in
reverse acoustic order, exposing neither reference nor acoustic scores. Batch
completed23 requests: three controls matched3/3, real text changed14/20 from
acoustic rank0. A technical name changed and one negation was dropped.
Sixteen of20 real choices selected displayed index0. Whole51.796s,
sampled peakRSS1171.469MiB. No human gold: differences are not correctness counts.

Follow with ONE paired variant, preserving exact same20 texts/candidate sets,
model, prompt and sampler; change only display order to original acoustic rank.
This is a distinct order-sensitivity diagnostic, not a replay to improve scores.
Completed20 requests, displayed index0 selected20/20. Selected text changed in
14/20 pairs solely with candidate order. Whole47.030s, peakRSS1171.496MiB.
Reject native index generation as a reliable reranker in this configuration.
Do not combine its failures with embedding scores and assume they cancel out.

## Budgets and evidence
Skill defaults: smoke120s, paired screen600s, total900s per bounded iteration.
Agent guards: per-request90s, editor RSS3072MiB, available memory floor2048MiB,
swap growth256MiB. Embedding iteration900s, RSS6144MiB, same memory floor.
These are guard ceilings, not reservations, hardware maxima or a user deadline.
Models run sequentially. Retain consumed/unknown results after faults; do not
reset budgets or silently rerun completed cells. Wrong model answers are scores,
not a reason to request new approval for unchanged scope.

Total generation requests91 =48 initial +23 corpus +20 order diagnostic.
Separately: ten embedding text-control cases and two whole-audio passes.
Do not combine them into a misleading independent-test or audio-accuracy count.
Private self-contained HTML is rendered by mini_editor_report.py. Private
transcripts, manifests, vectors and weights remain outside Git.

## Round 10: conditional numerical candidate likelihood (new method)
Hypothesis: teacher-forced likelihood of each candidate independently avoids the
observed index-generation presentation bias. Keep pinned Qwen3 Q8_0, native
llama.cpp b11429, CPU2, FP16 KV and4096 context. Score candidate text as the
assistant continuation of the original conservative-edit prompt, conditioned on
raw ASR. No candidate list in model input and no generation. Use actual stored
Jinja template with enable_thinking=false exactly once. Force complete candidate
and end-of-turn token; compute log-softmax over full151936 vocabulary for every
candidate token. Primary score is mean log probability including end-of-turn;
retain sum and token counts, but no normalization/coefficient sweep. This score
is text likelihood, not acoustic evidence or probability of correctness.

The native server only documents probabilities of generated tokens; built-in
multiple-choice scorer drops a shared prefix, normalizes only divergent suffix
and does not export per-candidate scores. Rather than approximate via top-k,
implement a small standalone driver linked to downloaded matching libllama,
using publisher C API for teacher forcing and full-vocabulary log-softmax.
No library fork, training, dependency replacement, or production server.
Decode prefix once per candidate; clear KV between candidates. Chunk at64 tokens
only inside text inference (no audio segmentation), bounded logits buffers.
Candidate processing order canonical lexical; identical prompt/token paths reuse
exact stored score. Ties must remain explicit; never choose by displayed index.

Freeze original10 synthetic controls,3 previous holdout controls,2 saved
ASR development Nbest and20 collected Nbest before inference (35 cases).
Reusing input texts with a genuinely new scoring method is not repeating the
consumed index-generation configuration. Keep per-case sources/hashes and exact
rendered prefix, token IDs and per-token log probabilities. One diagnostic
numerical check compares batched versus one-token processing on a synthetic
short string before corpus scoring; tolerance1e-3 for CPU batch roundoff,
not transcript-quality admission. A mismatch stops dependent scoring.
Same agent resource floor2048MiB, swapgrowth256MiB, RSS3072MiB, CPU2;
method time600s batch/900s overall. No explicit candidate repair/probe tuning
based on audio results. Check protected negatives/names/numbers and incomplete
thoughts; compare selected real text but do not claim WER without human gold.
Other session owns the newer GigaAM29-record experiment; do not duplicate it.

### Numerical preflight recovery
Initial native launch stopped after exactly2 synthetic smoke passes, before any
of110 frozen candidate paths. Identical target token IDs but max per-token
logprob difference0.0320915 between chunk64 and chunk1 exceeds fixed1e-3 gate.
The gate was not relaxed. Native llama.cpp documents batch-dependent logits;
quantized/repacked CPU kernels are a hypothesis, not yet proven cause.
One attributable runtime recovery disables optional CPU weight repacking
(use_extra_bufts=false), leaving weights, text, KV and tolerance unchanged.
Run in a separate result directory with exact same frozen manifest/input hashes.
Retain failed output and execute no corpus scoring unless smoke passes. This is
not repeated failed model-quality evaluation: no candidate path was consumed.

### Sequential-only replacement after two failed batch comparisons
Disabling repacking produced the identical0.0320915 mismatch; repacking hypothesis
not supported. Both trials consumed only synthetic smoke, no candidate paths.
Do not relax1e-3 or claim batched equivalence. Change numerical method to entirely
single-token decode (prefix AND answer, n_batch=n_ubatch=1). This avoids mixing
GEMV/GEMM batch paths; exact underlying kernel cause remains unproven. Keep model,
template, candidate set, score normalization and resource/time limits unchanged.
Replace failed batched method rather than silently pass its test. Numerical
preflight now checks causal prefix invariance: same prefix/answer with extended
future text must have identical logprobs on shared token prefix (tolerance1e-6).
Save two smoke outputs and explicitly label this narrower property; it is not
independent native-vs-reference validation. The single-token score branch is
experiment-only and must not be marketed as exact cross-runtime likelihood.
New immutable outputdirectory likelihood-sequential;110 candidatepaths still
untouched. Run all within600s scoring/900s overall; retain partial if limit hit.

### Observed sequential result
Sequential-only execution completed all35cases/110unique candidatepaths plus2
causal-smoke passes, exit0. Shared7targettokens had exactly0 logprob difference
with future suffix changed. Original model and full-vocabulary teacher-forced
scores retained in JSONL; exact prompt/token boundaries and EOS verified.
Synthetic13/13 normalizedreference matches. Corpus19/20 unchanged relative to
acousticbest, one terminalfragment omitted; bothdevelopmentclips unchanged.
Across35cases no protectedLatin/numeric token missing and no negative-tokencount
change, which is NOT a semantic preservation proof. Residual ASRerror remains;
this shows conservative selection, not improved acoustic accuracy.

All594 permutations of stored score sets produce identical winnerTEXTsets,
zero additional modelcalls. This verifies selection mechanics only; no claim
of594 independent modeltests. Tiesexplicit(noambiguousdifferent-texttieshere).
Wall431.342360s, sampled peak1110.695313MiB, minimumavailable8717.691406MiB,
zero sampled swapgrowth. Corpus median all-candidate evaluation12.586736s on
harnessCPU2 (notDeck). Too slow and unprovenqualitygain for promotion.

Report amendment preserves initial91generationrequests separately from
110newscoredpaths,2successfulcausalchecks and4failedbatchdiagnosticpaths.
No acoustic pass or production change. Next useful mechanistic branch may
reuse common prefixKV for numerical scoring (performance) or enrich acoustically
supported alternatives (quality); currentcopy-biasedNbestselection cannot repair
words absentfromallcandidates. Do not repeatthissuiteasnewvalidation.

## Decision and continuation
No automatic promotion: free editing, index-only selection and embedding-only
ranking are not supported as a usable transcription repair by this evidence.
This closes the named candidate evaluation, not the overall bilingual ASR goal.
Potential next bounded branch: order-independent numerical likelihood per
candidate or acoustic verification of differing words with trained heads,
using retained evidence where possible. Neither is implemented/proven here.
Keep original baseline and opt-outs; no new acoustic model repeat or deployment
is justified merely by the editors' negative results.
