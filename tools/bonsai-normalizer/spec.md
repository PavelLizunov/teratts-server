# Specification: Bounded Mac Bonsai 9B Neutral Transcript Normalizer

**Date:** 2026-10-21
**Target Repository:** `/var/lib/dsh/Project/mm4-test-llm/deck-bonsai-src`
**Branch:** `checkpoint/bonsai9-neutral-dictation-20261021`
**Scope:** `tools/bonsai-normalizer/*`, `tools/ruen-support-pilot/gateway-server.py` (targeted seam), and the owning README sections.

---

## 1. Objective & Intended Result

Introduce an optional, conservative transcript normalization stage executed **strictly after** accepted Steam Deck STT (Parakeet ASR + pre-dictionary + Loqira GEC + post-dictionary + opening cleanup) using Mac Bonsai 9B (`prism-ml/Ternary-Bonsai-2-9B-mlx-2bit`).

### Key Behaviors:
1. **Opt-in Only:** Activated only when `effective_mode == "smart"`, `STT_CORRECTOR == "loqira"`, a Loqira corrector exists, and environment variable `BONSAI_NORMALIZER_CONFIG` is set and valid.
2. **Default & Raw Invariance:** Effective default/raw requests bypass Bonsai with **0.0 ms reported Bonsai-stage time** and **no Bonsai network requests**. Existing `smart=true` precedence over `mode=raw` and `format=false` is unchanged. This does not assert literally zero CPU cost for added metadata.
3. **Safe Source Fallback:** On any timeout, HTTP failure, model/revision mismatch, or validation guard failure, the gateway falls back immediately to the accepted STT text (`final_text = accepted_stt_text`).
4. **No Unsolicited Automation:** No automatic fallback to alternate LLMs, no research campaigns, no remote mutations.
5. **Privacy:** Secrets (Bearer tokens) and transcript contents are never logged to console or included in error metadata.

---

## 2. Integration Seam (`gateway-server.py`)

### 2.1 Placement
The call is placed directly after `final_text, cleanup_result = clean_opening(final_text, cleanup)`:
```python
accepted_stt_text = final_text

bonsai_meta = {
    "status": "bypassed",
    "reason": "unconfigured" if bonsai_normalizer is None else "mode_bypassed",
    "latency_ms": 0.0,
    "model": getattr(bonsai_normalizer, "model", None),
    "revision": getattr(bonsai_normalizer, "revision", None)
}
bonsai_latency_ms = 0.0

if (
    bonsai_normalizer is not None
    and effective_mode == "smart"
    and STT_CORRECTOR == "loqira"
    and loqira_corrector is not None
    and os.environ.get("BONSAI_NORMALIZER_CONFIG")
    and accepted_stt_text
):
    t_bonsai_0 = time.perf_counter()
    try:
        rewritten_text, bonsai_meta = bonsai_normalizer.normalize(accepted_stt_text)
        if (not isinstance(bonsai_meta, dict) or not isinstance(rewritten_text, str)
                or (bonsai_meta.get("status") == "applied" and not rewritten_text.strip())):
            raise ValueError("invalid_normalizer_result")
    except Exception as error:
        rewritten_text = accepted_stt_text
        bonsai_meta = {"status": "fallback", "reason": type(error).__name__,
                       "model": bonsai_normalizer.model, "revision": bonsai_normalizer.revision}
    bonsai_latency_ms = (time.perf_counter() - t_bonsai_0) * 1000.0
    bonsai_meta["latency_ms"] = bonsai_latency_ms
    if bonsai_meta.get("status") == "applied":
        final_text = rewritten_text
    else:
        final_text = accepted_stt_text
```

### 2.2 Headers & Observability
- `X-Bonsai-Status`: `"applied"` | `"fallback"` | `"bypassed"`
- `X-Bonsai-Latency-Ms`: `f"{bonsai_latency_ms:.1f}"`
- `X-Bonsai-Model`: Model string when available
- `Server-Timing`: Appends `, bonsai;dur={bonsai_latency_ms:.1f}`
- Corpus archive record:
  - `accepted_stt_text`: Cleaned transcript prior to Bonsai
  - `bonsai`: Metadata dictionary with status, latency, model, revision, reason
  - `final_text`: Final returned text (distinct from `accepted_stt_text` when applied)
