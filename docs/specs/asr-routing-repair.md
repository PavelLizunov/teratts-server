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

### Round14 observed result
Pinnedsource67f8857,job1939auxiliary28/28success,job1956final28/28outputs,both
collectedexit0. Parametersreadfromsafetensors938008576(totalencoder+decoder),
under1Bbutnotliteral600M. Verifiedall8assets+binary/taskBLAS/sourcehashes;
knownpriorQwenmatrix/developmentaudioSHAoverlap0,28genuinefreshauxiliarycalls.
Originalcorpus28audio167.705125s;noEN/RUencoderrepeats. Final13round11routeexact
reuses+9round12identicalroutereuses+6newdecodes. All6oldround11failuresnowoutputs;
no previoussuccesslost. NewEnglishroutes10vs14previoussuccessful;18allRU(noEN
auxwords),7/22pairedrecordslosesomeoldENwords,2addENwords;9/22textschanged.
TheseincludesreplacementofnonsenseforcedENwithRU,notallwordlossesbad;nogold.

Concretecausalobservations/privateexamplesallinHTML: c027Englishframes47→11,
repeatedauxnamegoneandRUcontinuation+technicalnamepresent; c00944→3recoveringRU
butnamegarbled. c018GSHauxsameintervalandretainedDSHfinaldemonstratesnospelling
copy. c022newGitHubintervalfinalDSHunderunchangedhintgraph;timingrepairnotname
selectionrepair. c002QwenLatinizesRU(allENroute)showingunconstrainedauxLIDrisk.
KeepQwenbranchforfurtherinvestigation,notqualitypromoted/mainpipelineadopted.
Full28outputsNOT28correcttranscripts. Oldcorpus21/29+round11remainimmutable.

Auxbatch132.352457s,medianperclipcold4.070699s,sampledRSS2706.917969MiB.
Final-onlybatch29.116681s,6decode sum16.685243s/median2.091990s,
sampledRSS113.527344MiB;sequentialpeaksnotadded;minavailable7697.628906MiB,
swap0. NoDeckmeasurement/fullcoldchainclaim. Archivedrawagreementpaired22:
old2same/11small/9substantial,new3same/12small/7substantial,NOTaccuracy.
AuxQwenvsfinal16substantial/9small/3same;Qwennotgold. No humanreferences.

Nextqualitymechanism: fixedglobalcontext namesmaycrowdoutnewnameevenwithbetter
interval. IsolatecontextcausallyonallnewQwenENroutesusingretainedarrays and
pre-registeredfixedcontext-offvariant (notgrid),orinspectexistingcandidate
pathscorebreakdownbeforeclaimingcause. DoNOThandpickc022fix/newGitHubhintonly,
notlanguagefilter/rewrite,donotclaimcontextisthecausewithoutcomparison.

## Round15 — fixed context-off control on every Qwen English route

Question: how much of the changed name selection comes from the fixed context
component, rather than the auxiliary proposal alone? Run exactly one new control:
`context_score: 0.0`, against retained round14 `2.5`. Select all ten round14
records with any English frames by route metadata, irrespective of output text.
The other18 all-Russian routes are outside this contrast and are not new trials.
Keep Qwen proposals, ordered phrase alignment, original acoustic arrays, full
trained token inventories, Russian history beam4/native word closure and
same-token-text approximate forward search unchanged. No Qwen/encoder reruns,
new hints, coefficient grid, custom spelling variants or manual text merging.

Extend the existing runner with explicit context_score (default2.5) and forbid
reuse across different search context scores. Every control must reproduce the
entire prior selected_events sequence; otherwise stop rather than attribute a
changed route to context. Pin manifests/source/receipts before execution; previous
results remain immutable. Reject consumed output directories. Existing guard:
600s/record,900s/batch,RSS1536MiB,available floor2048MiB,swap growth256MiB; these
are method limits, not a user deadline. Host final-only inference, no Deck run.

The existing decoder removes the context graph when score is zero, so this
intervention includes context-guided retention/recombination, not just final
score subtraction on a fixed hypothesis set. State this confound explicitly.
Do not call retained_same_text_logsum an exact posterior or compare its changes
as an exact acoustic likelihood ratio across different pruned searches. Inspect
all ten top outputs and stored alternatives; report context credit, retained
acoustic score, total, state counts, language-preserving vs lost names, and whole
string changes. Agreement with Qwen/archive is descriptive, not accuracy.

