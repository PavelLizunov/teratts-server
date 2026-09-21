import { performance } from "node:perf_hooks";

const token = process.env.TERATTS_TOKEN;
if (!token) {
  console.error("error: TERATTS_TOKEN environment variable is required");
  process.exit(1);
}

const endpoint = process.env.TERATTS_ENDPOINT || "https://teratts.tail9fd337.ts.net/tts";

async function synth(text, voice = "ru_f1") {
  const started = performance.now();
  const res = await fetch(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      text,
      voice,
      language: "ru",
      duration_scale: 1,
    }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  const elapsed = (performance.now() - started) / 1000;
  const sampleRate = buf.readUInt32LE(24);
  const dataBytes = buf.readUInt32LE(40);
  const duration = dataBytes / (sampleRate * 2);
  return { elapsed, duration, bytes: buf.length };
}

// Fixed test sentences: 1 short, 1 medium, 1 long
const testPhrases = [
  "Сегодня мы проверяем скорость первого отклика.",
  "В данном отчете рассматриваются результаты первичного аудита инфраструктуры серверов синтеза речи.",
  "Подсистема представляет собой высокопроизводительный сервер синтеза речи на базе ONNX Runtime с поддержкой causal overlap-save streaming.",
];

console.log(`Starting benchmark against ${endpoint}...`);

// Warmup
for (const phrase of testPhrases) {
  await synth(phrase);
}

const results = [];
for (let run = 0; run < 15; run++) {
  for (let idx = 0; idx < testPhrases.length; idx++) {
    const text = `${testPhrases[idx]} Прогон ${run + 1}.`;
    const res = await synth(text);
    results.push({ run, idx, elapsed: res.elapsed, duration: res.duration, rtf: res.elapsed / res.duration });
    process.stdout.write(`.`);
  }
}
console.log("\nDone.");

const rtfs = results.map(r => r.rtf).sort((a, b) => a - b);
const p50 = rtfs[Math.floor((rtfs.length - 1) * 0.50)];
const p95 = rtfs[Math.floor((rtfs.length - 1) * 0.95)];
const avg = rtfs.reduce((sum, v) => sum + v, 0) / rtfs.length;

console.log(`Results: N=${results.length}, RTF avg=${avg.toFixed(3)}, p50=${p50.toFixed(3)}, p95=${p95.toFixed(3)}`);
