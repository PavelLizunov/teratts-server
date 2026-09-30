"""Private local vocabulary inventory. No inference, corrections or training.

Uses the existing corpus lock, stdlib SQLite, source identities and bounded
transactions. Database and DELETE journal live inside the same corpus quota.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tarfile
import time
import unicodedata

from voice_corpus import MAX_BYTES, MIN_FREE_BYTES, SAMPLE_NAME

DB_NAME = "vocabulary.sqlite"
DB_LIMIT = 2_000_000_000
RESERVE = 16 * 1024 * 1024
MAX_METADATA = 1024 * 1024
MAX_TEXT = 4096
CONFIRMED = ("Omarchy", "Steam Deck", "Bonsai")
TOKEN = re.compile(r"[^\W_]+(?:[-_.+][^\W_]+)*", re.UNICODE)


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().replace("ё", "е").split())


def is_technical(word):
    return (bool(re.search(r"[A-Za-z]", word)) or any(c in word for c in "-_.+")
            or (any(c.isdigit() for c in word) and any(c.isalpha() for c in word))
            or (len(word) > 1 and word.isupper()))


def extract(text):
    if not isinstance(text, str):
        return {}
    # Observed surface forms only; ordinary words stay low-priority inventory.
    words = [w for w in TOKEN.findall(text[:MAX_TEXT]) if 2 <= len(w) <= 100 and not w.isdigit()]
    words = words[:1000]
    result = Counter((w, "technical_token" if is_technical(w) else "observed_word") for w in words)
    for i in range(len(words) - 1):
        left, right = words[i:i + 2]
        if ((is_technical(left) and is_technical(right))
                or (left[:1].isupper() and right[:1].isupper())):
            phrase = left + " " + right
            if len(phrase) <= 160:
                result[(phrase, "name_phrase_candidate")] += 1
    for term in CONFIRMED:
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        count = len(re.findall(pattern, text[:MAX_TEXT], flags=re.I))
        if count:
            # Avoid doubling frequency when already emitted as the exact phrase.
            result[(term, "confirmed_term_occurrence_candidate")] = count
    return result


def disagreement_spans(primary, teacher):
    a, b = TOKEN.findall(primary[:MAX_TEXT]), TOKEN.findall(teacher[:MAX_TEXT])
    # Bound diff work and retain candidate spans, not asserted replacements.
    matcher = SequenceMatcher(None, [normalize(x) for x in a[:1000]],
                              [normalize(x) for x in b[:1000]], autojunk=True)
    for operation, i, j, x, y in matcher.get_opcodes():
        if operation == "equal":
            continue
        left, right = " ".join(a[i:j]), " ".join(b[x:y])
        if max(j - i, y - x) <= 6 and len(left) <= 160 and len(right) <= 160:
            if left or right:
                yield left, right


def texts_from_metadata(metadata):
    kind = metadata.get("kind")
    if kind == "stt":
        yield "stt_raw", metadata.get("raw_text", "")
        # Formatting duplicates should not inflate raw utterance word frequencies.
        if metadata.get("final_text") != metadata.get("raw_text"):
            yield "stt_final", metadata.get("final_text", "")
    elif kind == "tts_internal_stages":
        yield "tts_input", metadata.get("input_text", "")
    elif kind == "vocabulary_teacher_record":
        yield "teacher_hinted" if metadata.get("vocabulary_hints") else "teacher_blind", metadata.get("teacher_text", "")


def read_metadata(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Unsafe archive")
    with tarfile.open(path) as archive:
        member = archive.getmember("sample.json")
        if not member.isfile() or member.size > MAX_METADATA:
            raise ValueError("Invalid metadata")
        metadata = json.loads(archive.extractfile(member).read())
    if not isinstance(metadata, dict):
        raise ValueError("Invalid metadata")
    return metadata


def open_database(root, limit=DB_LIMIT):
    path = root / DB_NAME
    for name in [DB_NAME, DB_NAME + "-journal"]:
        target = root / name
        if target.exists() or target.is_symlink():
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise ValueError("Unsafe database entry")
    connection = sqlite3.connect(path, timeout=1)
    os.chmod(path, 0o600)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA cache_size=-4096")
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    connection.execute(f"PRAGMA max_page_count={limit // page_size}")
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS sources (
        source TEXT PRIMARY KEY, kind TEXT NOT NULL, imported_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS terms (
        normalized TEXT PRIMARY KEY, display TEXT NOT NULL,
        confirmed INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS observations (
        source TEXT NOT NULL, stage TEXT NOT NULL, term TEXT NOT NULL,
        surface TEXT NOT NULL, category TEXT NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY(source,stage,term,surface,category)
      );
      CREATE INDEX IF NOT EXISTS observations_term ON observations(term,category);
      CREATE TABLE IF NOT EXISTS disputes (
        source TEXT NOT NULL, primary_span TEXT NOT NULL, teacher_span TEXT NOT NULL,
        hinted INTEGER NOT NULL, sample_ref TEXT,
        PRIMARY KEY(source,primary_span,teacher_span)
      );
    ''')
    for term in CONFIRMED:
        connection.execute("INSERT INTO terms VALUES(?,?,1) ON CONFLICT(normalized) DO UPDATE SET confirmed=1",
                           (normalize(term), term))
    connection.commit()
    return connection


def import_metadata(connection, source, metadata):
    if connection.execute("SELECT 1 FROM sources WHERE source=?", (source,)).fetchone():
        return False
    rid = metadata.get("client_context", {}).get("headers", {}).get("x-request-id", "")
    if isinstance(rid, str) and rid.startswith("synthetic"):
        return False
    kind = metadata.get("kind", "unknown")
    stages = list(texts_from_metadata(metadata))
    for stage, text in stages:
        for (surface, category), count in extract(text).items():
            normalized = normalize(surface)
            connection.execute("INSERT OR IGNORE INTO terms VALUES(?,?,0)", (normalized, surface))
            connection.execute("INSERT INTO observations VALUES(?,?,?,?,?,?)",
                               (source, stage, normalized, surface, category, count))
    if kind == "vocabulary_teacher_record":
        primary, teacher = metadata.get("primary_text", ""), metadata.get("teacher_text", "")
        if isinstance(primary, str) and isinstance(teacher, str):
            for left, right in disagreement_spans(primary, teacher):
                connection.execute("INSERT OR IGNORE INTO disputes VALUES(?,?,?,?,?)",
                                   (source, left, right, bool(metadata.get("vocabulary_hints")),
                                    metadata.get("original_sample_id")))
    connection.execute("INSERT INTO sources VALUES(?,?,?)", (source, str(kind), time.time_ns()))
    return True


def status(connection):
    return {"unique_terms": connection.execute("SELECT count(*) FROM terms").fetchone()[0],
            "confirmed_terms": connection.execute("SELECT count(*) FROM terms WHERE confirmed=1").fetchone()[0],
            "observation_rows": connection.execute("SELECT count(*) FROM observations").fetchone()[0],
            "sources": connection.execute("SELECT count(*) FROM sources").fetchone()[0],
            "disputes": connection.execute("SELECT count(*) FROM disputes").fetchone()[0],
            "db_page_bytes": connection.execute("PRAGMA page_count").fetchone()[0]
                             * connection.execute("PRAGMA page_size").fetchone()[0],
            "db_ceiling_bytes": DB_LIMIT, "human_gold": False, "autocorrection": False}


def collect(root, batch=25, idle_seconds=30):
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or not 1 <= batch <= 25:
        raise ValueError("Invalid corpus or batch")
    # Skip near recent activity. No claim this detects all live speech requests.
    paths = sorted(p for p in root.glob("*.tar") if SAMPLE_NAME.fullmatch(p.name))
    if paths and time.time() - max(p.stat().st_mtime for p in paths) < idle_seconds:
        return {"status": "skipped_recent_activity"}
    # New teacher disputes get indexed before historical inventory-only records.
    paths.reverse()
    fd = os.open(root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    connection = None
    old_umask = os.umask(0o077)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped_lock_busy"}
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Invalid corpus lock")
        total = 0
        for p in root.iterdir():
            entry = p.lstat()
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
                raise ValueError("Unexpected corpus entry")
            total += entry.st_size
        db_size = (root / DB_NAME).stat().st_size if (root / DB_NAME).exists() else 0
        # Reserve full possible rollback journal plus bounded batch growth before writes.
        reserve = db_size + RESERVE
        if total + reserve > MAX_BYTES or shutil.disk_usage(root).free - reserve < MIN_FREE_BYTES:
            return {"status": "skipped_storage_headroom"}
        connection = open_database(root, limit=min(DB_LIMIT, max(db_size, 128 * 1024) + RESERVE // 4))
        # Per-batch SQLite page ceiling enforces reserved growth even on adversarial text.
        processed = 0
        examined = 0
        started = time.monotonic()
        for path in paths:
            source = path.name
            if connection.execute("SELECT 1 FROM sources WHERE source=?", (source,)).fetchone():
                continue
            try:
                metadata = read_metadata(path)
            except (FileNotFoundError, ValueError, tarfile.TarError, KeyError, json.JSONDecodeError):
                continue
            with connection:
                processed += int(import_metadata(connection, source, metadata))
            examined += 1
            if (examined >= batch or time.monotonic() - started >= 0.2
                    or (root / DB_NAME).stat().st_size - db_size >= RESERVE // 4):
                break
        result = status(connection)
        result.update(status="collected", processed=processed, examined=examined,
                      corpus_bytes_after=sum(p.stat().st_size for p in root.iterdir()))
        return result
    finally:
        if connection is not None:
            connection.close()
        os.close(fd)
        os.umask(old_umask)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--batch", type=int, default=25)
    parser.add_argument("--idle-seconds", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(collect(args.root, args.batch, args.idle_seconds)))
