# teratts-server

Standalone Rust HTTP/CLI wrapper for the pinned TeraTTSv2 ONNX release.

> Model assets are not distributed here. See `NOTICE.md` before redistribution.

## Commands

```sh
cargo run --release -- --download-models
cargo run --release -- --serve --port 8088
cargo run --release -- --speak "Привет" --voice ru_f1 --output hello.wav
```

Set `TERATTS_MODEL_DIR` or pass `--model-dir PATH` to override the default cache.

## Execution provider (CPU default)

Unset `TERATTS_EXECUTION_PROVIDER` or `cpu` retains CPU inference. Optional CUDA
support is compiled with `cargo build --offline --locked --release --features cuda`;
it does not install ONNX Runtime, CUDA, cuDNN, drivers, or models. The existing
`ort` rc.13 `load-dynamic` / API27 contract is unchanged.

For an **already admitted** GPU candidate, explicitly set
`TERATTS_EXECUTION_PROVIDER=cuda` and `TERATTS_CUDA_MEMORY_LIMIT_MIB` to an integer
in `1..=16384`. There is deliberately no default CUDA budget. Invalid provider,
non-Unicode configuration, missing/invalid CUDA budget, or a build without the
`cuda` feature fails before Tera model loading. The CUDA-only budget is ignored
in CPU mode. CUDA registration failure fails startup, rather than silently
running the requested candidate on CPU. Unsupported graph nodes may still run
on ORT's CPU provider; enabling CUDA does not prove every node executes on GPU.
To select the retained CPU fallback, unset the provider or set `cpu`; CUDA
inference errors/OOM do not automatically retry on CPU.

CUDA applies only to the four Tera sessions, not RUAccent. Each session gets its
own arena limit: budget accounting is **four sessions × engine slots × the
configured MiB**, plus CUDA/cuDNN context, workspace and other allocations outside
those arenas. This is **not a process-wide VRAM cap or an admission check**.
Keep `TERATTS_PARALLEL_CHUNKS=1` for a first candidate. CUDA uses device 0,
`SameAsRequested` arena growth, heuristic convolution selection, restricted
convolution workspace and TF32 disabled; no model conversion or CUDA graph
capture is enabled.

Before any GPU model load, an operator must validate the complete candidate's
peak at the intended input bounds on safely available hardware, add an explicit
reserve for existing workloads, and recheck actual free VRAM (`nvidia-smi
memory.free`). Graph file size is not peak VRAM. Unknown peak means no admission;
this code does not automatically measure, reserve, or prove available capacity.
Do not OOM-probe or change/stop an existing workload to make a candidate fit.