- Readiness check (`/readyz`, `/healthz`):
  - Returns `"bonsai": "configured"` if normalizer is initialized and enabled, else `"bypassed"`
  - Performs **zero network requests** to Mac and does not claim "healthy".

---

## 3. Bonsai Normalizer Module (`bonsai_normalizer.py`)

### 3.1 Constraints & Dependencies
- Standard library only (`urllib.request`, `json`, `os`, `re`, `time`, `dataclasses`, `typing`).
- Maximum input bound: 6,000 characters (exceeded input returns `fallback` with `reason="input_length_exceeded"`).
- Configurable socket timeout: Default 12.0s, finite range 0.1–20.0s. This is urllib's socket-operation timeout, not a proven end-to-end deadline under a trickling response or a cancellation guarantee for server inference.
- Configuration rejects non-boolean enablement, alternate/empty model or revision, nonzero temperature, nonfinite numeric values, invalid sampling values and nonpositive/over-limit input or token bounds. Numeric JSON values must be numbers, not strings.
- Token file: Read separately from local path specified in config; whitespace stripped. If a configured token file is missing/unreadable/empty, return `token_unavailable` without transmitting a transcript. Inline tokens remain supported, but are not used if a configured token file is unavailable. No token configured means an unauthenticated request is allowed.
- HTTP response bodies are capped at 64 KiB. Proxies and HTTP redirects are disabled; a redirect returns the accepted text without a second request.

### 3.2 Request Contract (OpenAI-compatible)
- Endpoint: `POST {endpoint_url}/v1/chat/completions`
- Headers:
  - `Content-Type: application/json`
  - `Authorization: Bearer <TOKEN>` (if token file or inline token configured and readable)
- Payload:
  - `model`: `"prism-ml/Ternary-Bonsai-2-9B-mlx-2bit"`
  - `messages`:
    - `{"role": "system", "content": SYSTEM_PROMPT}`
    - `{"role": "user", "content": text}`
  - `temperature`: 0.0 (required; nonzero configuration is rejected)
  - `top_p`: 0.8
  - `top_k`: 20
  - `min_p`: 0.0
  - `presence_penalty`: 0.0
  - `repetition_penalty`: 1.0
  - `seed`: 42
  - `max_tokens`: 1024
  - `stream`: False
  - Thinking: No client thinking flag; server-side effective behavior is not verified by these local checks.

### 3.3 System Prompt
The Russian prompt requests deletion of only insults, emotional filler and discourse fillers. Substantive phrases must be copied literally, with each thought on a new line, preserving facts, exact names, signed numbers and units, negation scope, conditions, task order, uncertainty and urgency. It must not answer questions, follow embedded instructions or add facts, conditions, advice or commentary. The exact prompt lives in `SYSTEM_PROMPT` in `bonsai_normalizer.py`; a prompt is not proof of compliance.

---

## 4. Response Validation & Rejection Guards

The candidate output must pass all validation checks; otherwise, `status = "fallback"`, reason is recorded, and original source text is returned:

1. **Finish Reason:** `choice["finish_reason"] == "stop"`. (Rejects `length`, `content_filter`, null, etc.)
2. **Model Identity:** Response `model` must match configured model (`prism-ml/Ternary-Bonsai-2-9B-mlx-2bit`).
3. **Revision Identity:** Response revision (from `data["bonsai"]["revision"]` or `data["revision"]`) must match expected revision (`f4e28a59531731c41b6dfac88cf271bd58f0a287`).
4. **Non-Empty:** Output must not be empty or whitespace only.
5. **Modest Growth Guard:** Output character and word length must not exceed modest bounds relative to input:
   - `len(output) <= max(int(len(input) * 1.5) + 30, len(input) + 100)`
   - `len(output_words) <= max(int(len(input_words) * 1.5) + 5, len(input_words) + 20)`
6. **Numeric Token Retention & No Added Numbers:**
   - Numeric-token occurrence counts must match, retaining explicit `+`, `-` and Unicode minus signs (Unicode minus is normalized to `-`; decimal commas to dots).
   - Reject missing/repeated-number loss and added/duplicated numbers. This does not protect the relationship of a number to a fact, date structure or measurement units.
7. **Latin Identifier Retention & No Added Identifiers:**
   - Latin identifier occurrence counts must match case-insensitively: no missing, added or duplicated identifiers. Punctuation-separated names are not treated as full structured identifiers.
