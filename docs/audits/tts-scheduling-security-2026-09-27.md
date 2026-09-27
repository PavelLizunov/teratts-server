# TTS scheduling differential security review

## Scope and status
In-session review, not independent acceptance. Base: a3bdbf29a840a30928cf6be03394943853a99530. Reviewed task-owned working-tree changes to dsh-plugin/lib/{index,coordinator,client}.js, related tests and README. Rust inference, model files, credentials, live deployment and DSH core are unchanged. Final snapshot/commit will be recorded in the task specification after verification.

## Trust boundaries checked
- Browser -> authenticated Host Remote -> foreground lease coordinator: newly exposed acquire/renew/release methods match browser schema. Acquisition accepts only nonempty <=256-character owner strings and nonnegative safe-integer epochs. Registry holds at most 32 owners; 15-second expiry and disposal clean timers. Client instance identities avoid cross-tab message-id collisions. These are scheduling hints within one trusted user's Host, not a new authentication mechanism.
- Host settings -> synthesis/metadata network requests: existing endpoint allowlist remains; metadata now validates before network access and refuses redirects. Revision cache/in-flight results are endpoint-scoped. No token is placed in browser state or new logs.
- Backend -> error/retry handling: error bodies are capped at 4096 bytes and cancelled on excess. Logs omit raw bodies/URLs/transport causes in changed synthesis branches. Unknown-outcome failures do not automatically resubmit native inference. Only explicit admission rejection can retry.
- Cancellation -> shared work: callers can cancel their wait without cancelling another consumer. Already admitted fragment drains under its existing request timeout. New speculation remains excluded while it drains. Transport abort is never presented as confirmed native termination.
- Configuration change -> cache and sharing: cache generation gates writes, pending dispatch and promotion. Foreground dedup keys include generation; late pre-reset results cannot populate post-reset cache or be joined by a new admission.

## Findings addressed in this change
1. Availability: failed speculative candidate remained queued and was dispatched repeatedly. Confirmed by bounded failing regression; finally now consumes only the dispatched candidate identity.
2. Availability: expired leases were never purged or woken; missing RPC markers prevented client leases from being honored. Confirmed by clock tests and installed-runtime Remote marker test.
3. Availability/correctness: preparation eviction retained rejected promises and synchronous throw bypassed registry initialization. Confirmed locally; cleanup is separated from slot ownership and disposal rejects waiters.
4. Availability: repeated inference after ambiguous network/502/504 failure. Confirmed by mocked actual service transport calls; retries narrowed and outcome classification preserved.
5. Correctness: revision cache crossed endpoints; cold prefetch used unknown key; old settings generations could share/cache work. Regression coverage now checks endpoint identity, preflight, new turns, invalidation and foreground generation.

No unresolved high-severity regression was found in the reviewed paths. This is not a whole-system security certification.

## History inspected
`git log -4 --oneline -- dsh-plugin/lib/coordinator.js`, `git blame -L 300,338 HEAD -- dsh-plugin/lib/coordinator.js`, and `git log -S 'Remote("synthesize")' --oneline -- dsh-plugin/lib/index.js`. Relevant prior commits: 9d5f447 (initial leases), 54955ce (multi-session coordinator), fd9e040 (prepare dedup). Existing unknown-outcome suspension policy was retained rather than silently weakening it.

## Verification and limits
- Benign isolated Node tests use installed DSH dependencies but never mount live services; all fetch/inference fault injections are mocked.
- Latest suite at this review step: 120 passing tests; `git diff --check` clean. Tests include real runtime method registration, bounded lease registry, epoch/expiry/disposal, duplicate synthesis, cancellation, queue cleanup, retry classification and bounded response logging.
- Independent review route is not authorized by the current tool catalog: native subagents inherit Astra, and workflow delegation was not explicitly requested. Self-review is explicitly not independent acceptance.
- No live browser/Host activation test, native-inference cancellation test, or authenticated production synthesis was run. No restarts, credential changes, public exposure or model changes.
- Existing metadata JSON response decoding is timeout-bounded but not byte-capped; only trusted allowlisted endpoints are supported. This preexisting resource-hardening limit is not claimed fixed.
- Foreground leases are advisory, not owner authorization between mutually hostile users. A trusted client could intentionally renew its own lease and suppress speculation. Manual requests remain available.
- Already-running unrelated speculation is not preempted. Unknown-outcome suspension needs an administrative reset/new coordinator. Cross-Host/external-client scheduling is outside this coordinator's scope.
