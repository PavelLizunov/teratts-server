# Spec v2 Decision Log

- 2026-08-22 — Linux-first: permanent HTTP/service workloads use Linux unless the human explicitly approves another runtime.
- 2026-08-22 — Runtime target: new unprivileged Debian 12 LXC on `pve-ninitux3`, local storage; do not use `harness-test` or desktop workers as permanent runtime.
- 2026-08-22 — Do not use CTID 102: it is a historically documented guest whose recreation is forbidden without operator confirmation. Select a free non-historical CTID during deployment preflight.
- 2026-08-22 — RUAccent default: `full`; dictionary and disabled remain explicit startup modes; manual `+` overrides automatic stress for the whole Russian span.
- 2026-08-22 — Model scope: distilled TTS core plus used RUAccent assets; teacher sampler and unused `nn_accent/big.onnx` are out.
- 2026-08-22 — DSH architecture: browser calls a Host Remote. Endpoint and bearer credential remain host-side; generic client bundle contains no homelab hostname.
- 2026-08-22 — Icons: DSH `IconLoadingOutline16` and `IconStopFill16`, plus one local decorative 16px speaker SVG because rc.8 exports no speaker/volume glyph.
- 2026-08-22 — Admission: one active synthesis, two waiting, immediate `429` overflow; no unbounded mutex waiter set.
- 2026-08-22 — Restart guardrail: never restart the DSH host from an active request/session served by that host; use an external management channel and a new session for validation.
- 2026-08-22 — Evidence labels: backend, bundle and browser acceptance are distinct; only observed checks may be marked verified.
