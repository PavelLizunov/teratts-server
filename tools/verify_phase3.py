import urllib.request
import urllib.error
import json
import time
import hashlib
import sys
import os

token = os.environ.get("TERATTS_TOKEN")
if not token:
    # Read from /etc/teratts/teratts.env if local
    try:
        with open("/etc/teratts/teratts.env") as f:
            for line in f:
                if line.startswith("TERATTS_BEARER_TOKEN="):
                    token = line.split("=")[1].strip()
    except Exception:
        pass

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        headers_dict = dict(resp.headers)
        status = resp.status
    dt = time.perf_counter() - t0
    return status, body, headers_dict, dt

# 1. Test POST /prepare with Markdown
md_text = (
    "# Отчет о внедрении\n\n"
    "Сервер работает в режиме `Profile D`. Подробности: [ссылка](http://docs.local).\n\n"
    "| Параметр | Значение |\n"
    "|---|---|\n"
    "| spinning | 0 |\n\n"
    "- [x] Проверить парсер\n"
    "- [ ] Запустить тест"
)

st, body, hdrs, dt = post("http://127.0.0.1:8089/prepare", {
    "text": md_text,
    "input_format": "markdown",
    "language": "ru"
})
res = json.loads(body)
print("=== 1. POST /prepare Happy Path ===")
print(f"HTTP status: {st}, latency: {dt*1000:.2f}ms")
print("Prepared text:", res.get("text"))
print("Revision:", res.get("preparation_revision"), "warnings:", res.get("warnings"))
assert res.get("output_format") == "plain"
assert "Отчет о внедрении." in res.get("text")
assert "Выполнено: Проверить парсер." in res.get("text")
assert "В планах: Запустить тест." in res.get("text")

# 2. Test empty input
st_empty, body_empty, _, _ = post("http://127.0.0.1:8089/prepare", {"text": "   ", "input_format": "markdown"})
res_empty = json.loads(body_empty)
print("\n=== 2. POST /prepare Empty Input ===")
print("Text:", repr(res_empty.get("text")), "warnings:", res_empty.get("warnings"))
assert "no_speakable_content" in res_empty.get("warnings")

# 3. Test input limit > 64 KiB
print("\n=== 3. POST /prepare Input > 64 KiB ===")
large_input = "x" * (65 * 1024)
try:
    post("http://127.0.0.1:8089/prepare", {"text": large_input, "input_format": "markdown"})
    print("ERROR: Expected failure!")
    sys.exit(1)
except urllib.error.HTTPError as e:
    print(f"Correctly rejected with HTTP {e.code}: {e.read().decode()}")
    assert e.code == 400

# 4. Test Plain-path bitwise regression against production 8088
print("\n=== 4. Plain-Path Bitwise Regression (8088 vs 8089) ===")
plain_payload = {
    "text": "Сегодня двадцать первое сентября, температура воздуха составляет плюс двадцать два градуса.",
    "voice": "ru_f1",
    "duration_scale": 1.0,
    "input_format": "plain"
}
# Request to prod (8088)
_, wav_prod, _, _ = post("http://127.0.0.1:8088/tts", plain_payload)
sha_prod = hashlib.sha256(wav_prod).hexdigest()

# Request to test (8089)
_, wav_test, _, _ = post("http://127.0.0.1:8089/tts", plain_payload)
sha_test = hashlib.sha256(wav_test).hexdigest()

print(f"WAV len prod: {len(wav_prod)}, test: {len(wav_test)}")
print(f"SHA256 prod: {sha_prod}")
print(f"SHA256 test: {sha_test}")
assert sha_prod == sha_test, "Bitwise identity failed!"
print("SUCCESS: WAV output is 100% bitwise identical on Plain path!")

# 5. Test direct /tts with input_format: markdown
print("\n=== 5. Direct /tts with input_format: markdown ===")
tts_md_payload = {
    "text": "## Статус сервиса\n\nВсе компоненты **работают** штатно. Подробнее: [документация](http://example.com).",
    "voice": "ru_f1",
    "duration_scale": 1.0,
    "input_format": "markdown"
}
st_tts, wav_md, _, dt_tts = post("http://127.0.0.1:8089/tts", tts_md_payload)
print(f"HTTP status: {st_tts}, latency: {dt_tts:.3f}s, bytes: {len(wav_md)}")
assert st_tts == 200 and len(wav_md) > 10000

print("\nALL VALIDATION CHECKS PASSED!")