Before-run source observation: one anomalous final name has12.5 context credit
at2.5 per context symbol. Context symbols include boundary markers; this is not
word confidence. All four retained hypotheses in that record share the name,
so subtracting credit from that saved top4 cannot discover a missing alternative.
Fresh zero-context search is genuinely distinct, necessary decoder work. No
human references exist; successful output is not a quality pass. Preserve raw
and formatting-only output separately in the existing private cumulative report.
Verdict: Extend the existing dependency-free runner; state_transducer already
supports zero bonus and is unchanged. No new dependency or model download.

### Round15a observation and bounded mechanism follow-up
First control completed10/10, exact routes10/10; eight texts changed. Both
previous ChatGPT spellings and all five DSH spellings disappeared, but the
previous GitHub error did not become GitHub. Russian token histories changed
in two records, including a record without a completed fixed hint. This does
not justify switching context off. Runtime52.491205s decode/60.669856s supervised,
RSS highwater131.296875MiB/sample128.917969MiB; no model/encoder reruns.

The predeclared caveat is now directly relevant: zero bonus removed context
state partitions. Run one bounded follow-up on the SAME ten records, keeping the
same fixed hint automaton transitions/state keys as baseline but setting every
credit contribution to zero. This is a structural control, not another bonus
coefficient. ContextBias instantiated with unit score supplies state transitions;
all step/finalization deltas are multiplied by zero. No graph/token inventory,
beam, interval or text change. Nonzero-bonus/default behavior must remain exact.
Compare baseline2.5, zero-without-graph and zero-with-graph. No earlier variant is
rerun. Record both bonus and graph-retention mode and disallow cross-mode reuse.
Keep all results; the mechanism follow-up is registered after the first outcome,
not a preregistered blinded test. Same host bounds and previous safety invariants.
The count is20 genuinely distinct final decodes if both ten-record controls finish,
not20 recordings or acoustic encoder calls. Numerical state/credit identities can
be checked with the configured hint symbols before consuming this control.

### Round15 final observed result
Both controls completed: runtime d279017 (no graph), e27e1f5 (retained graph),
jobs2018/2062 collected exit0. Exactly20 new final decodes on10records,0Qwen/audio
encoder calls; no baseline2.5 repeats. Both reproduce prior selected_events10/10,
all zero-context outputs have context_credit0. Graph transitions verified on45
synthetic sequences/351 steps with identical states and exact scaled credit;
not full decoder parity or a speech-quality test.

Best trained-token paths match10/10 between the two zero controls. Both differ
from baseline in8/10 texts,7/10ENtoken paths and2/10RUtoken paths. All5priorDSH
spellings and2ChatGPTspellings disappear (one alsoChatGPTPro); no literal fixed
hint spelling remains. This is diagnostic spelling comparison, not correctness.
Original hints includeOracle, absent from this ten-record best-output subset.
Seven zero-best paths were absent from oldtop4; mere stored-score subtraction
matches3/10. No old acoustic mass is treated as exact posterior across searches.

Therefore the score intervention, including its influence on pruning, explains
the observed best-output change under the same retained automaton; state removal
alone did not change these ten best paths. This does NOT prove beam-independent
acoustic truth, pure final-score causality or a general failure rate. Private
examples: name replacement disappears but sought name does not return; known
prior names fragment. Zero controls rejected as replacement. Preservedefault2.5.
No learned contextual relevance or new name-specific hint introduced in this round.

No-graph wall60.669856s/decode52.491205s/median3.480537s; retained-graph
wall46.552394s/decode40.617951s/median3.945650s. Reconciled combinedwall107.222250s,
combineddecode93.109156s. Highwatermax135.320313MiB,sampledmax133.253906MiB,
minavailable8887.839844MiB,swap0. Sequentialmemorypeaksnotadded; runtime noise
not investigated and faster batch not attributed to graph retention. Maxstates
baseline8364/no-graph8189/retained8364. Host-only, no full-chain/Deck claim.
Raw/archiveagreement10records5small/5substantial inallthreevariants,notaccuracy.
No human gold. All comparisons/alternatives in private cumulative HTML; outputs,
raw-piece provenance, separate formatting and prior artifacts remain untouched.

Next bounded direction, NOT frozen/launched: interval-local contextual relevance
using an unmodified auxiliary phrase, with open-vocabulary final heads and raw
provenance. Must not become a closed phrase decoder, replace text, hardcode the
observed missing name or assign model agreement the status of acoustic truth.
Alternatively examine stronger English specialist support for Russian-accented
names; known consumed model matrix must be checked first. No coefficient sweep.

