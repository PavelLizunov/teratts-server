# Speech latency candidate verification

Date: 2026-09-09. Base: `ebdbe89`; branch: `agent/speech-latency-gpu`.

## Requirements and outcome

- Trace browser button → Host RPC → existing Tera CPU service: exercised using an isolated authenticated browser against the existing GUI, without replacing or restarting services.
- Current button began playback in approximately 1.8 s. Three fixed short mixed Russian/technical samples through the real RPC envelope succeeded in 743, 1194 and 624 ms. These are individual observations, not latency percentiles or a controlled CPU/GPU benchmark.
- Smaller first chunk experiment: 120-character limit gave approximately 5.9 s in a browser trial; no improvement established. Reverted to the existing 240-character limit. The production inference stage timings during that trial completed in approximately 0.9 s; remaining delay was not attributed conclusively.
- Deadline-only browser candidate with 240-character limit began playback in 1787 ms; RPC resource duration 1602 ms, transfer after response start approximately 45 ms. Candidate JavaScript was substituted only inside the isolated browser, not deployed.
- Lost RPC protection: each client synthesis wait is bounded to 65 s; Stop/deadline aborts the active child signal and settles waiting even when the underlying RPC ignores abort. Late responses cannot restart playback. No new retries or fallback requests.
- Optional CUDA feature is default-off. Explicit provider and bounded per-session arena configuration validated before Tera graph loading; strict registration errors, no silent CPU masquerading as GPU. RUAccent unchanged on CPU. No CUDA model loading performed.
- Original long-delay symptom is NOT proven fixed. GPU primary, automatic failover, GPU memory peak, quality parity and CPU/GPU comparison remain unimplemented/unverified pending safe GPU admission.

## Executed checks

From repository root with Rust toolchain on PATH:

```sh
cargo test --offline --locked --bin teratts-server
cargo test --offline --locked --features cuda --bin teratts-server execution_provider::tests
cargo check --offline --locked --features cuda --bin teratts-server
node --test dsh-plugin/test/*.test.js
git diff --check
```

All exit 0: 103 Rust tests passed / four resource-dependent tests ignored; four CUDA configuration tests passed; 58 JavaScript tests passed. Compilation/configuration checks do not initialize CUDA or establish graph placement/performance.

## Differential safety review

Scope: task-owned uncommitted changes relative to the base in Cargo.toml, src/main.rs, src/tera.rs, src/execution_provider.rs, dsh-plugin/lib/client.js, related tests and README. Independent native reviewer inspected actual files and reran client tests plus an in-memory full playback deadline/Stop check. Source changes leave endpoint allowlist, credentials, authorization and server text validation unchanged. No new dependency version, network destination, subprocess or dynamic path input is introduced; optional ort/cuda uses the existing operator-selected dynamic runtime.

Trust boundaries: provider/budget are trusted operator environment, never HTTP input. Invalid provider and unavailable CUDA build fail closed; arena limits are NOT global memory admission. Native inference cancellation remains cooperative at existing boundaries, not guaranteed immediate interruption. Read-only review found no new security blocker in the examined paths; this is not a whole-repository security assurance.

## Deployment limits

CPU production, model/lexicon/voice, drivers and existing LLM remained unchanged. No DSH restart or replacement server. The installed GUI plugin is a newer runtime-specific local variant of the repository plugin: replacing it wholesale with repository code would discard compatibility changes. Any later activation must narrowly port the helper/call site, rebuild the owning Web artifact, and verify the existing URL after refresh. No activation is claimed here.
