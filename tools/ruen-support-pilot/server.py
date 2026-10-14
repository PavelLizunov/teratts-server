"""Serve the exact trained RU/EN checkpoint through the retained WAV adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gigaam-multilingual"))
from gigaam_multilingual_server import Recognizer, handler, ThreadingHTTPServer

MODEL_SHA = "b1e64f5b0e6349deefc3534358cbe97becac78349ae5ddc3a28c380ac9974a6d"
MODEL_NAME = "gigaam-ruen-support-pilot-20261014"


class PilotRecognizer(Recognizer):
    def __init__(self, checkpoint):
        path = Path(checkpoint)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA:
                raise ValueError("Trained checkpoint checksum mismatch")
        import torch
        import gigaam
        if torch.version.cuda is not None:
            raise ValueError("This deployment uses the retained CPU runtime")
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        asr = gigaam.load_model(str(path), device="cpu", fp16_encoder=False)
        if len(asr.decoding.tokenizer.vocab) != 74:
            raise ValueError("Unexpected trained vocabulary")
        # Reuse the historical adapter's WAV checks, lock and continuous chunk cuts.
        self.model = SimpleNamespace(model=asr)
        self.torch = torch
        self.lock = threading.Lock()
        self.metadata = {
            "model": MODEL_NAME, "model_revision": MODEL_SHA, "model_sha256": MODEL_SHA,
            "quantization": "none", "variant": "ssl220m-new-ruen-ctc-support-pilot",
            "engine": "pytorch", "engine_version": torch.__version__,
            "device": "cpu", "dtype": "float32", "cpu_threads": 4,
            "decoder": "CTC greedy", "punctuation": "none",
            "chunk_max_seconds": 25,
            "chunk_cut": "quietest 160ms window in last4sec,continuous nonoverlap",
            "upstream_commit": "7447938d791c4f3e643386ee22c33777004293a5",
            "experimental": True,
        }
        self.ready = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--port", type=int, default=10002)
    args = parser.parse_args()
    recognizer = PilotRecognizer(args.checkpoint)
    def audit(event, args):
        if event == "socket.connect":
            raise RuntimeError("ASR does not make outbound connections")
    sys.addaudithook(audit)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(recognizer))
    server.daemon_threads = True
    print(json.dumps({"ready": True, "model": recognizer.metadata}), flush=True)
    server.serve_forever()
