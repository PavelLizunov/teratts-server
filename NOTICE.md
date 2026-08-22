# teratts-server — third-party model notice and release gate

## RELEASE GATE

The TeraTTSv2 model assets (ONNX graphs, voice styles, and tokenizer table)
come from the public Hugging Face repository `TeraSpace/TeraTTSv2`, pinned to
revision `f05ea799094571a3553904a555df3834fb0b963b`.

**Upstream license status as of 2026-08-10: none published.** The repository
exposes no LICENSE file and no license metadata. Do not ship, mirror, or claim
redistribution rights over the model weights or style assets until a public or
archived written grant explicitly covers them.

This repository therefore contains no model assets. `--download-models` points
at the official upstream URL and downloads the pinned files directly to the
user's machine after SHA-256 verification.

TeraTTSv2 upstream: https://huggingface.co/TeraSpace/TeraTTSv2

The downloaded `RUACCENT_NOTICE.txt` states that the bundled RUAccent-derived
work is Copyright 2026 Denis Petrov and licensed under the MIT License.
RUAccent upstream: https://github.com/Den4ikAI/ruaccent

The Rust source copied and adapted from `suflyor-teratts` remains
GPL-3.0-or-later; see `LICENSE` and `Cargo.toml`.
