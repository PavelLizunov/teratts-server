#!/usr/bin/env python3
import sys
import time
import json
import urllib.request
import urllib.error
import os

PORT = int(os.environ.get("BENCH_PORT", "8089"))
TOKEN = os.environ.get("TERATTS_TOKEN", "")
CGROUP_PATH = f"/sys/fs/cgroup/system.slice/teratts-benchmark.service"

CORPUS = [
    "Сегодня мы проверяем скорость первого отклика.",
    "В данном отчете рассматриваются результаты первичного аудита инфраструктуры серверов синтеза речи.",
    "Подсистема представляет собой высокопроизводительный сервер синтеза речи на базе ONNX Runtime с поддержкой causal overlap-save streaming.",
]

def read_cgroup_stats():
    stats = {}
    stat_file = os.path.join(CGROUP_PATH, "cpu.stat")
    if os.path.exists(stat_file):
        with open(stat_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    try:
                        stats[parts[0]] = int(parts[1])
                    except ValueError:
                        pass
    peak_file = os.path.join(CGROUP_PATH, "memory.peak")
    if os.path.exists(peak_file):
        with open(peak_file, "r") as f:
            try:
                stats["memory_peak"] = int(f.read().strip())
            except ValueError:
                pass
    return stats

def synth(text, voice="ru_f1"):
    url = f"http://127.0.0.1:{PORT}/tts"
    headers = {
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    payload = json.dumps({
        "text": text,
        "voice": voice,
        "language": "ru",
        "duration_scale": 1.0,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    t1 = time.perf_counter()

    elapsed = t1 - t0
    if len(body) < 44:
        raise ValueError(f"invalid WAV length {len(body)}")

    sample_rate = int.from_bytes(body[24:28], "little")
    data_bytes = int.from_bytes(body[40:44], "little")
    duration = data_bytes / (sample_rate * 2) if sample_rate > 0 else 0.0

    return elapsed, duration, len(body)

def wait_for_ready(timeout=60):
    url = f"http://127.0.0.1:{PORT}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("status") == "ready":
                        return data
        except Exception:
            time.sleep(1)
    raise TimeoutError(f"server at port {PORT} not ready after {timeout}s")

def run_bench(target_count=50):
    print(f"Waiting for server at port {PORT}...")
    health = wait_for_ready()
    print(f"Server ready: app_git_sha={health.get('app_git_sha')} synthesis_revision={health.get('synthesis_revision')[:12]}")

    print("Warming up with all corpus phrases...")
    for phrase in CORPUS:
        e, d, _ = synth(phrase)
        print(f"  warmup '{phrase[:30]}...': elapsed={e:.3f}s duration={d:.3f}s")

    print(f"\nStarting benchmark series (target {target_count} requests)...")
    cgroup_start = read_cgroup_stats()

    records = []
    idx = 0
    while len(records) < target_count:
        phrase = CORPUS[idx % len(CORPUS)]
        idx += 1
        elapsed, duration, byte_len = synth(phrase)
        rtf = elapsed / duration if duration > 0 else 0.0
        records.append({
            "idx": len(records),
            "text_len": len(phrase),
            "elapsed": elapsed,
            "duration": duration,
            "rtf": rtf,
            "bytes": byte_len,
        })
        sys.stdout.write(".")
        sys.stdout.flush()

    print("\nBenchmark requests completed.")
    cgroup_end = read_cgroup_stats()

    # Aggregate metrics
    rtfs = sorted([r["rtf"] for r in records])
    latencies = sorted([r["elapsed"] for r in records])
    total_elapsed = sum(r["elapsed"] for r in records)
    total_audio = sum(r["duration"] for r in records)

    rtf_mean = sum(rtfs) / len(rtfs)
    rtf_corpus = total_elapsed / total_audio if total_audio > 0 else 0.0
    rtf_p50 = rtfs[int((len(rtfs) - 1) * 0.50)]
    rtf_p95 = rtfs[int((len(rtfs) - 1) * 0.95)]
    lat_p50 = latencies[int((len(latencies) - 1) * 0.50)]
    lat_p95 = latencies[int((len(latencies) - 1) * 0.95)]

    delta_usage_usec = cgroup_end.get("usage_usec", 0) - cgroup_start.get("usage_usec", 0)
    delta_user_usec = cgroup_end.get("user_usec", 0) - cgroup_start.get("user_usec", 0)
    delta_system_usec = cgroup_end.get("system_usec", 0) - cgroup_start.get("system_usec", 0)
    delta_nr_periods = cgroup_end.get("nr_periods", 0) - cgroup_start.get("nr_periods", 0)
    delta_nr_throttled = cgroup_end.get("nr_throttled", 0) - cgroup_start.get("nr_throttled", 0)
    delta_throttled_usec = cgroup_end.get("throttled_usec", 0) - cgroup_start.get("throttled_usec", 0)
    cpu_per_audio_sec = (delta_usage_usec / 1e6) / total_audio if total_audio > 0 else 0.0
    peak_mem = cgroup_end.get("memory_peak", 0)

    report = {
        "count": len(records),
        "total_elapsed_s": round(total_elapsed, 3),
        "total_audio_s": round(total_audio, 3),
        "rtf_mean": round(rtf_mean, 4),
        "rtf_corpus": round(rtf_corpus, 4),
        "rtf_p50": round(rtf_p50, 4),
        "rtf_p95": round(rtf_p95, 4),
        "lat_p50_s": round(lat_p50, 4),
        "lat_p95_s": round(lat_p95, 4),
        "delta_cpu_usage_s": round(delta_usage_usec / 1e6, 3),
        "delta_user_s": round(delta_user_usec / 1e6, 3),
        "delta_system_s": round(delta_system_usec / 1e6, 3),
        "delta_nr_periods": delta_nr_periods,
        "delta_nr_throttled": delta_nr_throttled,
        "delta_throttled_s": round(delta_throttled_usec / 1e6, 3),
        "cpu_per_audio_sec": round(cpu_per_audio_sec, 4),
        "peak_memory_mb": round(peak_mem / (1024 * 1024), 1) if peak_mem > 0 else None,
    }

    print("\n--- RESULTS ---")
    for k, v in report.items():
        print(f"  {k}: {v}")

    out_file = os.environ.get("BENCH_OUT", "")
    if out_file:
        with open(out_file, "w") as f:
            json.dump({"report": report, "records": records}, f, indent=2)
        print(f"Saved report to {out_file}")

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    run_bench(count)
