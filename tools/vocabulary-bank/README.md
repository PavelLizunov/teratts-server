# Local vocabulary candidate bank

Source-only backup of the private Model Forge collector, not a TTS-engine dependency. Python stdlib SQLite, no model calls, network lookups, automatic corrections, lexicon writes or training. Speech Front unchanged. Do not commit private DB, results/transcripts, real audio or source IDs.

Run tests:

```sh
PYTHONPATH=tools/stt-dictionary python3 -m unittest discover -s tools/vocabulary-bank/tests -v
```

Collector reads bounded sample.json metadata from existing TAR corpus, stores normalized terms, original surfaces/counts, source/stage and disputed primary/teacher spans. Three user-confirmed vocabulary seeds: Omarchy, Steam Deck, Bonsai. Model suggestions and occurrences never inherit human confirmation. Ordinary observed words are inventory, not asserted named entities. Newest unprocessed sources first; stable source identity prevents repeated import inflation.

Deployment-specific unit/timer templates are under deploy/. Timer every 10–12 minutes, nice 19 / idle I/O / CPUWeight=1 / 128 MiB. Skip recent archive activity or busy nonblocking corpus lock. Up to 25 metadata records, 4096 chars/1000 tokens per stage, soft batch work target 0.2 sec. No restart of existing speech/DSH services required. Historical backfill can be delayed by continuous activity/new sources.

DB and DELETE rollback journal live inside the same corpus root and count against its existing 50 GB logical byte quota. 2 GB DB ceiling is internal, not extra. Reserve current DB-size rollback journal + 16 MiB under flock, enforce max ~4 MiB page growth per batch; skip on headroom failure. Unknown/symlink/hardlink entries rejected. DB 0600, no WAL/second spool. DB history may survive source expiration; missing references remain a limit.

Observed live acceptance: 490 terms / 810 observation rows / 29 disputes, 360,448-byte DB, three confirmed seeds; quick_check ok, unchanged gateway/model PIDs. Nine unit tests passed.

Separate synthetic worker capacity smoke: 1,000,003 terms, 1,000,000 observations, 321,970,176-byte DB, 12.43 s construction, one indexed lookup 0.181 ms, integrity_check ok. Synthetic test NEVER fed into production dictionary. This checks storage capacity, not complex aggregate query performance, long soak or real-word quality.

## Private feedback page

`vocabulary_review.py` + `review-ui/` implement a real plain HTML review page using the existing vocabulary DB. A separate deploy/vocabulary-review.service binds only to a configured Tailnet address. Live search/pages/filters, paired disputed spans, full context and original WAV when retained. Explicit confirm/reject/skip/custom decisions persist in append-only feedback, same quota/lock; dispute choice does not approve a vocabulary term or training. Seed insertion no longer overrides a user's rejection.

Security boundary: trusted Tailnet peers, exact Host and same-origin Origin/per-start CSRF, no CORS/public wildcard/Funnel/per-user login. Eight concurrent handlers, capped request body, strict source sample IDs, DB/journal/symlink/hardlink checks and shared storage headroom. Original audio is fetched, not synthesized. Private browser/DB content excluded from repo.

Live acceptance: 975 terms/1601 observations/39 disputes. Sixteen Python tests passed; isolated Chromium live search/tab/audio and synthetic-only persistent save/reload passed, original WAV metadata loaded; mobile 390 px no horizontal overflow and text escaping/pageerror checks passed. Rapid-query race found/fixed. Synthetic term/feedback removed, actual candidates not approved by tests. No independent model-family review, user-device reachability or million-query UI soak; documented limits. Working link/report remain in private Model Forge docs/vocabulary-review.md.

### Conservative dispute alignment

After a user report of different sentence positions paired as words, review now displays full paired sentences and exact code-point highlights. Fragment choice requires a unique ordered diff block with nearby matching anchors and no obvious moved-word evidence. Repetition/large divergence/missing context falls back to sentence choice or skip. This is textual heuristic correspondence, NOT acoustic timestamps. Server rejects fragment decisions on uncertain pairs. New decisions retain scope/text/alignment snapshot; previous feedback is preserved, not reinterpreted. Live 39 cards: 31 contextual fragment / 8 sentence fallback; 18 tests and live Chromium highlight/fallback/mobile checks passed. Only review service redeployed, inference unchanged.

### GitHub occurrence evidence review

