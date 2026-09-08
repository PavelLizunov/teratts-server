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

## HTTP

```sh
curl http://127.0.0.1:8088/health
curl -o hello.wav http://127.0.0.1:8088/tts \
  -H 'content-type: application/json' \
  -d '{"text":"Привет, это TeraTTSv2.","voice":"ru_f1","duration_scale":1.0}'
```

`POST /tts` returns mono 16-bit PCM WAV at 44.1 kHz. The server serializes
inference because one engine owns the four mutable ONNX Runtime sessions.

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
all former English spans. Unknown/malformed markup returns 400. Numeric comparison
symbols remain text for conversion. Numeric or space-separated arithmetic `+`
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
segments synthesize sequentially in the background, total audio remains
16 MiB bounded, and controls apply across buffered speech.