The driver-570-compatible API27 route is Microsoft's explicit
[`onnxruntime-linux-x64-gpu_cuda12-1.27.0.tgz`](https://github.com/microsoft/onnxruntime/releases/tag/v1.27.0)
(CUDA 12 builds are deprecated but published), CUDA 12.8 and compatible cuDNN 9
for CUDA 12. Default ORT 1.27 GPU PyPI/NuGet packages use CUDA 13, which requires a
newer driver; do not substitute them. Pin and verify the runtime archive, select
its `libonnxruntime.so` using `ORT_DYLIB_PATH`, and supply process-private library
paths for its providers, CUDA 12 and cuDNN 9. Check the actual library versions:
`/usr/local/cuda` may point to a different major version. Use explicit paths
without changing global alternatives or other workloads. Inspect loader dependencies/API/provider
availability before model loading. See the [ORT CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
and [cuDNN 9.19 compatibility matrix](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.19.0/reference/support-matrix.html).

Model-free configuration checks (neither command creates an ORT session):

```sh
cargo test --offline --locked --bin teratts-server execution_provider::tests
cargo test --offline --locked --features cuda --bin teratts-server execution_provider::tests
```

## HTTP

```sh
curl http://127.0.0.1:8088/health
curl -o hello.wav http://127.0.0.1:8088/tts \
  -H 'content-type: application/json' \
  -d '{"text":"Привет, это TeraTTSv2.","voice":"ru_f1","duration_scale":1.0}'
```

`POST /tts` returns mono 16-bit PCM WAV at 44.1 kHz. The server serializes
inference because one engine owns the four mutable ONNX Runtime sessions.

## Optional remote primary with retained local fallback

CPU-only serving is unchanged when `TERATTS_PRIMARY_URL` and
`TERATTS_PRIMARY_TOKEN` are both unset. To route through an operator-managed
loopback tunnel, set both before `--serve` startup:

```sh
export TERATTS_PRIMARY_URL=http://127.0.0.1:18089/tts
# Set TERATTS_PRIMARY_TOKEN securely to the candidate's bearer token.
export TERATTS_PRIMARY_TIMEOUT_MS=3000
# Keep the stable local listener and its existing client bearer configuration.
teratts-server --serve --host 127.0.0.1 --port 8088
```

The URL accepts only literal loopback IP addresses over HTTP, exactly `/tts`,
without userinfo, query, fragment, or redirects. Hostnames and noncanonical IPv4
spellings are rejected. Its port must differ from the fixed, nonzero local
listening port (even across loopback address families). Partial/empty/non-Unicode
configuration, a standalone timeout without the URL/token pair, or invalid token
header bytes fail before model access. The optional primary timeout is an integer
in `1..=10000` milliseconds, default **3000**, covering connection, headers, and the
complete body. The pooled client bypasses proxies and disables redirects and
HTTP retries. No endpoint discovery, remote configuration, or service management
is performed.

With routing configured, one **55-second total deadline**, including queue wait,
primary request, and any CPU fallback, replaces the CPU-only 120-second deadline.
Both paths share one admission ticket and active permit. If less than the configured
primary timeout plus a five-second CPU reserve remains, the primary is skipped;
this reserve is not a guarantee that every CPU input finishes within five seconds.
After local authorization
and request validation, the primary receives the **original raw text** and explicit
effective voice, language, duration scale, `speech_front`, and `text_mode`.
`russian_stress` is forwarded only for Russian; English rejects any explicit
stress field, even `false`. No lexicon/normalization/conversion is applied locally
before forwarding. Fallback uses the original local prepared request, not primary
output, and runs the existing preprocessing exactly once.

At most one primary attempt and one local CPU attempt occur. Primary timeout or
transport failure can fall back; known backend JSON codes qualify only as
`500/internal`, `503/queue_timeout`, or `504/deadline_exceeded`. All 4xx (including
400/401/403/429), semantic text/conversion errors even on 5xx, redirects, unknown or
malformed error JSON, oversized/error bodies, and invalid audio fail closed.
429 retry metadata is retained only as bounded numeric `Retry-After` seconds
(1..=60) or JSON `retry_after_ms` (1..=60000); header seconds take precedence.
Error bodies are capped at 4 KiB; upstream messages, input text, and tokens are
never echoed or logged by this routing layer. Once a non-200 status is received,
body read failure/timeout cannot turn that rejection into fallback. Cancellation
and total deadline expiry never start fallback.

Success is returned only after the entire body is buffered and validated:
`audio/wav`, matching `X-Teratts-Text-Mode`, and the pinned encoder's exact 44-byte
RIFF/PCM header, mono 16-bit 44.1 kHz shape, length consistency, and at most
180 seconds (**15,876,044 bytes**, including header). Alternate WAV layouts are
intentionally rejected. No partial audio response is published. Only configured
routing adds `X-Teratts-Backend: primary|cpu` to successful WAV responses, as route
evidence (not proof of CUDA execution). `/health` retains
local CPU/model readiness semantics and adds only `primary_configured`; it does
**not** claim GPU readiness.

**Rollout gates (operator-owned):** prewarm and verify the GPU candidate before
activation: observed cold startup/first inference can exceed 40 seconds, well
above the primary budget. Verify matching models, voices, text mode/converter,
and approved lexicon on both backends. The candidate must have **no**
`TERATTS_PRIMARY_*` configuration, preventing GPU-to-CPU recursion; URL validation
cannot detect a tunnel deliberately pointed back at this server. Set the DSH Host
client's existing `maxRetries` to **0** before activation (its value of 3 would
create nested retries). Keep the stable endpoint and retained CPU assets. This
patch does not change Host configuration, create a tunnel, deploy/restart any
service, or establish a GPU readiness guarantee.

Cancellation is cooperative: dropping the request-owned future or reaching its
deadline sets a shared flag, and checks guard primary dispatch and CPU spawn.
The primary await is inline and is dropped with that future. This is **not** a
guarantee that an HTTP disconnect makes Axum drop the handler, that remote
inference stops, or that native ORT `Session::run` can be interrupted. Once CPU
work starts, its active permit remains held until the blocking worker and all
chunk threads finish/join; the 55-second bound limits the response wait, not
native computation lifetime.

Model-free checks (local mock HTTP only):

```sh
cargo test --offline --locked --bin teratts-server remote_primary::tests
cargo test --offline --locked --bin teratts-server server::tests
```

## Approved speech-front lexicon

`POST /tts` accepts optional `speech_front: true` for the server's Russian
normalizer before RUAccent. In the default `compatible` text mode, omitted/null
uses `TERATTS_SPEECH_FRONT=1` as the server default (otherwise off); explicit
`false` always overrides that default. English requests and explicit `<en>` spans
retain their existing behavior in `compatible` mode.

Unset `TERATTS_LEXICON_PATH` uses the embedded approved lexicon. Set it before
startup to an approved UTF-8 TOML file (maximum 2 MiB) to enable request-time
reloads without rebuilding or restarting for subsequent file updates. An invalid
initial file fails startup; a later invalid/missing file keeps the last valid
snapshot and emits a bounded diagnostic. Off requests do not reload the file.

The review tool and server must share the local file or explicitly synchronize
it: a Git remote update alone does not update a running server. See
[configuration, failure handling, and tests](docs/speech-front-integration.md).
Deployment and the DSH plugin are unchanged.

## Russian-only HTTP mode

`TERATTS_TEXT_MODE=compatible|russian_only` selects the server default; unset means
`compatible`. `POST /tts` accepts optional `text_mode` with those same values;
omitted/null uses the server default. This affects `--serve`, not `--speak`.
Explicit `compatible` retains the existing English pipeline and resources.

Russian-only mode requires an operator-installed, trusted Rust `speech-front`
executable and a prepared local CMUdict database:

```sh
export TERATTS_SPEECH_FRONT_BIN=/absolute/path/to/speech-front
export TERATTS_CMUDICT_PATH=/absolute/path/to/cmudict.sqlite3
export TERATTS_TEXT_MODE=russian_only
# Retain your normal bearer-token and model-directory configuration.
teratts-server --serve --port 8088
```

Both paths must be absolute, existing regular local files, and the binary must be
executable. Set both even with default `compatible` to allow explicit
`russian_only` requests. Partial/invalid configuration fails startup. Before model
verification/loading, the server probes the configured binary and database with
benign stdin `тест`; startup never downloads models or dictionaries. The optional
converter implementation is not linked, copied, or distributed by this public
repository; install an authorized binary separately. No private source dependency
or runtime Python dependency is introduced.

```json
{"text":"<en>Widget</en> и API","text_mode":"russian_only","voice":"ru_f1"}
```

The mode rejects non-Russian voices or `language: "en"` before inference rather
than silently overriding them. The default voice remains `ru_f1`, language `ru`.
Strict, balanced, non-nested `<ru>`/`<en>` tags are flattened to plain text with
word boundaries **before** approved server lexicon/number normalization, including
all former English spans. Unknown/malformed markup returns 400. Before the lexicon
and converter, bounded input-only substitutions speak `→ ⇒` as `переход к`, `← ⇐`
as `стрелка влево`, `↔ ⇔` as `связано с`, and `↑ ↓` as `стрелка вверх/вниз`.
Math `≈ ≤ ≥ ≠ × ÷ ± −` becomes `примерно равно`, `меньше или равно`,
`больше или равно`, `не равно`, `умножить на`, `разделить на`, `плюс минус`,
`минус`, with word boundaries. A Unicode minus immediately before a digit and not
immediately after a letter/digit becomes ASCII `-` instead, preserving signed
number/currency normalization (e.g. `$−5`); ASCII hyphens and `+` stay unchanged.
Em/en dashes become ASCII `-`; curly double/single quotes become ASCII quotes;
`[] {}` become parentheses; newlines, tabs and nonbreaking spaces become ordinary spaces.
The same input-only cleanup runs after server normalization, which can generate
new typographic range dashes.
Only the explicit decorations/list separators `⏵ ✅ • ‣ ▪ ● ◦ · │ ─` become spaces;
no Unicode/emoji ranges are silently deleted. Decoration-only empty text returns 400.
Other unsupported characters, including non-ASCII foreign letters, return 400 before
converter invocation; Russian text, ASCII Latin, supported punctuation and stress
marks remain accepted. This input cleanup also applies with `speech_front: false`;
converter output/traces and strict model checks are not rewritten or relaxed.
Numeric comparison `< >` symbols remain text for conversion. Numeric or space-separated arithmetic `+`
is protected as `плюс` in unmatched gaps before number normalization; approved
lexicon forms/readings always take priority, and Russian stress markers and `C++`
remain intact. Russian-only enables the server normalizer
when `speech_front` is omitted/null, even without `TERATTS_SPEECH_FRONT=1`.
Explicit `speech_front: false` skips lexicon reload and normalization, but **not**
Cyrillic conversion; this is the contract for already-prepared Preview text.
Approved lexicon readings therefore have priority unless the caller explicitly
opts out. Neither request preparation nor conversion writes to the lexicon.

After admission, the existing blocking worker invokes the configured executable
without a shell, passing only `russian-only --cmudict ABS_PATH` as arguments and
text through stdin. Each request incurs process startup/database-open overhead.
The converter must emit exactly one JSON document, no other stdout:

```json
{"text":"кириллический текст","readings":[{"written":"API","text":"эй пи ай","source":"cmudict","warnings":[]}],"warnings":[]}
```

Raw Russian-only requests are limited to 2,400 Unicode characters. Expanded
converter input/output is limited to 12,000 characters; JSON stdout is capped at
256 KiB. The server validates the complete trace shape, nonempty plaintext output,
and absence of Latin/unsupported alphabets or tags. Russian-only engine preparation
also checks the loaded model vocabulary before and after number expansion: any
character that would otherwise be silently filtered (including unexpanded oversized
numbers) rejects the request with static 400 rather than losing text. Compatible
mode retains its original filtering behavior. Conversion has a five-second
deadline, bounded stdin/stdout pipe workers, and discarded stderr. Failure never
falls back to compatible mode: server-side text/markup validation returns 400;
converter rejection/nonzero exit or invalid output returns 502, and conversion
timeout returns 504. Responses/logs do not expose converter
paths, input text, or trace; successful WAV responses include only the small
`X-Teratts-Text-Mode` mode header. The separate preparation CLI provides traces.

Paths and the executable are trusted operator configuration, not a sandbox for
untrusted programs. Use finite regular files on a local filesystem. The adapter
kills/reaps the child and joins both pipe workers; on Unix it kills only the child,
not a process group. Executables that spawn descendants or leave inherited pipes
open are unsupported and can prevent timely cleanup. No descendant supervision,
service installation, English-resource removal, or model inference changes are
included.

Focused model-free checks:

```sh
cargo test --offline --bin teratts-server russian_only::tests
cargo test --offline --bin teratts-server server::tests
# Optional real installed converter/database check (no model inference):
SPEECH_FRONT_TEST_BIN=/absolute/path/to/speech-front \
SPEECH_FRONT_TEST_CMUDICT=/absolute/path/to/cmudict.sqlite3 \
cargo test --offline --bin teratts-server installed_converter_cross_project -- --ignored
```

## DSH client plugin

`dsh-plugin/` contributes a button to `conversation.chat.assistant-actions`.
Install it into the DSH Web profile, add the `ui-teratts` row from
`dsh-plugin/cordis.patch.yml`, rebuild the Web artifacts, and refresh the
existing DSH URL. Host-owned settings configure the endpoint (default
`http://127.0.0.1:8088` or the approved Linux Tailnet endpoint
`https://teratts.tail9fd337.ts.net`). The browser keeps no credentials;
synthesis routes through the Host plugin. Active playback exposes
−10s, +15s, and a 1× / 1.25× / 1.5× / 2× speed cycle. Technical fenced blocks
and checklist items are converted to speakable text instead of being dropped.
For long speech, the first bounded segment begins as soon as ready, remaining
segments synthesize sequentially in the background, each response remains
16 MiB bounded (256 MiB cumulative buffered audio), and controls apply across
buffered speech. The client caps each synthesis RPC wait at 65 seconds, including
lost responses that outlive the Host timeout. Stop or expiry aborts the current
RPC; a late result cannot restart playback. This is a client waiting bound, not
a guarantee that a running native inference can be interrupted immediately.
The first-fragment limit remains 240 characters; no GPU speedup is implied.
