"""Plaintext rolling speech/dialogue corpus. Linux standard library only.

Atomic TAR records share one global byte quota and lock. Collection boundaries
provide metadata and attachments; this module never accesses a microphone.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import time
import uuid

MAX_BYTES = 50_000_000_000
MIN_FREE_BYTES = 5_000_000_000
SAMPLE_NAME = re.compile(r"[0-9]{20}-[0-9a-f]{32}\.tar\Z")
TEMP_NAME = re.compile(r"\.[0-9]{20}-[0-9a-f]{32}\.tar\.tmp\Z")


class Corpus:
    def __init__(self, root, max_bytes=MAX_BYTES, min_free_bytes=MIN_FREE_BYTES):
        if max_bytes <= 0 or max_bytes > MAX_BYTES or min_free_bytes < 0:
            raise ValueError("Invalid retention policy")
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        # All parent directories must already exist; never recursively create them.
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("Corpus root must be a real directory")
        os.chmod(self.root, 0o700)

    def _locked_directory(self):
        # Caller closes both descriptors. O_NOFOLLOW rejects root/lock symlinks.
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            lock = os.open(".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                os.close(lock)
                raise ValueError("Invalid lock file")
            os.fchmod(lock, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            return directory, lock
        except BaseException:
            os.close(directory)
            raise

    @staticmethod
    def _inventory(directory, cleanup=False):
        samples = []
        total = 0
        # Never recurse, follow symlinks, or delete files not owned by this module.
        for name in os.listdir(directory):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Unexpected corpus entry")
            if TEMP_NAME.fullmatch(name) and cleanup:
                os.unlink(name, dir_fd=directory)
                continue
            total += info.st_size
            if SAMPLE_NAME.fullmatch(name):
                samples.append((name, info.st_size))
        return sorted(samples), total

    def save(self, audio, metadata):
        """Return sample id, or None when quota/headroom prevents collection.

        I/O/validation failures raise; integration must isolate them from STT.
        Input metadata must come from an explicit application-owned allowlist.
        """
        if len(audio) > 10 * 1024 * 1024:
            return None
        data = dict(metadata)
        data.update({"audio_sha256": hashlib.sha256(audio).hexdigest(),
                     "audio_bytes": len(audio), "human_reference_text": None,
                     "reference_status": "unreviewed_model_output",
                     "audio_origin": "submitted_stt_request"})
        return self.save_record(data, {"original.wav": audio})

    def save_record(self, metadata, attachments=None):
        """General event/media record sharing exactly the same FIFO and quota."""
        attachments = attachments or {}
        if len(attachments) > 16:
            raise ValueError("Too many attachments")
        size = 0
        for name, content in attachments.items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name) or name == "sample.json":
                raise ValueError("Invalid attachment name")
            if not isinstance(content, bytes):
                raise ValueError("Attachments must be bytes")
            size += len(content)
        if size > 32 * 1024 * 1024:
            return None
        sample_id = f"{time.time_ns():020d}-{uuid.uuid4().hex}"
        data = dict(metadata)
        data.update({"schema_version": 2, "sample_id": sample_id,
                     "collected_at_unix_ns": time.time_ns(),
                     "attachment_hashes": {name: hashlib.sha256(content).hexdigest()
                                           for name, content in attachments.items()}})
        manifest = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(manifest) > 1024 * 1024:
            return None
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, content in (*attachments.items(), ("sample.json", manifest)): 
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(content))
        payload = buffer.getvalue()
        if len(payload) > self.max_bytes:
            return None
        directory, lock = self._locked_directory()
        temporary = f".{sample_id}.tar.tmp"
        try:
            samples, total = self._inventory(directory, cleanup=True)
            free = shutil.disk_usage(self.root).free
            remove = []
            for name, size in samples:
                if total + len(payload) <= self.max_bytes and free - len(payload) >= self.min_free_bytes:
                    break
                remove.append(name)
                total -= size
                free += size
            if total + len(payload) > self.max_bytes or free - len(payload) < self.min_free_bytes:
                return None  # Unknown files/headroom prevent safe collection: delete nothing.
            for name in remove:
                os.unlink(name, dir_fd=directory)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.rename(temporary, f"{sample_id}.tar", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            return sample_id
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            finally:
                os.close(lock)
                os.close(directory)

    def status(self):
        directory, lock = self._locked_directory()
        try:
            samples, total = self._inventory(directory)
            return {"samples": len(samples), "bytes": total, "max_bytes": self.max_bytes,
                    "min_free_bytes": self.min_free_bytes, "within_cap": total <= self.max_bytes}
        finally:
            os.close(lock)
            os.close(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show content-free corpus status")
    parser.add_argument("root")
    args = parser.parse_args()
    print(json.dumps(Corpus(args.root).status()))
