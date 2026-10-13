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

## Round12 — one acoustically corroborated timing method (frozen before run)
Cause: mandatory full auxiliary English phrases can hallucinate repetitions and
consume Russian time. New independent *timing* gate uses existing trained English
CTC argmax path, not an editor or another encoder. Collapse CTC repeats before
removing blank; exclude unknown0 identically to established decoder. Decode
publisher subwords to words with original separators/punctuation policy. Extract
exact representable auxiliary English words with round11 extractor; retain
unsupported Latin/mixed words as explicit failure (no transliteration/repair).
Use deterministic maximum-cardinality monotone exact-word matching (LCS) between
auxiliary English word occurrences and native greedy English word occurrences.
No fuzzy match, similarity threshold, coefficient grid or human words. Matches
retain original auxiliary trained token IDs. Unmatched English occurrences and
original Russian/numeric gaps become separators, not output text. Repeated
auxiliary words can therefore match no more occurrences than emitted by the CTC
path. Reuse unchanged align_phrases over corroborated runs to obtain routing;
matched greedy frame spans are diagnostic only, not manually shifted boundaries.
If no word matches, record explicit all-Russian fallback/English abstention;
never call this successful bilingual recognition. This remains uncalibrated
cross-model agreement, NOT frame-LID; genuine names absent in greedy may be lost.
The final open trained-head state-forward decoder and fixed hints2.5 do not change.

Apply to all28 saved corpus head sets in original order, compare with round11
routes and outputs, reuse identical successful routes without decoder repetition.
Changed routes get one new decode, preserve every result including regressions.
Human gold remains0: describe changed tokens, loss of previous names and agreement
with archived raw model text, never accuracy/WER. Corpus is exploratory, not blind.
No training, no waveform/encoder pass, no new baseline, no service/config changes.
Budget unchanged: localCPU2;600s/record,900s/batch,1536MiB RSS,2048MiB availablefloor,
256MiB swapgrowth. Hash source/inputs, preserve round11 receipts. All model calls
are native GigaAM joiner/predictor only; report local rather than Deck timing.
If exact gate over-rejects true-looking names, retain negative result and do not
loosen it post hoc. This is useful quality-focused counterexample, not automatic
promotion or reason to silently adopt a monolingual fallback. No rerun of denied
round11 unittests; method invariants checked in its actual authorized execution.

### Round12 observed result
Frozen code3e48ed70c3ef6c59576144b7cdc533cff3088975, job1820exit0collected.
28completeheadsets:16newdecodes,10exact-route/outputreuses,2unchangedunsupported.
All16newrouteswereall-Russianfallback;26outputs vs22round11, with4priorrepetition
failuresnowreturningRussiantext. No usefulqualitypromotion: only3/223auxEnglish
wordoccurrencesconfirmed (denominator includes146repeatsfromonesample). English
framesremainonly2records, vs14previouslysuccessfulEnglishroutedrecords.
12/22oldoutputschange;11/22loseatleastonepriorEnglishword. Prioroutputsnotgold:
absenceisnotWER, but disablingEnglishdoesnotmeetrequestedbilingualoutcome.
Specificpreviouslyrecoveredtechnicalnamesarenowtransliteratedoromitted;full
privatepairsretained. Exactgreedygateisnotrecommended;donotloosenposthoc.
Batch37.555438s,16newdecode sum25.990502s/median.904819s;sampledRSS110.230469MiB,
minavailable9239.796875MiB,swapgrowth0.0MiB;CPUhostnotDeck. Lowerlatencyreflects
all-Russianrouting,notaspeedupofsamebilingualwork. Noencoder/WAVpasses.
Archivedrawagreementon22samepairs changed from2same/11small/9substantial to
3same/13small/6substantial, butthisisNOTaccuracyorqualitygainandcannotjustifygate.
Observedretainedarrays/reusedsourceshashchecked,realpathinvariantsexecuted;
noadditionalunitchecksorblockedcommandretries. Production/primarypipeline
unchanged;newgateonlyexplicit routing_repair timing_method setting. Reportadds
all28pairsandfallbacklabelsintocumulativeprivateHTML,sourcecontainsnoprivategold.

NextmechanismmustretainacousticallyplausiblenonargmaxEnglishlabelsandalsoallow
Whispertimingtobeuncertain; exacttop1agreementcannotachieveboth. Candidate
RNNT/CTCword-boundaryjointsearchortrainedlocalframeLIDneedsfixedwell-defined
objectivebeforeexecution; no newvariantselectedorlaunchpendingthisround.

