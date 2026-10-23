# R76: repair missed profanity without free-form content deletion

## Request and baseline

The owner requested an actual fix after R75 reproduced incomplete profanity cleanup. This authorizes implementation, bounded fresh verification, deployment and publication, not only another evaluation. Base: `3a851f6d6c64861d510ed268ccb303b44f125e61`. R74's rejected exhaustive prompt must not be reactivated. Private real transcripts and exact outputs remain outside this public repository.

## Intended result

The experimental smart editor must remove supported expressive profanity even when the model leaves it unchanged. It must not accept arbitrary loss of instructions, quoted text or factual wording. Preserve the selected FrogNano model, Mac prompt/runtime, authentication, request budget and one-call transport. Default/raw, dictionary/ASR/Loqira, Kodak, TTS and Clef remain unchanged. Any service/protocol/identity/validation failure still returns the exact accepted post-cleanup source, without local cleanup on that failure.

## Approach and limits

Replace unconstrained use of generated prose with a finite source-span renderer inside the FrogNano client. Inventory explicit profanity/interjections outside quote/code/path/URL, literal-mention and ambiguous contexts. Do not adopt historical adjective candidates because their literal meaning is not decidable locally. Model output may keep or delete only locally inventoried spans, checked by bounded prefix-position matching rather than backtracking or word-level subsequences; all other source words, their order and punctuation are copied from the source. Supported unambiguous profanity is cleaned deterministically after a valid response, including when native output is unchanged. Any neutral replacement must be explicit and retain its predicate rather than silently dropping it (for example, an expressive exhaustion verb). Do not add generic suffix matching, arbitrary word deletion or a second model call. Coverage is deliberately finite, not a guarantee for all Russian slang or interpretation of corrupted ASR.

Exact implementation details remain subject to source review and tests. Prefer the existing quote/span machinery where appropriate, without installing historical rejected editors as the gateway default. Any new production helper must be included in deployment and verified by hash. Metadata must distinguish unchanged text from an applied edit.

## Verification

- Offline red/green against retained private R75 response bytes: no new native replay of these texts. Evaluate cleanup separately from semantic uncertainty in corrupted source.
- Public synthetic regression tests: multiple interjections, repeated curses, expressive exhaustion versus deleted factual predicate, substantive instruction loss, protected/nested/unbalanced quotes, literal word mentions, technical strings, negations/conditions/numbers/names, meaningful punctuation, empty/all-profanity source, malformed model/protocol/timeout and no retries.
- Existing service/client/gateway suites in normal and optimized Python. Installed Deck ASGI/multipart with actual configuration and injected unavailable transport; default/raw make zero editor calls.
- Fresh native acceptance only after complete admission: at most two distinct synthetic requests, unchanged Mac service/model/profile, <=5 minutes after readiness (agent-selected iteration bound). One emotional case and one protected-quote/instruction control. Each gets an exclusive intent and at most one HTTP call. Unknown outcomes are collected, never repeated. No acoustic ASR rerun, owner-PC access, Telegram, unrelated kills or model/dependency changes.
- Deploy only committed/pushed source fetched by exact SHA. Restart only the affected gateway; verify public readiness, installed helper/client hashes, protected speech service PIDs, Mac settlement/preservation and exact fallback.
- Review the task diff and publish a separate checkpoint branch. Report tested coverage and limitations; no universal semantic-safety claim.
