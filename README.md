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

## DSH client plugin

`dsh-plugin/` contributes a button to `conversation.chat.assistant-actions`.
Install it into the DSH Web profile, add the `ui-teratts` row from
`dsh-plugin/cordis.patch.yml`, rebuild the Web artifacts, and refresh the
existing DSH URL. Host-owned settings configure the endpoint (default
`http://127.0.0.1:8088` or the approved Linux Tailnet endpoint
`https://teratts.tail9fd337.ts.net`). The browser holds no endpoint or
credential; synthesis routes through the Host plugin. Active playback exposes
−10s, +15s, and a 1× / 1.25× / 1.5× / 2× speed cycle. Technical fenced blocks
and checklist items are converted to speakable text instead of being dropped.
