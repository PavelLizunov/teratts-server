"""Select small independent STT teacher pilot on Deck; never upload audio.

Run on Deck via SSH. Manifest contains IDs/timing/hashes, no text/audio. Explicit
selection stays reproducible even as the rolling corpus changes.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import wave

MAX_SAMPLES = 20
MAX_SECONDS = 300
MIN_DURATION = 2
MAX_DURATION = 30


def inspect_sample(path):
    if path.is_symlink():
        return None
    try:
        with tarfile.open(path) as archive:
            metadata = json.load(archive.extractfile("sample.json"))
            if metadata.get("kind") != "stt":
                return None
            context = metadata.get("client_context", {})
            rid = next((value for key, value in context.get("headers", {}).items()
                        if key.lower() == "x-request-id"), "")
            if rid.startswith("synthetic") or metadata.get("audio_origin") != "submitted_stt_request":
                return None
            if not metadata.get("raw_text", "").strip():
                return None
            audio = archive.extractfile("original.wav").read(10 * 1024 * 1024 + 1)
            if len(audio) > 10 * 1024 * 1024:
                return None
            with wave.open(io.BytesIO(audio), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
                    return None
                frames = wav.readframes(wav.getnframes())
            if not frames.strip(b"\0") or not MIN_DURATION <= duration <= MAX_DURATION:
                return None
            digest = hashlib.sha256(audio).hexdigest()
            if digest != metadata.get("audio_sha256"):
                return None
            return {"sample_id": metadata["sample_id"], "filename": path.name,
                    "duration_s": round(duration, 6), "audio_sha256": digest,
                    "audio_bytes": len(audio), "backend": metadata.get("backend"),
                    "reference_status": "unreviewed_model_output"}
    except (OSError, ValueError, KeyError, tarfile.TarError, wave.Error, EOFError):
        return None


def select(root):
    candidates = []
    hashes = set()
    # Stable oldest-first scan, deduplicate actual audio, never selects TTS audio.
    for path in sorted(Path(root).glob("*.tar")):
        sample = inspect_sample(path)
        if sample and sample["audio_sha256"] not in hashes:
            candidates.append(sample)
            hashes.add(sample["audio_sha256"])
    # Spread examples over available history rather than take 20 adjacent utterances.
    indices = sorted(set(round(i * (len(candidates) - 1) / (MAX_SAMPLES - 1))
                         for i in range(min(MAX_SAMPLES, len(candidates))))) if candidates else []
    if len(candidates) < MAX_SAMPLES:
        indices = list(range(len(candidates)))
    chosen = []
    duration = 0
    for index in indices:
        sample = candidates[index]
        if duration + sample["duration_s"] > MAX_SECONDS:
            continue
        chosen.append(sample)
        duration += sample["duration_s"]
    return {"schema_version": 1, "max_samples": MAX_SAMPLES, "max_seconds": MAX_SECONDS,
            "eligible_unique_samples": len(candidates), "selected_samples": len(chosen),
            "total_duration_s": round(duration, 6), "samples": chosen,
            "external_upload_started": False, "label_policy": "pseudo_labels_not_human_gold"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    args = parser.parse_args()
    print(json.dumps(select(args.root), ensure_ascii=False))
