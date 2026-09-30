# Local vocabulary candidate bank

Source-only backup of the private Model Forge collector, not a TTS-engine dependency. Python stdlib SQLite, no model calls, network lookups, automatic corrections, lexicon writes or training. Speech Front unchanged. Do not commit private DB, results/transcripts, real audio or source IDs.

Run tests:

```sh
python3 -m unittest discover -s tools/vocabulary-bank/tests -v
```

Collector reads bounded sample.json metadata from existing TAR corpus, stores normalized terms, original surfaces/counts, source/stage and disputed primary/teacher spans. Three user-confirmed vocabulary seeds: Omarchy, Steam Deck, Bonsai. Model suggestions and occurrences never inherit human confirmation. Ordinary observed words are inventory, not asserted named entities. Newest unprocessed sources first; stable source identity prevents repeated import inflation.

Deployment-specific unit/timer templates are under deploy/. Timer every 10–12 minutes, nice 19 / idle I/O / CPUWeight=1 / 128 MiB. Skip recent archive activity or busy nonblocking corpus lock. Up to 25 metadata records, 4096 chars/1000 tokens per stage, soft batch work target 0.2 sec. No restart of existing speech/DSH services required. Historical backfill can be delayed by continuous activity/new sources.

DB and DELETE rollback journal live inside the same corpus root and count against its existing 50 GB logical byte quota. 2 GB DB ceiling is internal, not extra. Reserve current DB-size rollback journal + 16 MiB under flock, enforce max ~4 MiB page growth per batch; skip on headroom failure. Unknown/symlink/hardlink entries rejected. DB 0600, no WAL/second spool. DB history may survive source expiration; missing references remain a limit.

Observed live acceptance: 490 terms / 810 observation rows / 29 disputes, 360,448-byte DB, three confirmed seeds; quick_check ok, unchanged gateway/model PIDs. Nine unit tests passed.

Separate synthetic worker capacity smoke: 1,000,003 terms, 1,000,000 observations, 321,970,176-byte DB, 12.43 s construction, one indexed lookup 0.181 ms, integrity_check ok. Synthetic test NEVER fed into production dictionary. This checks storage capacity, not complex aggregate query performance, long soak or real-word quality.

No million-word prompt: future hints must be bounded to relevant terms. No mass dictionary download or filler creation. The full private operating report stays in Model Forge docs/vocabulary-bank.md, outside this repository.