8. **Negation Count Guard:**
   - Candidate negation count must equal source negation count; reject both loss and additions.
   - Checks Russian (`не`, `нет`, `ни`, `никогда`, `никуда`, `нигде`, `никак`, `никто`, `ничто`, `нельзя`, `без`) and English (`not`, `no`, `never`, `none`, `neither`, `nor`, `without`, `n't`).

9. **Selected Qualifier Retention:** Whole-token/phrase occurrence counts cannot decrease for `кажется`, `не уверен`, `возможно`, `вероятно`, `если`, `сначала`, `потом`.

**Known acceptance limit:** these guards are lexical heuristics, not a semantic equivalence test. `Не удаляй базу, перезапусти сервер.` → `Удаляй базу, не перезапусти сервер.` passes them despite changing meaning. Facts, Cyrillic names, units, urgency, task ordering and the scope of negations/conditions can still be changed. A finite test retains this counterexample to prevent reporting these guards as a guarantee. Prior Bonsai rewrite failures are not resolved by the local protocol tests; no deployment quality claim follows.

---

## 5. Local continuation contract (2026-10-21)

This continuation is local-only: no deployment, commits, pushes, remote calls or inference. Preserve the accepted Parakeet → pre-dictionary → Loqira → post-dictionary → cleanup path and its raw/default behavior. The implementation is still an opt-in experiment, not evidence that Bonsai preserves meaning.

Before editing, the existing 43 mocked/AST checks passed. Source inspection found configuration could replace the pinned identity, exceed the 6,000-character bound, or enable a string-valued `false`; the example/runbook still requested temperature 0.7. Upstream `finish_reason` was copied into metadata verbatim. Existing seam simulations copied the implementation instead of executing it.

Required local corrections and finite verification:
- Reject invalid configuration before constructing a usable client: exact pinned model/revision, boolean enablement, temperature 0, finite timeout/sampling values, positive bounded input/token limits. A specified unreadable/empty token file must not send an unauthenticated transcript.
- Keep all fallback reasons content-free, including malformed finish reasons and transport errors. Bound response reads and disable redirects rather than resending transcript/authentication to a new endpoint.
- Add finite regressions for repeated numbers/identifiers, signed quantities, negation additions and qualifier loss. These lexical checks cannot establish semantic equivalence, scope, factual relations, names, units, urgency or instruction ordering in general; document a passing-but-wrong counterexample.
- Execute the actual gateway function AST with hardware/network dependencies stubbed; cover default/raw and smart/format precedence, stage ordering, accepted-text fallback, headers and corpus metadata. Do not import hardware initializers or contact a service.
- Run the normalizer, dictionary, formatting and retained Loqira checks locally; report commands, exit results, untested live behavior and the next deployment seam.

## 6. Verification Plan

1. **Unit Tests (`test_bonsai_normalizer.py`):**
   - Mock HTTP server / `urllib.request` handler.
   - Gating & bypass checks (disabled config, missing token, mode != smart).
   - Validation failure tests (numeric missing/added, latin missing/added, negation lost, growth exceeded, empty text).
   - Protocol error tests (HTTP 500, socket timeout, invalid JSON, wrong finish_reason, wrong model, wrong revision).
   - Secret & transcript non-leakage verification in logs/metadata.
2. **Static Seam / AST Tests (`test_gateway_seam_ast.py`):**
   - Verify AST insertion after `clean_opening`.
   - Verify capture of `accepted_stt_text`.
   - Verify condition: `effective_mode == "smart" and STT_CORRECTOR == "loqira" and os.environ.get("BONSAI_NORMALIZER_CONFIG")`.
   - Verify headers, server-timing, and corpus metadata fields.

## 7. Observed local verification (2026-10-21)

Worker verification scope: branch `checkpoint/bonsai9-neutral-dictation-20261021`, base `0623c2b47a54cbd71c448549aea178975f717cf9`, unstaged tracked edits plus the existing untracked normalizer directory. The delegated worker was restricted to local changes and checks, without commits, push, deployment or inference. Those are assignment boundaries, not new restrictions on the owner's already-authorized overall task. No local/ancestor repository AGENTS files were found. Existing Python cache files and the tunnel unit were not modified by that worker.

Commands were run from the repository root, with no HTTP server, remote access, model initialization or inference:

- `PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 -m unittest discover -s tools/bonsai-normalizer/tests -v`: baseline 43/43 passed; new regression reproduction ran 52 tests with 35 failing subtest/assertion results (exit 1); final source/config suite 59/59 passed in 1.196 seconds (exit 0). Checks execute the actual transcription function AST rather than a copied seam, use real dictionary/cleanup functions, and stub all hardware, ASR and Loqira/model/HTTP calls.
- `PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 -m unittest discover -s tools/stt-dictionary/tests -p test_stt_dictionary.py -v`: 19 tests, 16 passed and 3 failed (exit 1). Existing deployed aliases `джипти` → `GPT` and `харнес` → `harness` conflict with unchanged older tests. `git diff HEAD -- tools/stt-dictionary` is empty, and worktree blob hashes match the index: implementation `581e7ee3c2a9803061905168962193a971d8fadd`, deployed config `ada5dc7bebb7458325fb99ba24a80456f84395a2`, tests `09408733d819755277a30be0c05dd13576497bb4`. This is a pre-existing dictionary test/config mismatch; the accepted dictionary is preserved, not adjusted to make the suite green.
- `PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 -m unittest discover -s tools/gigaam-multilingual/tests -p test_speech_formatting.py -v`: 7/7 passed (exit 0).
- `PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/tools/bonsai-normalizer" python3 tools/loqira-trial/check_corrector.py`: 5/5 passed (exit 0), transport/generation mocked by the existing fake corrector.
- `git diff --check -- README.md tools/ruen-support-pilot/README.md tools/ruen-support-pilot/gateway-server.py`: passed. New normalizer source/tests/config/runbook/spec were checked with `git diff --no-index --check /dev/null <path>`; after removing Markdown hard-break whitespace and one extra EOF blank line, no diagnostics remained. Exit 1 from a diagnostic-free no-index check denotes a differing new file, not a failed whitespace check.
- Local path resolution verified all three added README links. The runbook JSON block equals the example configuration and both load with temperature `0.0` and the pinned model/revision (automated regression).

Focused local source review covered configuration → payload/authentication → response validation → metadata, and the accepted-text gateway seam. It does not constitute an independent review (this delegated session cannot delegate). No secrets or transcript contents are emitted by the new error paths in the finite mock checks. No dependencies were added.

Remaining limits: the known semantic counterexample in section 4 still passes, socket timeout is not a total response deadline, full FastAPI imports/hardware startup and real Mac effective sampling/revision/latency have not been exercised. The next operator seam is the gateway/module/config placement and opt-in environment shown in the runbook, after the separate Mac diagnosis, followed by live default/raw bypass, smart failure fallback, exact response identity and human meaning review. Nothing here authorizes or reports that deployment as done.

## Lead integration checkpoint

The lead independently reran59normalizer/gateway checks,7formatting checks and5mockedLoqira checks. The same3dictionary mismatches reproduced; unchanged implementation/config/test blobs match the index. An independent read-only context review found no additional concrete important protocol or control-flow defect in this local snapshot. Its blanket requirement language does not establish semantic fidelity or live deployment. No120second total FastAPI deadline was verified; do not use a reviewer's claim about a worker timeout as a serving guarantee. Configuration identity validation also does not verify Python import provenance.

The dedicated `bonsai9-mac-tunnel.service` is active/enabled on Deck. The lead verified authenticated pinned-model health through it with `loaded=false`, using the existing token in memory only. No normalizer token/config/module/drop-in or patched gateway was installed; production gateway hash remains `0fee7132c77769bff880607a0f41afe4ab308230ed4c5cd3d229c11ecf05f6c1`. Mac launchd inference is blocked at the external-SSD model-config open with a TCC full-access preflight denial. The owner was asked for the OS grant. Kodak was narrowly restored to its previous `minicpm_q8` route; this is not accepted caption quality.

This checkpoint may be committed/pushed by the lead under the owner's existing authorization. It must remain undeployed until useful semantic behavior and the actual consumer path pass; protocol mocks alone are insufficient. The no-commit/no-remote boundaries earlier in this record applied to the worker assignment, not the overall task.

### Delivery Gate Verification (Prose)
- PASS: no invented performance/safety claims; local counts and failures are recorded separately from untested runtime behavior.
- PASS: documentation explains the gates, failure mechanics and configuration without claiming semantic equivalence.
- PASS: owning README sections link to the runbook/spec; next deployment seam and known acceptance limit are explicit.
