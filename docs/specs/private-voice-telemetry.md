# Private voice telemetry: deeper hooks

User-approved on 2026-09-30: retain maximal unredacted local voice/dialogue telemetry. Initial collection (Deck STT + TTS ingress proxy + native DSH journal snapshots) is already active. User additionally approved preparing/testing client draft/playback/correlation hooks and TTS internal normalized/preprocessed text. No DSH/TTS engine restart is authorized yet; activation needs separate consent.

## Changes

- Extend installed-compatible teratts plugin with optional private ingestion URL, remote record method, assistant original/message/session/playback context, draft observer using registered composer hook (no DOM scraping), and playback state events. Exact values retained without anonymization; credential headers excluded.
- Attach explicit request IDs/context to actual synthesis; preserve cache behavior and record cache-hit playback without pretending new inference occurred.
- Optional TTS internal stage writer uses existing reqwest/serde and sends bounded metadata only to loopback or Tailnet ingestion. Preserve post-Markdown, post-text-mode and preprocessed/chunk strings separately. Async bounded writer; no separate disk spool; failures never change audio response.
- Same managed Deck corpus/global 50 GB quota, no model/provider changes or external upload.
- Use branch based on actual deployed commit 5cff27e, not stale local main. Do not alter active installed artifacts before approval.

## Verification

JS tests for metadata, draft hook lifecycle, remote descriptor, correlation through cache/synthesis and private endpoint validation; plugin existing tests. Rust unit tests and cargo checks for writer encoding/input boundary, disabled default, safe destination and stage preservation. Deployment/build matching release must be recorded; runtime activation and GUI verification remain gated.

## Unknowns

Client session snapshot shape and availability, exact activation method without DSH restart, native STT-to-composer request correlation not yet provided by stock UI, full browser reachability for live tests, TTS remote toolchain build.
