#!/usr/bin/env python3
"""Run six AB/BA pairs with the frozen 2026-09-27 Node evaluator; no TTS requests."""
import hashlib
import json
import pathlib
import subprocess
import sys

control, candidate, workload, prefix = sys.argv[1:]
roots = {"control": pathlib.Path(control).resolve(), "candidate": pathlib.Path(candidate).resolve()}
out = pathlib.Path("evidence/tts-20260927")
out.mkdir(parents=True, exist_ok=True)
commits = {}
for label, root in roots.items():
    subprocess.run(["git", "-C", str(root), "diff", "HEAD", "--exit-code"], check=True, capture_output=True)
    commits[label] = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
rows = {label: [] for label in roots}
order = []
for pair in range(6):
    labels = ["control", "candidate"] if pair % 2 == 0 else ["candidate", "control"]
    order.append(labels)
    for label in labels:
        root = roots[label]
        result = subprocess.check_output(["node", str(root / "evaluators/tts-preprocessing-20260927/evaluate.mjs"), str(root), "bench", workload], text=True, timeout=30)
        row = json.loads(result)
        assert row["quality"] and all(row["negative_controls"].values())
        rows[label].append(row)
        print(pair, label, row["seconds"], flush=True)

def store(name, value):
    path = out / (prefix + "-" + name + ".json")
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

store("raw", {"commits": commits, "order": order, "rows": rows})
refs = {}
for label, data in rows.items():
    subprocess.run(["git", "-C", str(roots[label]), "diff", "HEAD", "--exit-code"], check=True, capture_output=True)
    assert subprocess.check_output(["git", "-C", str(roots[label]), "rev-parse", "HEAD"], text=True).strip() == commits[label]
    quality = store(label + "-quality", {"kind":"quality", "commit":commits[label], "workload":workload, "target_id":"dsh-host-node22-linux-x64", "status":"passed", "checks":{"exact_output":all(r["quality"] for r in data), "client_host_parity":all(r["quality"] for r in data)}, "negative_controls":{key:all(r["negative_controls"][key] for r in data) for key in data[0]["negative_controls"]}})
    refs[label] = store(label + "-measurement", {"kind":"measurement", "commit":commits[label], "workload":workload, "target_id":"dsh-host-node22-linux-x64", "metric":{"name":"preprocessing_wall_seconds", "unit":"s"}, "samples":[r["seconds"] for r in data], "quality":quality, "resources":{"peak_rss_bytes":max(r["peak_rss_bytes"] for r in data)}})
print(json.dumps({"commit":commits["candidate"], "control_commit":commits["control"], **refs}))