Dedicated /github view indexes saved original STT raw text and existing teacher records, not corrected output. Broad variants (гитха/gethab/git hub/gitab/hub git/Git/GitLab-like) are candidates only. Full codepoint-highlighted sentence, provenance/stage and original audio; per-occurrence yes/no/unsure/custom feedback snapshot. It NEVER promotes an occurrence into a global replacement alias, especially Git/GitLab. Current narrow live spelling rule remains unchanged.

Name documents/mentions/scan markers share the bank quota/guards. Historical already-imported sources independently audited, idempotent; future timer scans continue. Canonical detector/private API now also exposes /omarchy, /plugins and /opening (canonical Смотри). Default-wide candidate inventory is not a forced replacement: plugin inflections, merch and Maria may be legitimate words, each requires occurrence review. URL/code protected; bounded 32 KiB text/100 mentions, heuristic detection may miss unrelated-looking errors. No acoustic timestamps or cloud inference.

Live audit: all 3159 current archives examined, 591 STT records, 34 candidates across 11 raw STT documents and 14 case-preserved surfaces. Twenty-three tests passed, browser deep link/real ambiguity/search/mobile and synthetic-only persistent live save verified; fixture removed, prior 39 feedback preserved. Native voice service PIDs unchanged. Private source text/audio/DB/screenshots excluded from Git backup.

Personal v2 queue audit: all existing sources versioned at final snapshot, Omarchy 12 mentions / plugins 34 / opening 37 (32 Ну,4 Смотри,1 Мария), prior 73 feedback decisions preserved. Six name tests + 18 bank/review passed; live mobile deep links/cards and explicit synthetic controls verified. Omarchy/cleanup native spelling integration is separately documented under tools/stt-dictionary, not enabled by evidence decisions. Maria never automatically becomes smotri.

### Developer/Git and Linux topical review

New /development and /linux topics use 32 curated development and 42 Linux term groups, detection only. Exact/transliterated/inflected names and bounded near-match on long distinctive names; no short-command fuzzy guesses. Phrase matches preferred over single-word overlaps. Protected URLs/code and unrelated пуля/пульт/пульс/controller are not forced into pull/contributor.

Topic cards show exact suggestions (pull vs pool), original-as-heard, not-technical, unsure and custom spelling. Server rejects generic yes-to-topic; exact chosen value is stored with occurrence snapshot. No active dictionary/inference changes or cloud calls. Inflected Russian speech may correctly stay Russian, not forced into English base form. Full acoustic alignment unavailable.

Final audit: all 5664 archives current-version scanned,892 STT records, Development91 mentions in59 raw documents/Linux15 in15 documents,98 feedback preserved. Twenty-nine tests passed, live Chromium distinct pull/pool/search/mobile/JS and synthetic-only exact pull decision+reload+cleanup verified. Main voice PID1996400 unchanged, review-only deployment. Private docs in Model Forge docs/developer-linux-review.md.

### Opening feedback intent repair

Previous opening UI generic yes falsely suggested that every Ну meant Смотри. User clarified intent. Append-only repair_opening_intent.py supersedes only latest yes-on-Ну with explicit custom Ну, retains originals and skips no/unsure/custom/later human decisions. Five repaired, second run zero, original five audit rows retained. New buttons distinguish Ну, Смотри and suspected Maria; server refuses generic yes for opening queue. No raw speech correction or cleanup activation follows from these feedback changes. Two dedicated tests plus regressions/live mobile labels verified. No private feedback IDs/content in source backup.

### Audio decisions and visible active rules

Every feedback click pauses/resets that card's real WAV before POST; failed save never resumes, tab/list replacement also pauses. Raw surface/context stays immutable. Review uses shared stt-dictionary module (same runtime directory on Deck, PYTHONPATH above in source backup) to show current-rule preview and active plugin banner; historical final displayed separately. Known standard plugin forms no longer ask users to reapprove an active normalization alias. Browser actual playback tested success/503/tab pause/reset, no real feedback insertion; preview!=raw test and mobile no errors passed.

Installed NeMo-Speech.cpp0.1.0 docs explicitly say Parakeet TDTv3 has no word boosting. Nemotron3.5 is multilingual ru+context candidate, not migrated/downloaded/tested here. See private Model Forge docs/review-audio-chatgpt-asr-context.md.

### Conservative duplicate review grouping

