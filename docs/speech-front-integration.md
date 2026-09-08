# Approved speech-front integration

## Configuration and HTTP contract

Configure `TERATTS_LEXICON_PATH` in the server process environment before
`teratts-server --serve` starts. It selects the complete approved lexicon export,
not a patch merged into the builtin lexicon. When unset, the server uses its
compile-time builtin lexicon and performs no lexicon filesystem reads per request.
The configured path and `TERATTS_SPEECH_FRONT` default are captured at startup.
An empty configured path is invalid, not equivalent to an unset variable.

`POST /tts` keeps its existing request fields, authentication, errors and WAV
response. No new endpoint is introduced. The optional `speech_front` boolean
selects normalization:

| Request field | Server environment | Effective flag |
| --- | --- | --- |
| omitted or `null` | `TERATTS_SPEECH_FRONT=1` | on |
| omitted or `null` | unset or any other value | off |
| `true` | any | on |
| `false` | any | off |

The external path alone does not turn normalization on. An enabled admitted
request refreshes once, then retains one immutable normalizer snapshot for all
its spans and chunks. Preparation runs on the existing blocking synthesis
worker, not a Tokio runtime thread. Off requests skip reload entirely, including
when a previously valid file has since disappeared or become invalid. English
requests still refresh when enabled but are not Russian-normalized; explicit
`<en>` spans in Russian requests are preserved. Existing numeric normalization,
language validation, RUAccent, chunking and synthesis remain server-owned and
unchanged. This feature applies to HTTP `--serve`, not CLI `--speak`.

## Publish approved updates

1. The review tool's **Approve** action must export a complete approved
   schema-version-1 `lexicon.toml` to the configured location.
2. Write a temporary file in the same directory, then atomically replace the
   destination. Do not edit a published file in place: a syntactically valid
   intermediate edit cannot be distinguished from an intentional export.
3. The next enabled admitted HTTP request reads and SHA-256 hashes the bytes.
   Changed content is detected even when byte length is unchanged or the path
   points to a new inode after replacement. The full file is validated before
   swapping the in-process `Arc` snapshot under a mutex.

The server and review tool need a **local shared filesystem**, or an explicit
file-sync step that atomically publishes the approved export on the server's
filesystem. GitHub/Git remote changes do not magically update runtime files;
pushing a lexicon without syncing it to the configured path has no runtime effect.
No deployment, service, credential, model, DSH plugin or remote-sync configuration
is changed by this integration. Initial environment configuration requires the
normal operational startup; subsequent valid file revisions need no rebuild or
restart.

## Validation and failure behavior

- Startup validates the configured external file before model verification/loading.
  Missing, unreadable, nonregular, oversized, non-UTF-8, malformed TOML or invalid
  schema/entries fail startup. There is no silent builtin fallback for an
  explicitly configured bad file, even when normalization defaults to off.
- Files must be regular files of at most **2 MiB (2,097,152 bytes)**. Descriptor
  metadata and a capped read of at most limit + 1 bytes enforce the size bound
  even if a file grows after the initial metadata check.
- Full validation uses the existing server parser: schema version 1, required
  fields, nonempty/trimmed written and spoken forms, word/phrase matching,
  nonempty language/sources/engine overrides, and unique case-insensitive written
  forms. Existing normalizer semantics are retained, not replaced with a shared
  engine implementation or G2P suggestions.
- Later failures retain the last valid snapshot and its revision. The request
  continues normally. A fixed reason is logged at most once per **60 seconds**
  per loader, including across different failures/recoveries. Diagnostics never
  include the path, parser details, lexicon text or request text. Restoring valid
  data is retried on the next enabled request, without waiting for the log window.
- The path, parent directory and synchronized export are operator-controlled;
  this is not an API for arbitrary HTTP-provided paths. Do not use device files,
  FIFOs, named pipes, hostile writable directories or unreliable network mounts.
  Nonregular files are rejected before opening and the opened descriptor is
  checked again. Linux additionally uses a nonblocking open to guard raced FIFO
  replacement. Other platforms require the trusted-directory assumption; this
  is not a guarantee against a hostile filesystem owner racing replacements.
  Size-bounded local I/O does not impose a hard timeout on an unresponsive mount.
- SHA-256 here detects revisions; it is not an approval signature. Only publish
  user-approved data. No GPL server code is copied back into the engine-neutral
  speech-front repository.

## Model-free verification

From the repository root:

```sh
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
```

Tests cover atomic approved-export replacement reaching request preparation,
same-length revisions, old snapshot lifetime, invalid initial files, later
corrupt/missing updates with rate-limited diagnostics and valid recovery, size
and regular-file constraints, builtin fallback when unset, explicit false over a
true injected default, English/mixed spans, and existing server/normalizer
regressions. Tests do not mutate process environment for speech-front flags.
The FIFO fixture runs only on Linux and uses the local `mkfifo` utility.
The real cross-project approval test is opt-in and needs a built speech-front
CLI (provided by the owning repository, not vendored here):

```sh
SPEECH_FRONT_TEST_BIN=/absolute/path/to/speech-front \
  cargo test --locked cross_project_approve_reloads -- --ignored
```

It runs `observe` and `approve --confirm` against a temporary SQLite queue and
lexicon, then checks the already-existing loader uses the new approved form.
This ignored test fails if the binary is unavailable; it does not silently skip.

No live server, production model assets or synthesis are required. The existing
asset-dependent RUAccent golden-corpus test remains ignored by default; Linux
unit-test success does not verify Windows runtime behavior or actual audio.