## Round16 — auxiliary phrase context scoped to its fixed English interval

One new decoder mode, `context_mode: auxiliary-interval-v1`, uses each unchanged
Qwen English phrase as the ONLY soft contextual path in its own saved interval.
No old global hints in this mode, no added spelling/alias/name. Use the same
canonical trained token IDs already used by the aligner; append context-only
right boundary. Keep score2.5, the full open trained EN/RU vocabulary, native
word closure, RU-history beam4 and fixed round14 events. All ten EN routes are
included independent of text;18allRU routes not rerun. No new audio/Qwen pass.
This is a new coupled method: the auxiliary model now influences both timing
and context ranking, not just timing. Agreement with it is NOT independent
confirmation, and a wrong proposal can be reinforced. Never label this correction
as acoustic truth. Raw pieces, context paths and auxiliary provenance retained.

Each English interval has a separate ContextBias graph. Outside it the graph is
empty. On leaving/changing interval, add a virtual context-only right boundary,
settle completed matches/refund unfinished prefixes, then clear graph state.
Do not reset RU predictor, output prefix or CTC blank state; do not emit delimiter
IDs or alter the route. The next graph sees only tokens emitted in its interval.
EOS uses the same settlement once. This is not independent region decoding or
waveform segmentation. Boundaries are the existing inferred intervals, not gold.

Unlike global text-only credit, scoped credit can differ for identical output
IDs emitted at different times. Therefore accumulated credit must partition
state keys, same-text grouping and final retained alternatives in this mode.
Sum acoustic paths ONLY when both emitted IDs and credit agree; max-compete
other texts. Keep separate text+credit alternatives rather than falsely calling
a mixed-credit score an acoustic logsum. Record this approximation/possible
duplicate strings. No change to default global context behavior.

Freeze manifests/source before execution. Require exact prior selected_events,
and prevent cache reuse across context modes as well as scores/graph options.
Numerical controls: full phrase reward at interval exit; incomplete prefix refund;
no match/reward leakage across intervals; outside-interval tokens unrewarded;
identical-output paths with different credit remain separate. Tiny synthetic
open search must be able to reject a weak proposal in favor of another trained
word. Those are algorithm controls, not gold speech or repetitions of old tests.
Same host limits600s/cell,900s/batch,RSS1536MiB,availablefloor2048MiB,swap256MiB.
One changed run per ten records; consumed/unknown cells never replayed. Include
all10 outcomes, new names vs lost names, RU changes and resources in privateHTML.
No production promotion, fullchain/Deck or accuracy claim from successful scripts.
Verdict: Extend existing ContextBias and state_transducer; new small scheduling
module, no dependency/model download. No coefficient grid or hard phrase filter.

### Round16 observed result
Frozenruntime f757a8b,job2197collectedexit0. All10selectedrecords completed new
final decodes, all10routes exactly unchanged. Eleven original auxiliary English
phrases became interval-local paths. Baseline literal proposed-phrase matches5/11,
zero-control3/11,new10/11; coupled proposal agreement, NOT accuracy or timing
validation. Against baseline6/10texts changed; againstzero7/10. Russian token
histories changed in2(c005,c022),9bestoutputs have nonzero credit. Currenttop4
contain no duplicate strings, although same-text/different-credit is supported.

Private observations: c003globalDSH→GPT; c015globalDSH→GitHub; c022→GitHub but
precedingRussianfragment and changedopeningremain. c027/28retainChatGPT(Pro).
c018copiesQwenerrorGSHinsteadoldDSH throughrewardedacousticpath; c002reinforces
LatinizationofRU. c009GitHubstilllosesandalltop4credit0:softbiasnotclosedlexicon.
No selective splicing or hand-added names. Hold experimental; not baseline/production
promotion. Two dependencies remain: correct auxiliary language/spelling and
native phrase boundary/acoustic support. Identified gains do not establish gold.

Six new credit-settlement controls, two tiny open-search controls and explicit
credit-key identity control ran successfully before corpus. Weakproposal rejected;
identicaltextpaths with credits0and7.5 retained separately. Not fulldecoderparity
orquality. Runtime checks validatedtrainedpathconstraints, hashes and schedule;
no new Qwen/audioencoder forward. Default global scoring remains unchanged in
logic; consumed default corpus was not rerun. Production files untouched.