View-only review_groups.py groups same-audio/canonical/full-normalized-token-text/token-position/surface stage copies. Different samples, repeated token positions, distinct transcripts and absent sample IDs do not merge. Raw primary preferred, all member stages/IDs retained. Consistent previous decisions hide group; conflicting history explicitly pending. New choices append member decisions with group snapshot; revision includes membership/current decisions, stale groups rejected. Max5000-row window explicit, not unlimited UI-load proof.

Development exact-occurrence GitHub/plugin duplicates routed to respective queues; no evidence deletion. Live91->27cards (63 specialized routed,1stagecopymerged),pending12,all250previousfeedbackretained. Thirty-seven tests passed, synthetic two-member live save/hide+cleanup,Chromium groupedprovenance/mobile/noerrors;STT/gatewayunchanged. Real repeated word in different recordings still needs separate review if context differs. Full private docs/review-deduplication.md.

### Nemotron / Parakeet human comparison

Private /nemotron page imports verified full-run summary SHA into949unique-audio rows,not951duplicate-sourcecards. Default20diagnosticrecords:8variedcandidateempty,1reverseempty,8technicalsubstantialdifferences,3nonemptyagreementcontrols. Filters priority/empty34/technical120/full949,search/pagination/pending. Human preference Parakeet/Nemotron/bothbad/equivalent/unsure/customwholetext persists with both model outputs/samplehash/modelmanifest provenance;human_gold=false/training_approved=false,model never switched.

Frozen private WAV retrieval strictSHA/owner/nosymlink/hash/size,not arbitrary paths and no synthesis/inference. Samequota/flock/CSRFguards. Completedimport949/repeat0;old250feedbackpreserved. Fourcomparison tests plus regressions=41backup tests passed. Live Chromiumallfilters,next/back/audio-stop/mobile/JS,allfivechoices+custom saved on single syntheticrow and reloaded;rowand6testvotesremoved. SourceDB/rawresults/WAV/screenshotsnotGit. Review-onlydeployment. Private ModelForge docs/nemotron-comparison-review.md.

### Blind randomized comparison

Current /blind page displays Model1/Model2 only; old /nemotron page/API is a blind compatibility alias. Balanced random per-card assignment+opaque token/display order persisted server-side,stable across reload/filter/restart. Public JSON uses option1_text/option2_text,neutral categories/stats,no primary/candidate identities,model/audio hashes/sourceIDs/mapping. Opaque audio path;old explicit SHAaudio routeclosed. Mapping/privateauditDB not published or committed.

New blind_comparison feedback uses option1/option2 and private resolved-choice snapshot,never exposes model on save. Old nonblind preferences preserved separately and not mixed/prefilled. Fourblind tests plus fullbackup suite45passed,liveChromiumneutralbody/API+legacyalias/stablereload/realAudioStop/mobile0errors;syntheticreverseorientationrealvote resolved correctly,reloadedhide,fixture+testvoteremoved. Previous250feedback unchanged,949real assignmentsstable. Diagnostic20selection/previous exposure/style clues remain biases;this is voluntaryblindUI not protection from privilegedDBowner or populationaccuracy proof. Private operatingdoc ModelForge docs/blind-model-comparison.md.

### Longer unseen blind challenge set

First20blindvotes completed;16wereunder3s,so userfoundthemtootrivial. New immutable set long-content-v1 selects30previouslyunreviewed nonemptyclips with>=12tokens each and>=3tokendifferences,duration5–40s,notpunctuationonly/nearidentical,duplicatebaselinetextexcluded.15technical/6number-negation/9otherlexicaldifferences,actual7.637–31.359s,median17.386,total547.565s. Balancedexistingorientation,all949mapping/old20votespreserved. Diagnosticbiasedselectionnotgeneralqualityscore,winnersremainhidden.

challengefilternewdefault;priorityfirst20retained,noreset. Neutral selection reasons/noidentityfields. Threeadditionaltests+fullsuite48passed,liveChromiumchallenge30/page2/oldpending0/stablereload/noerrors/mobileoverflowfixed. No extra inference/STTrestart. Private membership notGit;source-only selector/guardinstallerbackedup. Full private docs/blind-challenge-set.md.

No million-word prompt: future hints must be bounded to relevant terms. No mass dictionary download or filler creation. The full private operating report stays in Model Forge docs/vocabulary-bank.md, outside this repository.
