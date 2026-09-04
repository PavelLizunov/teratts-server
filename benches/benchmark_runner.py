#!/usr/bin/env python3
"""
Benchmark runner for teratts-server profiler-guided optimization.
Runs repeatable uninstrumented benchmarks measuring end-to-end synthesis latency.
"""
import sys
import time
import json
import subprocess
import urllib.request
import urllib.error
import os
import signal

SERVER_BIN = os.path.abspath("target/release/teratts-server")
PORT = 8089
BASE_URL = f"http://127.0.0.1:{PORT}"
TOKEN = "benchmark_secret_token_12345678"

CORPUS = [
    # Short sentence (dialogue)
    {"text": "Привет! Как твои дела сегодня?", "voice": "ru_f1"},
    # Medium sentence with numbers and dates
    {"text": "Сегодня 4 сентября 2026 года, температура воздуха составляет 22 градуса Цельсия.", "voice": "ru_f1"},
    # Long paragraph requiring multi-chunk synthesis
    {"text": "Искусственный интеллект и синтез речи развиваются стремительными темпами. "
             "Современные нейросетевые модели способны генерировать естественный голос, "
             "неотличимый от человеческого, с правильной интонацией и расстановкой ударений.", "voice": "ru_f1"},
]

def wait_for_server(proc, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            raise RuntimeError(f"Server exited prematurely with code {proc.returncode}:\nSTDOUT:\n{stdout.decode()}\nSTDERR:\n{stderr.decode()}")
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            with urllib.request.urlopen(req, timeout=1) as resp:
                data = json.loads(resp.read().decode())
                # When listening, server returns 200 (ready) or 503 (ready=false before sha or verification)
                # But once port is open and listening, ruaccent load is complete!
                if "sample_rate" in data:
                    return
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode())
                if "sample_rate" in data:
                    return
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("Server failed to become ready within timeout")

def run_single_request(item):
    payload = json.dumps({
        "text": item["text"],
        "voice": item["voice"],
        "duration_scale": 1.0,
        "speech_front": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/tts",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}"
        }
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        audio_bytes = resp.read()
    elapsed = time.perf_counter() - t0
    # Sanity check: valid WAV header (RIFF....WAVE)
    if len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise ValueError(f"Invalid WAV received, size={len(audio_bytes)}")
    return elapsed, len(audio_bytes)

def run_benchmark(warmup_runs=1, measured_runs=3):
    env = os.environ.copy()
    env["TERATTS_BEARER_TOKEN"] = TOKEN
    env["TERATTS_ORT_THREADS"] = "4"
    env["TERATTS_PARALLEL_CHUNKS"] = "1"
    env["TERATTS_RUACCENT_MODE"] = "full"
    env["LD_LIBRARY_PATH"] = f"/var/lib/dsh/.cache/ort/onnxruntime-linux-x64-1.27.0/lib:{env.get('LD_LIBRARY_PATH', '')}"

    proc = subprocess.Popen(
        [SERVER_BIN, "--serve", "--port", str(PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )

    try:
        wait_for_server(proc)

        # Warmup
        for _ in range(warmup_runs):
            for item in CORPUS:
                run_single_request(item)

        # Measured runs
        timings = []
        for _ in range(measured_runs):
            corpus_time = 0.0
            for item in CORPUS:
                t, _ = run_single_request(item)
                corpus_time += t
            timings.append(round(corpus_time, 4))

        return timings
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

if __name__ == "__main__":
    timings = run_benchmark()
    print(json.dumps({"timings": timings, "mean": round(sum(timings)/len(timings), 4)}))