Host supervised115.522938s,decode109.723221s/median5.614234s;
longestc01555.984132s. Highwater199.398438MiB,sampled199.550781MiB,
minavailable8826.3125MiB,swap0,maxstates58400 (oldglobal8364).
Extra credit partitions increase state capacity, but no profiler attribution or
clean speed comparison. Larger state search still approximate; credit timing
classes are not marginalized across final candidates. Human gold0. Archive
agreement stays5small/5substantial,notaccuracy. NoDeck/fullchain timing claim.

Next not frozen: c009fails despite correct-looking auxiliary name, c022duplicates
Russian namefragment. Inspect existing fixed phrase intervals against retained
RU/EN acoustic evidence and search alternatives before adjusting boundaries.
Do not pad waveform/hand-move intervals to desired output or raisecontextscore.
Also auxiliary Latinization/GSH failure needs independent evidence; simply trust
Qwenmore is contradicted. Preserve all methods and raw provenance.

## Round17 — inspect boundary uncertainty before changing any route

One numerical diagnosis over all11original English phrases on the same10records.
No new transcript/route, waveform reads, encoder/Qwen/decoder reruns or manually
expanded intervals. Use original saved EN log probabilities and round16 alignment
receipts, model mapping and hashes. English-only diagnosis does not independently
locate Russian token emissions; it cannot prove the source of a duplicated RU
fragment. Context and acoustic failures must remain distinguished.

Reconstruct the existing ordered phrase graph (self-looping label/blank states,
zero-cost wildcard gaps, label emission logp minus per-frame maximum). Verify its
Viterbi score and traceback against the saved aligner. Then compute exact forward
and backward sums over complete paths in THIS graph, normalize by its partition,
and derive first/last phrase-frame distributions and occupancy. These are
conditional weighted alignment distributions given the requested canonical
phrases and wildcard construction; NOT calibrated timing/word/language confidence
or CTC transcript probability. Wildcard max-path gaps and path multiplicity affect
the measure. All phrase labels remain forced for diagnosis even if auxiliary wrong.

For each phrase report original interval, minimum CTC frames (tokens + adjacent
repeats), length slack, mode/mean/entropy and fixed5–95percentile frame ranges for
first/last boundaries, mass of the exact selected span (separate constrained-DP
sum, not product of marginals), conditional occupancy outside it, and frames of
highest boundary mass. No percentile is used as a new decode route or threshold.
Use all frames with original80ms centres; no resampling/interpolation/padding.

Additionally sum standard CTC alignments for the canonical target IDs and the
interval's independent greedy-collapsed IDs within the SAME unchanged frame range.
These are exact probabilities of fixed token sequences on that frame set, not
all alternative subword spellings or full mixed RNNT text. Report their log-mass
difference, the existing one-completion context credit and isolated sum, labelled
as a local score diagnostic rather than actual final search counterfactual. Do
not increase credit to turn a failure into a pass. Retain per-frame top1/blank/
target-label scores and occupancy for all original frames, not handpicked crops.

New algorithm controls: small-graph exhaustive state-path enumeration must match
partition, start/end marginals and selected-span mass; fixed-token CTC must match
independent raw-path enumeration including repeated labels. Match saved Viterbi
scores/trace and forward/backward partitions on all10real records. No external
implementation parity or human gold claim. Agentlimits600s/RSS1536MiB/floor2048MiB/
swap256MiB with supervision. Existing private cumulative HTML includes all11rows.
Verdict: Extend the existing NumPy diagnostic style and reuse supervisor; no new
model or dependency. Do not recompute consumed round13 occurrence experiments.

### Round17 observed result
Runtime108e963,manifest-round17.json,job2255exit0collected. All10records/11phrases
complete. Viterbi traces10/10exact,scoreerror0;maximum forward/backward partition
error1.4210854715202004e-14. Three complete-state-path enumeration cases(21/6/7paths)
and five raw-CTC cases(81paths each) pass,maxerror2.220446049250313e-16. The shared
supervisor gained only optionalworker_script; originaldefault preserved.

