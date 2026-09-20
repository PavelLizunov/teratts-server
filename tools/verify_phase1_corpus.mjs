import fs from "node:fs";
import { cleanMarkdown, splitSpeechText } from "../dsh-plugin/lib/speech-text.js";

const token = process.env.TERATTS_TOKEN;
if (!token) {
  console.error("error: TERATTS_TOKEN environment variable is required");
  process.exit(1);
}
const endpoint = process.env.TERATTS_ENDPOINT || "https://teratts.tail9fd337.ts.net/tts";

async function synth(text, signal) {
  const started = performance.now();
  const res = await fetch(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      text,
      voice: "ru_f1",
      language: "ru",
      duration_scale: 1,
    }),
    signal,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  const elapsed = (performance.now() - started) / 1000;
  // WAV header sampleRate at 24, dataBytes at 40
  const sampleRate = buf.readUInt32LE(24);
  const dataBytes = buf.readUInt32LE(40);
  const duration = dataBytes / (sampleRate * 2);
  const rev = res.headers.get("x-teratts-synthesis-revision");
  return { elapsed, duration, bytes: buf.length, rev };
}

// 1. TTFA Warmup & 20 runs
console.log("--- 1. HTTP FULL-RESPONSE LATENCY (FIRST CHUNK <= 140 CHARS, N=20) ---");
const firstChunkText = "Сегодня мы проверяем скорость первого отклика.";
// Warmup run
await synth(firstChunkText);

const ttfaRuns = [];
for (let i = 0; i < 20; i++) {
  // Use unique suffix to prevent server or proxy side caching
  const text = `${firstChunkText} Прогон номер ${i + 1}.`;
  const res = await synth(text);
  ttfaRuns.push(res.elapsed);
  process.stdout.write(`.`);
}
console.log("");
ttfaRuns.sort((a, b) => a - b);
const p50 = ttfaRuns[Math.floor((ttfaRuns.length - 1) * 0.50)];
const p95 = ttfaRuns[Math.floor((ttfaRuns.length - 1) * 0.95)];
const max = ttfaRuns[ttfaRuns.length - 1];
console.log(`HTTP full_response_ms (s): p50=${p50.toFixed(3)}s, p95=${p95.toFixed(3)}s, max=${max.toFixed(3)}s`);

// 2. Concurrency measurement: manual click during active background synthesis
console.log("\n--- 2. CONCURRENCY: DIRECT HTTP CALL DURING IN-FLIGHT SYNTHESIS ---");
const longBgText = "Фоновый синтез длинного блока для создания активной очереди на сервере. ".repeat(4);
const bgPromise = synth(longBgText);
// Wait 150ms so background request definitely arrives and acquires admission
await new Promise(r => setTimeout(r, 150));
const fgStart = performance.now();
const fgRes = await synth("Ручной клик пользователя во время фонового расчета.");
const fgElapsed = (performance.now() - fgStart) / 1000;
await bgPromise;
console.log(`Direct HTTP call during in-flight background: ${fgElapsed.toFixed(3)}s (queued until active subchunk finishes)`);

// 3. Corpus continuous playback simulation (800, 2000, 4000 chars)
console.log("\n--- 3. MODEL-BASED BUFFER CONTINUITY SIMULATION (800, 2000, 4000 chars) ---");
console.log("(Note: Evaluates mathematical buffer depletion based on measured generation times, not live AudioContext output)");

const corpus800 = `
В данном отчете рассматриваются результаты первичного аудита инфраструктуры.
Было выявлено несколько ключевых факторов, влияющих на задержку генерации аудио.
В частности, процесс синтеза включает этапы текстового кодирования, предсказания длительности,
диффузионного сэмплирования и вокодера.
Для обеспечения непрерывного воспроизведения аудиопотока в браузере требуется,
чтобы каждый последующий фрагмент поступал до момента завершения проигрывания накопленного буфера.
`.repeat(2).trim();

const corpus2000 = `
## Архитектурный обзор подсистемы генерации речи TeraTTS

Подсистема TeraTTSv2 представляет собой высокопроизводительный сервер синтеза речи на базе ONNX Runtime.
Архитектура включает четыре последовательных графа нейросетей:
1. Текстовый энкодер преобразует токены символов в векторное представление с учетом стиля голоса.
2. Предиктор длительности вычисляет временные интервалы для каждого элемента речи.
3. Восьмишаговый сэмплер генерирует латентные фреймы методом диффузии с коэффициентом гайданса три.
4. Вокодер декодирует сжатые латентные представления в линейную волновую форму звука с частотой дискретизации сорок четыре килогерца.

### Оптимизация буферизации
Ранее клиентский веб-плагин выполнял нарезку крупными блоками до восьмисот символов.
Это приводило к тому, что клиент ожидал генерации неделимого аудиофайла более пятнадцати секунд.
В новой схеме нарезки первый чанк ограничен ста сорока символами, второй — двумястами сорока,
а последующие — тремястами двадцатью символами.
Благодаря этому задержка до старта воспроизведения снижается до полутора секунд,
а последующие фрагменты поступают значительно быстрее, чем заканчивается звучание предыдущего буфера.
`.repeat(2).trim();

const corpus4000 = `${corpus2000}\n\n${corpus2000}`;

async function evaluateContinuity(name, rawText, rates = [1.0, 1.25, 2.0]) {
  const cleaned = cleanMarkdown(rawText);
  const chunks = splitSpeechText(cleaned);
  console.log(`\nEvaluating: ${name} (raw chars: ${rawText.length}, cleaned: ${cleaned.length}, chunks: ${chunks.length})`);
  console.log(`Chunk lengths: ${chunks.map(c => c.length).join(", ")}`);

  // Synthesize each chunk and record generation time & audio duration
  const profiles = [];
  for (let i = 0; i < chunks.length; i++) {
    const res = await synth(chunks[i]);
    profiles.push(res);
    process.stdout.write(`[c${i}: G=${res.elapsed.toFixed(2)}s D=${res.duration.toFixed(2)}s] `);
  }
  console.log("");

  for (const rate of rates) {
    let buffer = profiles[0].duration / rate; // initial buffer after chunk 0
    let underrunCount = 0;
    let totalPauseSeconds = 0;
    let minBuffer = buffer;

    for (let i = 1; i < profiles.length; i++) {
      const genTime = profiles[i].elapsed;
      const playDuration = profiles[i].duration / rate;

      if (buffer < genTime) {
        // Underrun! Player ran out of audio while waiting for chunk i
        underrunCount++;
        const pause = genTime - buffer;
        totalPauseSeconds += pause;
        buffer = playDuration; // starts fresh after pause
        minBuffer = 0;
      } else {
        buffer = (buffer - genTime) + playDuration;
        minBuffer = Math.min(minBuffer, buffer - playDuration);
      }
    }

    console.log(`  Rate ${rate.toFixed(2)}x: underruns=${underrunCount}, total_pause=${totalPauseSeconds.toFixed(2)}s, min_buffer=${minBuffer.toFixed(2)}s`);
  }
}

await evaluateContinuity("Corpus 800 chars", corpus800);
await evaluateContinuity("Corpus 2000 chars", corpus2000);
await evaluateContinuity("Corpus 4000 chars", corpus4000);