## Round13 — exact CTC whole-word occurrence evidence, not a new gate
Round12 top1 conflated absence in a greedy path with absence of acoustic support.
Compute P(collapsed CTC piece stream contains whole target word/phrase) by a
weighted deterministic character automaton times the previous raw CTC label.
Use all1023 trained EN pieces and blank1024, unknown0 excluded and renormalized
exactly as existingdecoder. Every distinct raw alignment has one deterministic
path; repeats collapse BEFORE blank removal. Feed newly emitted pieces through
the word/phrase automaton after published ▁→space and SAME separator/punctuation
policy as auxiliary_words. Start/EOF boundaries count, wholewordend required;
all valid piece segmentations of the same spelling are included, not just the
publisher canonicalencode path. Case follows original uncased tokenizer, no
phonetic/fuzzy normalization. Targets are all unique representable English
auxiliary words PLUS the fixed four existing hints on each of28headsets. Keep
unsupportedauxwordfailures as metadata;fixedhintsstillcanbediagnosed. No targets
from production/comparator text or human guesses. Duplicatewordoccurrences do
not cause repeatedcomputation. Hints are diagnosticqueries here, NOT outputvocab.

Log-space sum-product DP state(partialcharacterprefix,last_raw_token);absorbing
found mass records each raw path at first complete match only. Other-word dead
state resets on boundary. Stable prefix/suffix logadds exclude repeated raw
label without near1 subtraction. Newly repeated label remains at same DFAstate;
blank resets last rawlabel but emits nothing. Save perframefirst-completionmass,
EOFcompletionmass and exactprobability; model distribution only, NOT calibrated
word correctness or RU/EN frameLID. Conserve found+unfound probability perframe.
For multiwordphrase collapse consecutiveboundarysymbols; require initial/trailing
wordboundaries, allow re-start at internalwordboundary on mismatch using a
prefix automaton rather than dropping possible suffix matches.

Before realdata, new small-vocabulary enumeration checks SAME algorithm against
all3^5 raw paths (blank,a,b) for repeatedlabels/wordboundary/EOF; controlscontain
no privateaudio and are not ASRaccuracy. These are distinct newalgorithmcontrols,
not retriesofdeniedround11unittests. Checkstepmassandboundsinactual28recordrun.
No transcriptdecode, modelweights/joiner/encoder/audio load, no thresholdselection,
noautomaticall-RUfallback, no arbitrarycoefficients. Evidence determineswhether
softpathsupportmeritsfutureopenjointsearch; negativeoutcome staysnegative.
HostNumPyCPU,agent600sbatch/RSS1536MiB/floor2048/swap256;samehashes,immutable
round13directory/manifest. Do notclaimwordconfidence/qualityfrommathcorrectness.

Verdict: Extend — existing numerical CTC/retained-input conventions; repo has
fixedpathforcealign and maxphrasealignment but not all-segmentations occurrence
probability. No additional runtime/dependency. Background reference:
https://github.com/huggingface/audio-transformers-course/blob/main/chapters/en/chapter3/ctc.mdx
explains CTC collapse and multiple paths; custom finitewordevent algorithm is
ours, not a claimed official implementation or published benchmark.

### Round13 observed result
Frozen1ed85cc5af5aa0b2f74961810b687fdd5efadd21,job1868exit0collected. All28records,
133unique record/target events,28auxiliaryrecordwords,4fixedhints perrecordwith
intersectionsdeduplicated. Greedypresents3events;allother130evaluatedwithout
forcingtarget. Tennewenumerationcontrolsactuallyexecutedbeforecorpus:6targets
x243paths+4targets x256paths, maximumabsoluteerror2.220446e-16. Notthousands of
modelcalls/audioqualitytests. Corpusmaximumlogmassconservationerror1.851958e-14.
No newtranscripts/modelcalls/headroutingorproductionchanges. Allfullperframe
firstcompletionmassesandEOFmassretained;nofitteddecisionthreshold.

Nonargmaxevidenceexistsbutoftenveryweak. Privatec018DSHevent.0004313467937,
c028ChatGPTevent5.89514744e-7;earliercontextualoutputshadthesespellings butare
notgold. RepeatedauxChatGPTc0217.43832638e-12,c0264.62691603e-11;thisobservation
isnotgeneralizablethreshold. Topnon-greedyauxevent.0839717347;greedyGemini/GPT
.3263792458/.1249878047. Probabilitydependsliteralword/phraseandlength,allpossible
subwordsegmentationsincludedbutphonetic/transliterated/spaced-acronymaliasesNOT.
No reliablelanguageconfidencemodelclaimed. Need audio-supported broadercandidate
pathsorbetterauxiliarytiming,notstackinguncalibratedscoresanddeclaringtruth.