Selected-span mass min0.0763121563/median0.1465657147/max0.4049344540. All11have
trailingblank-topframes. Equal-cost trailingblank ownership between phrase and
gap makes boundary mass diffuse even without missed speech; do not treat lowspan
mass as proof of wrong timing or use quantile bounds as a new route. c009GitHub
native42–44 length3=min3,conditionalstartmode42mass0.4331,previous41mass0.4080;
endmode47mass0.3197. SameintervalcanonicalCTClogmass−17.967507 vs greedy−2.883917;
netdifference−15.083589+12.5=−2.583589. Genuine local acoustic deficit despitebias,
not proof of fullmixedsearchcause/righttiming. c022start59mass0.97318, enddiffuse
throughblankplateau; no independent RU emission localization or duplicatecause.

Nineof11canonicaltargetmassesbelowgreedy;onlyc009stillbelowafterexistingcredit.
Newmechanicalfinding c005GPT: canonicalIDs[41,287] vs greedy[41,1015,998] render
identically, but credits10vs0. CurrentcontextmatchesoneSPEsequence,notspelling.
Keep this distinct from pronunciation/spelling errors and language selection;
no character matcher or new decoder run claimed this round.

Hostworker0.274404s/supervised0.602350s,highwater42.734375MiB,
sampled42.882813MiB,minavailable8930.734375MiB,swap0. NumPyretaineddata-only;
newmodelcalls0,newtranscripts0,gold0. boundary_report.py records all11rows and
all originalframes privately; production/routesunchanged. Goal remainsunmet.

Nextnotfrozen: segmentation-invariant spelling context on unchangedintervals,
rewarding equal spelling equally regardless of trained subword segmentation.
Must keep total completion credit fixed per original phrase (avoid accidental
per-character bonus increase), no newnames/aliases/Qwenchanges; openalltrainedIDs,
actualacousticpiecesandcreditpartitions retained. Empty/partial/wrong/outside
spelling must refund; punctuation/boundaries explicit. Compare all10routes rather
than justc005. This addresses representation bias, not QwenGSH/Latinization truth.

## Round18 — spelling-invariant interval context, unchanged full credit

Add opt-in `auxiliary-spelling-interval-v1`. Keep all10round16routes/11unaltered
Qwen phrases, native events, open trained vocabularies, RUbeam4/history and score2.5.
No new acoustic/Qwen passes or post-edit, no route change/manualnames. Context
reads the characters actually emitted by trained subword tokens; output remains
those exact tokens. Reuse the boundary convention from ctc_occurrence: SentencePiece
marker/whitespace/punctuation(PZS except apostrophe) become context-only BOUNDARY.
No case rewrite, alias, transliteration or approximate spelling match.

For each phrase the one-completion budget is EXACTLY its previous canonical
context-symbol count times2.5. Match an entire normalized spelling with left/right
word boundaries. Borrow/refund credit for partial prefix as before. To avoid float
state-key drift, allocate integer units along the spelling path: both outer
boundaries get1unit; the remaining originalunits are distributed by cumulative
floor(k*interiorunits/interiorcharacters). Each unit pays2.5. Thus equal emitted
character prefixes have identical state/credit regardless of subword segmentation;
no per-character bonus inflation, fractions or arbitrary coefficient search.
Partial-prefix credit shape necessarily differs from token matching; search/pruning
may change independently of the winning spelling. Repeated/overlapping matches
retain existing covered-symbol semantics using position-specific integer weights;
shared covered symbols do not earn another award. No one-match cap is introduced.

Extend the existing single-pattern ContextBias machinery in a small subclass;
retain old global and token-interval branches. Cache reuse requires the new mode,
same score and identical phrases/routes. Different timing credits still partition
search states/final retained alternatives; do not claim full posterior. Exact
bonus2.5 is required for this first mode, whose integer2.5 units are binary-exact.

Before corpus, compare all chunkings of small spellings and their every common
prefix, mismatch/partial/EOS refunds, whole-word containment, punctuation, repeated
matches, cross-interval reset, weak hint loss in tiny open search, and the actual
c005twoGPTtokenizations receiving the same10credit. Check each of11phrasecompletion
budgets against the retained round16graph. These algorithm controls are not new
speech references, full decoder parity or a replay of old experiments.

One final decode per10existingroutes, oldresults preserved. Frozen source/manifest
and600s/cell,900s/batch,RSS1536MiB/floor2048MiB/swap256MiB agent limits. Report all10
texts/tokenpaths/RUchanges/credits/resources, including known QwenGSH/Latinization
regressions. Improvement not inferred from more proposal agreement. Training,
waveform padding/segmentation, production switch and external audio remain excluded.
