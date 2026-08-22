# Spec v2 Amendment A: Debian ONNX Runtime Artifact

## 1. Intent & Invariants
- Keep the approved unprivileged Debian 12 LXC; replace the ABI-incompatible default static Pyke ONNX Runtime with the official Microsoft ONNX Runtime 1.27.0 shared library.
- `ort = 2.0.0-rc.13` uses `default-features = false`, features `load-dynamic` and `api-27`; the absolute `ORT_DYLIB_PATH` selects the immutable library.
- Pinned artifacts: `onnxruntime-linux-x64-1.27.0.tgz` SHA-256 `547e40a48f1fe73e3f812d7c88a948612c23f896b91e4e2ee1e232d7b468246f`; `libonnxruntime.so.1.27.0` SHA-256 `4061866361d9a8d2872f5f419c5515ce35a830a0c5c77ce1723320ac0dbabfc7`.

## 2. Interface / Data Contract
```text
/opt/teratts/releases/<app-sha>/teratts-server
/opt/teratts/releases/<app-sha>/lib/libonnxruntime.so.1.27.0
/opt/teratts/releases/<app-sha>/release.env
ORT_DYLIB_PATH=/opt/teratts/current/lib/libonnxruntime.so.1.27.0
```

## 3. Verification Checklist
- [ ] Debian 12 `cargo build --release --locked` succeeds without statically linking ONNX Runtime.
- [ ] `ldd teratts-server` contains no ONNX Runtime dependency; startup loads only the pinned absolute dylib.
- [ ] Installer verifies tarball and dylib hashes; activation verifies binary+dylib before switching `current`.
- [ ] Wrong/missing dylib prevents activation; previous exact-SHA release remains runnable.
- [ ] Full RUAccent synthesis and HTTP acceptance pass inside the Debian LXC.