Worker13.407699s/supervised13.628471s;medianrecord.376547s;highwater61.15625MiB,
sampled61.242188MiB,minavailable8965.65625MiB,swapgrowth0. Limits1536MiBprocess /
2048MiBavailablefloor,notallocations. LocalNumPy-onlyhost,savedDeckarrays;noDeck
latencyclaim. Tencontrolsnewalgorithmactualrun,notdeniedround11unittestretries.
FullobservationsoutsideGit and cumulativeprivateHTML; rawASRbaselineunchanged.

## Round14 — replace auxiliary generator, retain trained-head decoder
Hypothesis: Whisper's repeated/out-of-vocabulary English timing proposals are an
upstream failure; more gates on those same proposals cannot create missing good
intervals. Use existing pinnedQwen3-ASR-0.6B nativeBF16 as AUXILIARYonly, not a
replacementtrainedpair or transcripteditor. NativeEnglishCTC+GigaAMRURNNT remain
ONLYfinalemittingheads. Same28originalcorpusheadsets, samefixedhints2.5 forfinal,
round11English-onlyextractor, originalorderedphrasealignment/state-forward.
Qwen gets wholeoriginalWAV, autolanguage, no hints/context, -S0, --past-text no,
--silent, CPU2. No new variant sweep or default-multilingual output promotion.
Qwen itself is multilingual and cannot satisfystrictpairalone; only itsEnglish
phraseorderingreachesfinaldecoding. Unsupportedproposalsstillfailratherthan
rewritingtheirwords. Unlikehardgreedygate, noEnglishconfirmationthreshold.

ExistingmodelQwen/Qwen3-ASR-0.6Brev5eb144179a02acc5e5ba31e748d22b0cf3e303b0;
existingnativeantirez/qwen-asrrev924694251d9e0f18e5d86bbd06aa3ab5f870002d.
Reuse downloadedweights/engine, inspectsource/hashbinary/actualtensorcount.
Priorsevenclipmatrix andtwooriginalcodeswitchrunsdoNOTproveperformanceonthis
28recordcorpus. InspectknownpriorreceiptsbyoriginalaudioSHA/config;reusesuccessful
identicalauxiliaryconfiguration iffound; neverduplicateconsumed/unknowninference.
OriginalcorpusWAVs nowverifiedavailableingigaam-followup/clips fromother-session;
read/hashsamebytes, don'tdownloadorcopyinventednewaudio. Oldmissing29thheadset
excludedfromthispairedtrial, notrerun.

Runtimepreflightfoundlibgfortranmissingwithouttaskenv; establishedtask-local
LD_LIBRARY_PATH resolvesit, nofailedinferenceconsumed/systemchanges. Source
qwen_transcribe_audio -S0callsonewholetranscribe_segment,bypassingsegmentation
andits shortsegmentzeropadding. skip-silenceoff; nofile/waveformappend. Native
STFTreflect-centering ismodelfrontendnotappendedsilence, retained/disclosed.
Pinall8modelassets, nativebinary, linkedtasklibs, selectedruntimeCfiles,source
revision;validateWAVgeometry/length/hashbeforeeachcall, privatefileprovenance.

Twoindependentboundedstages: auxiliarybatch900s,180s/clip,RSS4096MiB,availablefloor
2048MiB,swapgrowth256MiB,nice19CPU2; thenfinal-onlyretaineddata900s/600sperclip,
RSS1536MiB/samefloor. Agentmethodlimitsnotuserdeadline orreservedallocation.
Hostonly: noDeckrun/budgetclaim. Exactroutealreadyseeninround11or12reuseoutput
ratherthannewdecode; preservebaselinecomparisons andwhichresultwasreused.
Changedroutegetsonefreshfinaldecodewitholdheadarrays,noacousticheadrerun.
SaveallQwenrawstdout/stderr/output/status,samples,startedmarker,receipt/hash.
Onefailedproposalisnotnoaudioquality;knownfailurespreservedandindependentother
recordscontinueunlessresourceguardstopsbatch. Noautoresumeunknownresults.
Newsourceownspec/README/privateHTMLonly;productionunchanged.

Observe whole28statuscounts,Englishroutingdrop/add,technicalnamechanges,
originalrawmodelagreementNOTaccuracy,auxvsfinaldisagreements,exactreuse/novel
finaldecodes,hoststagewall/RSS. Human gold remains0; noWERorpassedqualityclaim.
Verdict: Extend — alreadyinspected/pinnednativeQwenCLI plus existingretained-head
runner; no new dependency, modeldownload, enginefeature or externalprivatecall.
