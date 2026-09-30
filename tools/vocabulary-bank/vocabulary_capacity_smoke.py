"""Isolated synthetic capacity smoke. NEVER point this at the real vocabulary.

Creates one million synthetic candidates and observation rows in a new temp
worker directory; does not feed them into prompts or production archive.
"""
import json
from pathlib import Path
import tempfile
import time

from vocabulary_bank import open_database, status

root = Path(tempfile.mkdtemp(prefix="vocabulary-capacity-only-"))
root.chmod(0o700)
connection = open_database(root)
start = time.monotonic()
try:
    for offset in range(0, 1_000_000, 5000):
        with connection:
            connection.executemany("INSERT INTO terms VALUES(?,?,0)",
                ((f"syntheticterm{i}", f"SyntheticTerm{i}") for i in range(offset, offset + 5000)))
            connection.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?)",
                (("synthetic-only", "capacity", f"syntheticterm{i}", f"SyntheticTerm{i}",
                  "synthetic_capacity", 1) for i in range(offset, offset + 5000)))
    build_seconds = time.monotonic() - start
    start = time.monotonic()
    row = connection.execute("SELECT surface,count FROM observations WHERE term=?", ("syntheticterm999999",)).fetchone()
    lookup_ms = (time.monotonic() - start) * 1000
    assert row == ("SyntheticTerm999999", 1)
    result = status(connection)
    assert result["unique_terms"] == 1_000_003
    assert result["observation_rows"] == 1_000_000
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print(json.dumps({"synthetic_only": True, "directory": str(root), "build_seconds": round(build_seconds, 2),
                      "indexed_lookup_ms": round(lookup_ms, 3), **result}))
finally:
    connection.close()
