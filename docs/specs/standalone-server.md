# Spec: Standalone TeraTTSv2 Server and DSH Voice

## 1. Intent & Invariants
- What: reuse the proven Rust TeraTTSv2 inference modules in an independent HTTP/CLI project and add a DSH assistant-message voice action.
- Invariants: model revision is `f05ea799094571a3553904a555df3834fb0b963b`; model assets are downloaded from upstream, never distributed in Git; output is mono 16-bit PCM WAV at 44.1 kHz; inference constants remain CFG 3.0, SPEED 1.05, SEED 1234; one synthesis runs at a time.

## 2. Interface / Data Contract
```rust
struct TtsRequest { text: String, voice: Option<String>, duration_scale: Option<f32> }
struct HealthResponse { status: String, revision: String, sample_rate: u32, voices: Vec<String> }

// GET /health -> JSON
// POST /tts -> audio/wav or JSON error
// --download-models [--model-dir PATH]
// --serve [--host HOST] [--port PORT] [--model-dir PATH]
// --speak TEXT [--voice ID] [--output FILE] [--model-dir PATH]
```

## 3. Verification Checklist (Definition of Done)
- [ ] Reused engine, text normalization, number expansion, indexer, chunker, manifest, NPY, and RNG modules.
- [ ] Downloader verifies every file size and SHA-256 before atomic publication.
- [ ] `/health`, `/tts`, and CLI WAV output behave as specified.
- [ ] DSH button has idle/loading/playing states and strips Markdown/code blocks.
- [ ] Rust tests and real `ru_f1` synthesis pass on `mac-worker`; compile checks pass on Windows/Linux workers.
- [ ] DSH Web artifacts are rebuilt and verified at the existing `http://127.0.0.1:3080`.
