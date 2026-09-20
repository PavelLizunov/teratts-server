const STRUCTURAL = /^\s{0,3}#{1,6}\s|^\s*>|^\s*[-*+]\s|^\s*\d+[.)]\s/;
const ALLOWED_CHARS = /[^\p{Script=Cyrillic}a-zA-Z0-9\s.,:;!?\-\u2014\u2013…()\[\]{}«»“”„’"\/\\_+#@%=&~$*|^<>→⇒←⇐↔⇔↑↓≈≤≥≠×÷±−₽€£¥]/gu;

function cleanLine(line) {
  return line
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)/g, "$1")
    .replace(/\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/g, "")
    .replace(/^\s*>\s?/g, "")
    .replace(/^\s*[-*+]\s+\[[ xX]\]\s+/g, "")
    .replace(/^\s*[-*+]\s+/g, "")
    .replace(/^\s*\d{1,3}[.)]\s+/g, "")
    .replace(/[*~]/g, "")
    .replace(/_/g, " ")
    // Strip only syntactically valid HTML-like tags while preserving exact Tera <ru>/<en> language tags.
    .replace(/<(?!\/?(?:ru|en)>)(?:\/?[a-z][a-z0-9:-]*)(?:\s+[^<>]*?)?\/?\s*>/gi, " ")
    // Convert math and code comparison operators into speakable words
    // so raw `<` does not trigger server language-tag validation failure.
    .replace(/<=\s*/g, " меньше или равно ")
    .replace(/<(?!\/?(?:ru|en)>)\s*/g, " меньше ")
    .replace(/>=\s*/g, " больше или равно ")
    .replace(/(?<!<\/?(?:ru|en))>\s*/g, " больше ")
    .replace(ALLOWED_CHARS, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanCodeBlock(body) {
  return body
    .split("\n")
    .map((line) =>
      cleanLine(line).replace(/[{}\[\]();"]/g, " ").replace(/\s+/g, " ").trim(),
    )
    .filter(Boolean)
    .map((line) => (/[.!?…:]$/.test(line) ? line : `${line}.`))
    .join(" ");
}

function sanitizeLanguageTags(text) {
  const tagRegex = /<\/?(ru|en)>/gi;
  const matches = [...text.matchAll(tagRegex)];
  if (matches.length === 0) return text;

  const validPairs = new Set();
  let openTag = null;

  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    const isClosing = m[0][1] === "/";
    const lang = m[1].toLowerCase();

    if (!isClosing) {
      if (openTag === null) {
        openTag = { index: i, lang };
      }
    } else {
      if (openTag !== null && openTag.lang === lang) {
        validPairs.add(openTag.index);
        validPairs.add(i);
        openTag = null;
      }
    }
  }

  let result = "";
  let lastPos = 0;
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    result += text.slice(lastPos, m.index);
    if (validPairs.has(i)) {
      result += m[0].toLowerCase();
    } else {
      const isClosing = m[0][1] === "/";
      const lang = m[1].toLowerCase();
      const prevChar = text[m.index - 1] || "";
      const nextChar = text[m.index + m[0].length] || "";
      const leadSpace = prevChar && !/\s/.test(prevChar) ? " " : "";
      const trailSpace = nextChar && !/\s|[.,!?:;…]/.test(nextChar) ? " " : "";
      result += `${leadSpace}${isClosing ? `/${lang}` : lang}${trailSpace}`;
    }
    lastPos = m.index + m[0].length;
  }
  result += text.slice(lastPos);
  return result;
}

function cleanMarkdown(text) {
  const unified = text
    .replace(/\r/g, "")
    .replace(/```[^\n]*\n([\s\S]*?)```/g, (_fence, body) => `\n${cleanCodeBlock(body)}\n`)
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      // Markdown tables: read rows as "key, value."; drop separator rows.
      if (trimmed.startsWith("|")) {
        if (/^[\s|:\-–—]+$/.test(trimmed)) return "";
        const cells = trimmed
          .split("|")
          .map((c) => cleanLine(c))
          .filter(Boolean);
        return cells.length ? cells.join(", ") + "." : "";
      }
      const structural = STRUCTURAL.test(line);
      const cleaned = cleanLine(line);
      if (!cleaned) return "";
      // Headings/list items/quotes are separate thoughts: give the TTS a
      // sentence boundary so it pauses instead of running them together.
      if (structural && !/[.!?…:](?:<\/ru>)?$/.test(cleaned)) return cleaned + ".";
      return cleaned;
    })
    .filter(Boolean)
    .join(" ")
    .replace(/\s*→\s*/g, ", ")
    .replace(/\s*×\s*/g, ", ")
    .replace(/\s+/g, " ")
    .trim();
  return sanitizeLanguageTags(unified).replace(/\s+/g, " ").trim();
}

const FIRST_SPEECH_CHUNK_CHARS = 140;
const SPEECH_RPC_TIMEOUT_MS = 65_000;

// Bound client waiting too: the Host timeout cannot settle a lost RPC response.
function synthesizeWithDeadline(voice, text, parentSignal, timeoutMs = SPEECH_RPC_TIMEOUT_MS) {
  if (parentSignal.aborted) return Promise.reject(parentSignal.reason);
  const controller = new AbortController();
  return new Promise((resolve, reject) => {
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      parentSignal.removeEventListener("abort", cancel);
    };
    const cancel = () => {
      cleanup();
      controller.abort(parentSignal.reason);
      reject(parentSignal.reason);
    };
    parentSignal.addEventListener("abort", cancel, { once: true });
    timer = setTimeout(() => {
      cleanup();
      const error = new Error("Speech request timed out; try again");
      controller.abort(error);
      reject(error);
    }, timeoutMs);
    try {
      Promise.resolve(voice.synthesize(text, controller.signal)).then(
        value => { cleanup(); resolve(value); },
        error => { cleanup(); reject(error); },
      );
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}
const SECOND_SPEECH_CHUNK_CHARS = 240;
const SPEECH_CHUNK_CHARS = 320;
const MAX_STREAMED_AUDIO_BYTES = 256 * 1024 * 1024; // 256 MiB (~45 minutes of speech)

function speechChunkLimits(options, laterMaxChars) {
  let firstChars = FIRST_SPEECH_CHUNK_CHARS;
  let secondChars = SECOND_SPEECH_CHUNK_CHARS;
  let nextChars = SPEECH_CHUNK_CHARS;
  if (typeof options === "number") {
    firstChars = options;
    secondChars = options;
    nextChars = laterMaxChars ?? options;
  } else if (options !== undefined) {
    if (options === null || typeof options !== "object") {
      throw new RangeError("invalid speech chunk size");
    }
    firstChars = options.firstChars ?? firstChars;
    secondChars = options.secondChars ?? (options.firstChars ? Math.max(firstChars, options.nextChars ?? nextChars) : secondChars);
    nextChars = options.nextChars ?? nextChars;
  }
  if (!Number.isInteger(firstChars) || firstChars < 1) {
    throw new RangeError("invalid speech chunk size");
  }
  if (!Number.isInteger(nextChars) || nextChars < 1) {
    throw new RangeError("invalid speech chunk size");
  }
  return { firstChars, secondChars, nextChars };
}

function speechLanguageSpans(text) {
  const spans = [];
  const tags = /<\/?(ru|en)>/gi;
  let active = null;
  let cursor = 0;
  let contentStart = 0;
  let match;
  while ((match = tags.exec(text)) !== null) {
    const closing = match[0][1] === "/";
    const language = match[1].toLowerCase();
    if (!closing) {
      if (active) throw new TypeError("nested TeraTTS language tags are not supported");
      if (match.index > cursor) spans.push({ language: null, text: text.slice(cursor, match.index) });
      active = language;
      contentStart = tags.lastIndex;
    } else {
      if (active !== language) throw new TypeError("unbalanced TeraTTS language tags");
      spans.push({ language, text: text.slice(contentStart, match.index) });
      active = null;
      cursor = tags.lastIndex;
    }
  }
  if (active) throw new TypeError("unbalanced TeraTTS language tags");
  if (cursor < text.length) spans.push({ language: null, text: text.slice(cursor) });
  return spans.length ? spans : [{ language: null, text }];
}

function nextSpeechCut(text, maxChars) {
  if (text.length <= maxChars) return text.length;
  const window = text.slice(0, maxChars + 1);
  let cut = Math.max(
    window.lastIndexOf(". "),
    window.lastIndexOf("! "),
    window.lastIndexOf("? "),
    window.lastIndexOf("… "),
    window.lastIndexOf(": "),
  );
  if (cut >= Math.floor(maxChars / 2)) cut += 1;
  else cut = window.lastIndexOf(" ", maxChars);
  if (cut < 1) cut = maxChars;
  const before = text.charCodeAt(cut - 1);
  const after = text.charCodeAt(cut);
  if (before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff) cut -= 1;
  return Math.max(1, cut);
}

function splitSpeechText(text, options, laterMaxChars) {
  const { firstChars, secondChars, nextChars } = speechChunkLimits(options, laterMaxChars);
  const chunks = [];
  for (const span of speechLanguageSpans(text.trim())) {
    let rest = span.text.trim();
    while (rest) {
      let limit = nextChars;
      if (chunks.length === 0) limit = firstChars;
      else if (chunks.length === 1 && firstChars < secondChars && secondChars <= nextChars) {
        limit = secondChars;
      }
      const wrapperChars = span.language ? 9 : 0;
      const contentLimit = limit - wrapperChars;
      if (contentLimit < 1) throw new RangeError("speech chunk size is too small for language tags");
      const cut = nextSpeechCut(rest, contentLimit);
      const content = rest.slice(0, cut).trim();
      if (content) {
        chunks.push(
          span.language ? `<${span.language}>${content}</${span.language}>` : content,
        );
      }
      rest = rest.slice(cut).trim();
    }
  }
  return chunks;
}

function inspectMonoPcmWav(bytes, expectedFormat) {
  if (!(bytes instanceof Uint8Array) || bytes.length < 44) {
    throw new TypeError("invalid WAV chunk");
  }
  const tag = (offset) => String.fromCharCode(...bytes.subarray(offset, offset + 4));
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const sampleRate = view.getUint32(24, true);
  const dataBytes = view.getUint32(40, true);
  const valid =
    tag(0) === "RIFF" &&
    tag(8) === "WAVE" &&
    tag(12) === "fmt " &&
    tag(36) === "data" &&
    view.getUint32(4, true) === bytes.length - 8 &&
    view.getUint32(16, true) === 16 &&
    view.getUint16(20, true) === 1 &&
    view.getUint16(22, true) === 1 &&
    sampleRate > 0 &&
    view.getUint32(28, true) === sampleRate * 2 &&
    view.getUint16(32, true) === 2 &&
    view.getUint16(34, true) === 16 &&
    dataBytes === bytes.length - 44 &&
    dataBytes % 2 === 0;
  if (!valid) throw new TypeError("unsupported WAV chunk");
  if (expectedFormat) {
    for (let index = 20; index < 36; index += 1) {
      if (bytes[index] !== expectedFormat[index - 20]) {
        throw new TypeError("WAV formats do not match");
      }
    }
  }
  return {
    dataBytes,
    duration: dataBytes / (sampleRate * 2),
    format: bytes.slice(20, 36),
    payload: bytes.subarray(44),
  };
}

function checkedWavBytes(totalBytes, dataBytes, maxBytes = MAX_STREAMED_AUDIO_BYTES) {
  if (dataBytes > maxBytes - totalBytes) throw new RangeError("Speech audio is too large");
  return totalBytes + dataBytes;
}

function locateBufferedTime(durations, time) {
  if (!Array.isArray(durations) || durations.length === 0) return null;
  const total = durations.reduce(
    (sum, duration) => sum + (Number.isFinite(duration) && duration > 0 ? duration : 0),
    0,
  );
  const target = Math.max(0, Math.min(Number.isFinite(time) ? time : 0, total));
  let elapsed = 0;
  for (let index = 0; index < durations.length; index += 1) {
    const duration = Number.isFinite(durations[index]) && durations[index] > 0 ? durations[index] : 0;
    if (target < elapsed + duration || index === durations.length - 1) {
      return { index, offset: Math.min(duration, target - elapsed), target, total };
    }
    elapsed += duration;
  }
  return null;
}

const PLAYBACK_RATES = [1, 1.25, 1.5, 2];

function nextPlaybackRate(currentRate) {
  const index = PLAYBACK_RATES.indexOf(currentRate);
  if (index === -1) return PLAYBACK_RATES[0];
  return PLAYBACK_RATES[(index + 1) % PLAYBACK_RATES.length];
}

function clampSeekTime(currentTime, offset, duration) {
  if (typeof duration !== "number" || !Number.isFinite(duration) || duration <= 0) {
    return typeof currentTime === "number" && Number.isFinite(currentTime) ? currentTime : 0;
  }
  const cur = typeof currentTime === "number" && Number.isFinite(currentTime) ? currentTime : 0;
  const target = cur + offset;
  return Math.max(0, Math.min(duration, target));
}

// Test-only export: never expose helpers in the production browser global.
if (typeof process !== "undefined" && process.versions?.node) {
  globalThis.__teratts_cleanMarkdown = cleanMarkdown;
  globalThis.__teratts_PLAYBACK_RATES = PLAYBACK_RATES;
  globalThis.__teratts_nextPlaybackRate = nextPlaybackRate;
  globalThis.__teratts_clampSeekTime = clampSeekTime;
  globalThis.__teratts_splitSpeechText = splitSpeechText;
  globalThis.__teratts_inspectMonoPcmWav = inspectMonoPcmWav;
  globalThis.__teratts_locateBufferedTime = locateBufferedTime;
}

if (typeof window !== "undefined" && window.__ModuleLoader__?.load) {
window.__ModuleLoader__.load({
  id: "dsh-client-ui-teratts",
  factory: (require) => {
    const module = { exports: {} };
    const React = require("react");
    const {
      IconLoadingOutline16,
      IconStopFill16,
      Toast,
      Tooltip,
    } = require("@deepseek-ai/dsh-client-ui-primitives");

    const textSchema = {
      parse(value) {
        if (typeof value !== "string") throw new TypeError("text must be a string");
        return value;
      },
    };
    const audioSchema = {
      parse(value) {
        if (
          value === null ||
          typeof value !== "object" ||
          typeof value.audioBase64 !== "string" ||
          typeof value.mimeType !== "string"
        ) {
          throw new TypeError("invalid TeraTTS audio response");
        }
        return value;
      },
    };

    const anySchema = {
      parse(value) {
        return value;
      },
    };

    const REMOTE = {
      package: "dsh-client-ui-teratts",
      descriptors: [
        {
          id: "dsh-client-ui-teratts#terattsVoice/synthesize",
          service: "terattsVoice",
          namespace: "terattsVoice",
          method: "synthesize",
          invocation: { kind: "direct" },
          parameters: [
            {
              name: "text",
              wire: "text",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/synthesize:text",
                schema: textSchema,
              },
            },
          ],
          cancellation: { parameter: "signal" },
          result: {
            mode: "strict",
            typeSymbol: "dsh-client-ui-teratts#terattsVoice/synthesize:result",
            schema: audioSchema,
          },
        },
        {
          id: "dsh-client-ui-teratts#terattsVoice/acquireForeground",
          service: "terattsVoice",
          namespace: "terattsVoice",
          method: "acquireForeground",
          invocation: { kind: "direct" },
          parameters: [
            {
              name: "ownerId",
              wire: "ownerId",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/acquireForeground:ownerId",
                schema: textSchema,
              },
            },
            {
              name: "epoch",
              wire: "epoch",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/acquireForeground:epoch",
                schema: anySchema,
              },
            },
          ],
          result: {
            mode: "strict",
            typeSymbol: "dsh-client-ui-teratts#terattsVoice/acquireForeground:result",
            schema: anySchema,
          },
        },
        {
          id: "dsh-client-ui-teratts#terattsVoice/renewForeground",
          service: "terattsVoice",
          namespace: "terattsVoice",
          method: "renewForeground",
          invocation: { kind: "direct" },
          parameters: [
            {
              name: "ownerId",
              wire: "ownerId",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/renewForeground:ownerId",
                schema: textSchema,
              },
            },
            {
              name: "epoch",
              wire: "epoch",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/renewForeground:epoch",
                schema: anySchema,
              },
            },
          ],
          result: {
            mode: "strict",
            typeSymbol: "dsh-client-ui-teratts#terattsVoice/renewForeground:result",
            schema: anySchema,
          },
        },
        {
          id: "dsh-client-ui-teratts#terattsVoice/releaseForeground",
          service: "terattsVoice",
          namespace: "terattsVoice",
          method: "releaseForeground",
          invocation: { kind: "direct" },
          parameters: [
            {
              name: "ownerId",
              wire: "ownerId",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/releaseForeground:ownerId",
                schema: textSchema,
              },
            },
            {
              name: "epoch",
              wire: "epoch",
              source: "json",
              codec: {
                mode: "strict",
                typeSymbol: "dsh-client-ui-teratts#terattsVoice/releaseForeground:epoch",
                schema: anySchema,
              },
            },
          ],
          result: {
            mode: "strict",
            typeSymbol: "dsh-client-ui-teratts#terattsVoice/releaseForeground:result",
            schema: anySchema,
          },
        },
      ],
    };

    const styleId = "dsh-client-ui-teratts/action";
    if (!document.querySelector(`style[data-plugin-css=${JSON.stringify(styleId)}]`)) {
      const style = document.createElement("style");
      style.dataset.plugin = "dsh-client-ui-teratts";
      style.dataset.pluginCss = styleId;
      style.textContent = ".teratts-action{width:28px;height:28px;color:var(--dsw-alias-label-tertiary);cursor:pointer;background:0 0;border:none;border-radius:28px;justify-content:center;align-items:center;padding:4px;display:inline-flex}.teratts-action:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}.teratts-action:disabled{cursor:default;opacity:.5}.teratts-action[data-active]{color:var(--dsw-alias-label-primary)}.teratts-loading{animation:teratts-spin 1s linear infinite}@keyframes teratts-spin{to{transform:rotate(360deg)}}";
      style.textContent += '[class*="_actions"]:has(.teratts-player){height:auto!important;min-height:calc(28px + var(--dsh-content-font-delta,0px));overflow:visible!important;flex-wrap:wrap!important;align-items:flex-start!important}';
      style.textContent += ".teratts-player{flex-basis:100%;width:100%;max-width:440px;order:10;margin:6px 0 2px 0;padding:8px 12px 6px 12px;background:var(--dsw-alias-bubble-secondary,rgba(125,125,125,0.08));border:1px solid var(--dsw-alias-border-l3,rgba(125,125,125,0.18));border-radius:14px;display:flex;flex-direction:column;gap:6px;box-sizing:border-box}";
      style.textContent += ".teratts-main-row{display:flex;align-items:center;gap:10px;width:100%}.teratts-play-btn{width:36px;height:36px;min-width:36px;border-radius:50%;corner-shape:round;background:var(--dsw-alias-label-primary,#000);color:var(--dsw-alias-label-primary-foreground,var(--dsw-alias-bg-base,#fff));border:none;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;padding:0;transition:transform .1s ease,opacity .1s ease}.teratts-play-btn:hover{opacity:.9;transform:scale(1.04)}.teratts-play-btn:active{transform:scale(.96)}.teratts-play-btn svg{width:16px;height:16px}";
      style.textContent += ".teratts-track-wrap{flex:1 1 auto;display:flex;flex-direction:column;gap:2px;min-width:0}.teratts-time-row{display:flex;justify-content:space-between;align-items:center;width:100%;padding:0 1px}.teratts-time{font-size:11px;line-height:1.2;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-secondary);white-space:nowrap;flex-shrink:0}";
      style.textContent += ".teratts-sub-row{display:flex;align-items:center;justify-content:flex-end;gap:6px;width:100%;padding-top:4px;border-top:1px solid var(--dsw-alias-border-l4,rgba(125,125,125,0.08))}";
      style.textContent += ".teratts-pill-btn{height:28px;padding:0 10px;border-radius:14px;background:var(--dsw-alias-interactive-bg-subtle,rgba(125,125,125,0.08));color:var(--dsw-alias-label-secondary);border:1px solid var(--dsw-alias-border-l4,transparent);font-size:11px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;font-family:inherit;user-select:none;white-space:nowrap}.teratts-pill-btn:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}.teratts-stop-btn{color:var(--dsw-alias-label-tertiary);padding:0 8px}.teratts-stop-btn:hover{color:var(--dsw-alias-label-primary)}";
      style.textContent += ".teratts-progress{min-height:32px;cursor:pointer;accent-color:var(--dsw-alias-label-primary);margin:0}.teratts-progress{min-height:44px}.teratts-action:focus-visible,.teratts-play-btn:focus-visible,.teratts-pill-btn:focus-visible,.teratts-progress:focus-visible{outline:2px solid currentColor;outline-offset:2px}";
      style.textContent += ".teratts-pinned{position:fixed!important;left:12px!important;right:12px!important;bottom:var(--teratts-composer-offset,calc(var(--dsh-composer-height,80px) + 12px))!important;width:auto!important;max-width:440px!important;margin:0 auto!important;z-index:1000!important;box-shadow:0 8px 32px rgba(0,0,0,0.32)!important;backdrop-filter:blur(16px)!important;-webkit-backdrop-filter:blur(16px)!important;background:var(--dsw-specific-menu,rgba(28,28,30,0.92))!important;border:1px solid var(--dsw-alias-border-l1,rgba(255,255,255,0.16))!important;border-radius:16px!important;padding:10px 14px 8px 14px!important;pointer-events:auto!important;animation:teratts-pop-in .18s cubic-bezier(0.16,1,0.3,1)}@media(min-width:601px){.teratts-pinned{left:auto!important;right:24px!important;width:380px!important;margin:0!important}}@keyframes teratts-pop-in{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}";
      style.textContent += "@media(max-width:600px),(pointer:coarse){.teratts-play-btn{width:44px;height:44px;min-width:44px}.teratts-pill-btn{min-width:44px;min-height:44px;border-radius:22px;font-size:13px;padding:0 12px}}@media(prefers-reduced-motion:reduce){.teratts-loading{animation:none}}";
      document.head.appendChild(style);
    }

    function messageText(snapshot, messageId) {
      const chat = snapshot?.chat ?? snapshot;
      const legacy = chat?.legacy ?? chat;
      const nodes = legacy?.nodes ?? chat?.nodes;
      const node = nodes?.find(
        (candidate) => (candidate.kind === "assistant" || candidate.role === "assistant") && candidate.messageId === messageId,
      );
      if (!node) return "";
      const blocks = node.blocks || node.content || [];
      return cleanMarkdown(
        blocks.filter((block) => block.kind === "text" || block.type === "text").map((block) => block.text || "").join("\n"),
      );
    }

    function SpeakerIcon() {
      return React.createElement(
        "svg",
        {
          "aria-hidden": true,
          width: 16,
          height: 16,
          viewBox: "0 0 16 16",
          fill: "none",
        },
        React.createElement("path", {
          d: "M2 6.25h2.25L7.5 3.5v9L4.25 9.75H2v-3.5Zm7.1-.85a3.25 3.25 0 0 1 0 5.2M10.8 3.7a5.5 5.5 0 0 1 0 8.6",
          stroke: "currentColor",
          strokeWidth: 1.25,
          strokeLinecap: "round",
          strokeLinejoin: "round",
        }),
      );
    }

    const playback = {
      epoch: 0,
      owner: null,
      voice: null,
      heartbeatTimer: null,
      state: "idle",
      error: null,
      errorOwner: null,
      errorSeq: 0,
      abort: null,
      audio: null,
      segments: [],
      index: -1,
      bufferedBytes: 44,
      format: null,
      producerDone: false,
      listeners: new Set(),
      rate: 1,
      volume: 1,
      paused: false,
      playAttempt: 0,
      duration: 0,
      position: 0,
      complete: false,
    };

    function setPlaybackVolume(volume) {
      playback.volume = Math.max(0, Math.min(1, Number(volume) || 0));
      for (const segment of playback.segments) segment.audio.volume = playback.volume;
      publish();
    }

    function snapshot() {
      const durations = playback.segments.map((segment) => segment.duration);
      const duration = durations.reduce((sum, d) => sum + d, 0);
      const position = globalCurrentTime();
      return {
        owner: playback.owner,
        state: playback.state,
        error: playback.error,
        errorOwner: playback.errorOwner,
        errorSeq: playback.errorSeq,
        rate: playback.rate,
        volume: playback.volume,
        paused: playback.paused,
        duration,
        position,
        complete: playback.producerDone,
      };
    }

    function publish() {
      const next = snapshot();
      playback.duration = next.duration;
      playback.position = next.position;
      playback.complete = next.complete;
      for (const listener of playback.listeners) listener(next);
    }

    function togglePause() {
      if (!playback.owner) return;
      playback.paused = !playback.paused;
      if (playback.paused) {
        playback.playAttempt += 1;
        playback.audio?.pause();
        playback.state = "paused";
        publish();
      } else {
        if (playback.audio) {
          const epoch = playback.epoch;
          void playSegment(epoch, playback.index, playback.audio.currentTime).catch((error) => {
            failPlayback(epoch, error instanceof Error ? error.message : "Audio playback failed");
          });
        } else if (playback.segments.length) {
          seekPlayback(0);
        } else {
          playback.state = "loading";
          publish();
        }
      }
    }

    function seekToTime(targetTime) {
      const durations = playback.segments.map((segment) => segment.duration);
      const location = locateBufferedTime(durations, targetTime);
      if (!location) return;
      if (location.target === location.total && location.offset === durations[location.index]) {
        if (playback.producerDone) {
          playback.index = location.index;
          finishPlayback();
          return;
        }
        if (playback.audio) {
          playback.audio.onended = null;
          playback.audio.onerror = null;
          playback.audio.ontimeupdate = null;
          playback.audio.pause();
        }
        playback.index = location.index;
        playback.audio = null;
        playback.state = playback.paused ? "paused" : "loading";
        publish();
        return;
      }
      if (location.index === playback.index && playback.audio) {
        playback.audio.currentTime = location.offset;
        publish();
        return;
      }
      const epoch = playback.epoch;
      playback.index = location.index;
      void playSegment(epoch, location.index, location.offset).catch((error) => {
        failPlayback(epoch, error instanceof Error ? error.message : "Audio playback failed");
      });
      publish();
    }

    function finishPlayback() {
      playback.audio?.pause();
      playback.audio = null;
      playback.state = "ended";
      playback.paused = false;
      publish();
    }

    function setPlaybackRate(rate) {
      playback.rate = rate;
      for (const segment of playback.segments) segment.audio.playbackRate = rate;
      publish();
    }

    function cyclePlaybackRate() {
      setPlaybackRate(nextPlaybackRate(playback.rate));
    }

    function globalCurrentTime() {
      if (playback.index < 0) return 0;
      let elapsed = 0;
      for (let index = 0; index < playback.index; index += 1) {
        elapsed += playback.segments[index].duration;
      }
      const current = playback.audio
        ? playback.audio.currentTime
        : playback.segments[playback.index]?.duration || 0;
      return elapsed + current;
    }

    function disposeSegment(segment) {
      segment.audio.onended = null;
      segment.audio.onerror = null;
      segment.audio.pause();
      segment.audio.removeAttribute("src");
      segment.audio.load();
      URL.revokeObjectURL(segment.url);
    }

    function releaseMedia() {
      playback.abort?.abort();
      playback.abort = null;
      for (const segment of playback.segments) disposeSegment(segment);
      playback.audio = null;
      playback.segments = [];
      playback.index = -1;
      playback.bufferedBytes = 44;
      playback.format = null;
      playback.producerDone = false;
      playback.pendingError = null;
    }

    function stopPlayback() {
      if (playback.heartbeatTimer) {
        clearInterval(playback.heartbeatTimer);
        playback.heartbeatTimer = null;
      }
      if (playback.owner && playback.voice) {
        const ownerId = String(playback.owner.description || playback.owner);
        playback.voice.releaseForeground?.(ownerId, playback.epoch)?.catch?.(() => {});
      }
      playback.epoch += 1;
      releaseMedia();
      playback.owner = null;
      playback.voice = null;
      playback.state = "idle";
      publish();
    }

    function failPlayback(epoch, message) {
      if (epoch !== playback.epoch) return;
      if (playback.heartbeatTimer) {
        clearInterval(playback.heartbeatTimer);
        playback.heartbeatTimer = null;
      }
      if (playback.owner && playback.voice) {
        const ownerId = String(playback.owner.description || playback.owner);
        playback.voice.releaseForeground?.(ownerId, epoch)?.catch?.(() => {});
      }
      const errorOwner = playback.owner;
      playback.epoch += 1;
      releaseMedia();
      playback.owner = null;
      playback.voice = null;
      playback.state = "idle";
      playback.error = message;
      playback.errorOwner = errorOwner;
      playback.errorSeq += 1;
      publish();
    }

    function unwrapAudio(result) {
      if (result && typeof result.audioBase64 === "string") return result;
      if (result && result.ok === true && result.value) return result.value;
      if (result && result.ok === false) {
        throw new Error(result.error?.message || "Speech generation failed");
      }
      throw new TypeError("invalid TeraTTS audio response");
    }

    function decodeWavBytes(result) {
      const audio = unwrapAudio(result);
      if (audio.mimeType?.split(";", 1)[0].trim().toLowerCase() !== "audio/wav") {
        throw new TypeError("unsupported TeraTTS audio format");
      }
      if (typeof Uint8Array.fromBase64 === "function") {
        return Uint8Array.fromBase64(audio.audioBase64);
      }
      const binary = atob(audio.audioBase64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    }

    function createSegment(result) {
      const bytes = decodeWavBytes(result);
      const info = inspectMonoPcmWav(bytes, playback.format);
      const bufferedBytes = checkedWavBytes(
        playback.bufferedBytes,
        info.dataBytes,
        MAX_STREAMED_AUDIO_BYTES,
      );
      const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
      let audio;
      try {
        audio = new Audio(url);
      } catch (error) {
        URL.revokeObjectURL(url);
        throw error;
      }
      audio.preload = "auto";
      audio.playbackRate = playback.rate;
      audio.volume = playback.volume;
      playback.format ??= info.format;
      playback.bufferedBytes = bufferedBytes;
      return { audio, duration: info.duration, url };
    }

    async function playSegment(epoch, index, offset = 0) {
      if (epoch !== playback.epoch) return;
      const segment = playback.segments[index];
      if (!segment) return;
      const attempt = ++playback.playAttempt;
      if (playback.audio && playback.audio !== segment.audio) {
        playback.audio.onended = null;
        playback.audio.onerror = null;
        playback.audio.ontimeupdate = null;
        playback.audio.pause();
      }
      playback.index = index;
      playback.audio = segment.audio;
      segment.audio.playbackRate = playback.rate;
      segment.audio.volume = playback.volume;
      segment.audio.currentTime = clampSeekTime(0, offset, segment.duration);
      segment.audio.onended = () => {
        if (epoch !== playback.epoch || playback.index !== index) return;
        void advancePlayback(epoch, index);
      };
      segment.audio.onerror = () => failPlayback(epoch, "Audio playback failed");
      segment.audio.ontimeupdate = () => {
        if (epoch === playback.epoch && playback.audio === segment.audio) publish();
      };
      if (playback.paused) {
        segment.audio.pause();
        playback.state = "paused";
        publish();
        return;
      }
      try {
        await segment.audio.play();
      } catch (error) {
        if (epoch !== playback.epoch || attempt !== playback.playAttempt || playback.index !== index || playback.audio !== segment.audio) {
          return;
        }
        if (playback.paused && error?.name === "AbortError") return;
        throw error;
      }
      if (epoch !== playback.epoch || attempt !== playback.playAttempt || playback.index !== index || playback.audio !== segment.audio) {
        return;
      }
      if (playback.paused) segment.audio.pause();
      playback.state = playback.paused ? "paused" : "playing";
      publish();
    }

    async function advancePlayback(epoch, index) {
      if (epoch !== playback.epoch || playback.index !== index) return;
      const next = index + 1;
      if (next < playback.segments.length) {
        try {
          await playSegment(epoch, next);
        } catch (error) {
          failPlayback(epoch, error instanceof Error ? error.message : "Audio playback failed");
        }
        return;
      }
      playback.audio = null;
      if (playback.producerDone) {
        const pendingErr = playback.pendingError;
        if (pendingErr) failPlayback(epoch, pendingErr);
        else finishPlayback();
      } else {
        playback.state = "loading";
        publish();
      }
    }

    function seekPlayback(offset) {
      const durations = playback.segments.map((segment) => segment.duration);
      const location = locateBufferedTime(durations, globalCurrentTime() + offset);
      if (!location) return;
      if (location.target === location.total && location.offset === durations[location.index]) {
        if (playback.producerDone) {
          stopPlayback();
          return;
        }
        if (playback.audio) {
          playback.audio.onended = null;
          playback.audio.onerror = null;
          playback.audio.pause();
        }
        playback.index = location.index;
        playback.audio = null;
        playback.state = "loading";
        publish();
        return;
      }
      if (location.index === playback.index && playback.audio) {
        playback.audio.currentTime = location.offset;
        return;
      }
      const epoch = playback.epoch;
      void playSegment(epoch, location.index, location.offset).catch((error) => {
        failPlayback(epoch, error instanceof Error ? error.message : "Audio playback failed");
      });
    }

    async function startPlayback(owner, text, voice) {
      stopPlayback();
      const epoch = playback.epoch;
      const abort = new AbortController();
      const ownerId = String(owner.description || owner);
      playback.owner = owner;
      playback.voice = voice;
      playback.state = "loading";
      playback.error = null;
      playback.errorOwner = null;
      playback.abort = abort;
      publish();

      voice?.acquireForeground?.(ownerId, epoch)?.catch?.(() => {});
      playback.heartbeatTimer = setInterval(() => {
        if (playback.epoch === epoch && (playback.state === "loading" || playback.state === "playing")) {
          voice?.renewForeground?.(ownerId, epoch)?.catch?.(() => {});
        } else if (playback.heartbeatTimer) {
          clearInterval(playback.heartbeatTimer);
          playback.heartbeatTimer = null;
        }
      }, 5000);

      try {
        if (!voice) throw new Error("TeraTTS voice service is unavailable");
        const textChunks = splitSpeechText(text);
        if (textChunks.length === 0) {
          stopPlayback();
          return;
        }
        for (let index = 0; index < textChunks.length; index += 1) {
          let result;
          try {
            result = await synthesizeWithDeadline(voice, textChunks[index], abort.signal);
          } catch (chunkError) {
            if (epoch !== playback.epoch) return;
            // If audio is actively playing buffered segments, let them finish playing smoothly
            // before stopping and reporting the error, instead of brutally cutting off speech.
            if (playback.audio !== null && playback.segments.length > 0) {
              playback.producerDone = true;
              playback.pendingError =
                chunkError?.name === "AbortError"
                  ? "Request timed out"
                  : (chunkError instanceof Error ? chunkError.message : "Speech playback failed");
              publish();
              return;
            }
            throw chunkError;
          }
          if (epoch !== playback.epoch) return;
          const segment = createSegment(result);
          playback.segments.push(segment);
          if (
            index === 0 ||
            (playback.state === "loading" && playback.audio === null && playback.index + 1 === index)
          ) {
            await playSegment(epoch, index);
            if (epoch !== playback.epoch) return;
          }
        }
        playback.producerDone = true;
        playback.abort = null;
        if (!playback.audio && playback.index === playback.segments.length - 1) stopPlayback();
      } catch (error) {
        if (epoch !== playback.epoch) return;
        if (error?.name === "AbortError") {
          failPlayback(epoch, "Request timed out");
          return;
        }
        failPlayback(epoch, error instanceof Error ? error.message : "Speech playback failed");
      }
    }

    if (typeof process !== "undefined" && process.versions?.node) {
      globalThis.__teratts_playbackTestApi = {
        getPlayback: () => playback,
        seekPlayback,
        setPlaybackRate,
        startPlayback,
        stopPlayback,
      };
    }

    function usePlayback() {
      const [value, setValue] = React.useState(snapshot);
      React.useEffect(() => {
        playback.listeners.add(setValue);
        return () => playback.listeners.delete(setValue);
      }, []);
      return value;
    }

    let ReactDOM = null;
    try {
      ReactDOM = require("react-dom");
    } catch (_) {}

    function PlayIcon() {
      return React.createElement(
        "svg",
        { width: 16, height: 16, viewBox: "0 0 16 16", fill: "currentColor", "aria-hidden": true },
        React.createElement("path", { d: "M4 2.5v11L13 8z" })
      );
    }

    function PauseIcon() {
      return React.createElement(
        "svg",
        { width: 16, height: 16, viewBox: "0 0 16 16", fill: "currentColor", "aria-hidden": true },
        React.createElement("path", { d: "M3 2h4v12H3zm6 0h4v12H9z" })
      );
    }

    function formatTime(seconds) {
      const value = Math.max(0, Math.floor(seconds || 0));
      return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
    }

    function TeraTtsAction({ messageId, useChat, useSession, voice }) {
      const useTextSnapshot = useChat ?? useSession;
      const text = useTextSnapshot ? useTextSnapshot((session) => messageText(session, messageId)) : "";
      const current = usePlayback();
      const owner = React.useRef(Symbol(messageId));
      const buttonRef = React.useRef(null);
      const playerRef = React.useRef(null);
      const active = current.owner === owner.current;
      const state = active ? current.state : "idle";

      React.useEffect(
        () => () => {
          if (playback.owner === owner.current) stopPlayback();
        },
        [],
      );

      const toggle = React.useCallback(
        (e) => {
          if (e) {
            e.preventDefault();
            e.stopPropagation();
          }
          if (active) stopPlayback();
          else if (text) startPlayback(owner.current, text, voice);
        },
        [active, voice, text],
      );

      const handleSeek = React.useCallback(
        (offset) => (e) => {
          e.preventDefault();
          e.stopPropagation();
          seekPlayback(offset);
        },
        [],
      );

      const handleRate = React.useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        cyclePlaybackRate();
      }, []);

      const error =
        current.errorOwner === owner.current && current.errorSeq ? current.error : null;

      const label =
        state === "loading"
          ? "Generating speech"
          : "Read response aloud";

      const actionButton = React.createElement(
        React.Fragment,
        null,
        React.createElement(
          Tooltip,
          { label, side: "bottom" },
          React.createElement(
            "button",
            {
              ref: buttonRef,
              type: "button",
              className: "teratts-action",
              "aria-label": label,
              "aria-busy": state === "loading" || undefined,
              "data-active": active || undefined,
              disabled: !text,
              onClick: toggle,
            },
            state === "loading"
              ? React.createElement(IconLoadingOutline16, { className: "teratts-loading" })
              : React.createElement(SpeakerIcon),
          ),
        ),
        error &&
          React.createElement(Toast, {
            key: current.errorSeq,
            text: error,
            anchor: buttonRef.current,
            onDone: () => {
              if (playback.errorSeq === current.errorSeq) {
                playback.error = null;
                playback.errorOwner = null;
                publish();
              }
            },
          }),
      );

      if (!active) {
        return actionButton;
      }

      const rateText = `${current.rate || 1}×`;
      const playerCard = React.createElement(
        "div",
        {
          ref: playerRef,
          className: "teratts-player teratts-card teratts-pinned",
          role: "region",
          "aria-label": "Speech player",
        },
        React.createElement(
          "div",
          { className: "teratts-main-row" },
          React.createElement(
            "button",
            {
              type: "button",
              className: "teratts-play-btn",
              "aria-label": state === "ended" ? "Replay speech" : current.paused ? "Resume speech" : "Pause speech",
              title: state === "ended" ? "Replay speech" : current.paused ? "Resume speech" : "Pause speech",
              onClick: (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (state === "ended") void startPlayback(owner.current, text, voice);
                else togglePause();
              },
            },
            React.createElement(current.paused || state === "ended" ? PlayIcon : PauseIcon),
          ),
          React.createElement(
            "div",
            { className: "teratts-track-wrap" },
            React.createElement("input", {
              type: "range",
              className: "teratts-progress",
              min: 0,
              max: current.duration || 0,
              step: 0.1,
              value: Math.min(current.position, current.duration),
              disabled: !current.duration,
              "aria-label": "Seek within generated audio",
              onClick: (e) => e.stopPropagation(),
              onInput: (e) => {
                e.stopPropagation();
                seekToTime(Number(e.target.value));
              },
              onChange: (e) => {
                e.stopPropagation();
                seekToTime(Number(e.target.value));
              },
            }),
            React.createElement(
              "div",
              { className: "teratts-time-row" },
              React.createElement("span", { className: "teratts-time" }, formatTime(current.position)),
              React.createElement(
                "span",
                { className: "teratts-time" },
                `${formatTime(current.duration)}${current.complete ? "" : " · generating"}`,
              ),
            ),
          ),
        ),
        React.createElement(
          "div",
          { className: "teratts-sub-row" },
          React.createElement(
            "button",
            {
              type: "button",
              className: "teratts-pill-btn",
              "aria-label": "Rewind 10 seconds",
              title: "Rewind 10 seconds (Alt+Left)",
              onClick: handleSeek(-10),
            },
            "-10s",
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "teratts-pill-btn",
              "aria-label": `Playback speed ${rateText}`,
              title: `Playback speed ${rateText}`,
              onClick: handleRate,
            },
            rateText,
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "teratts-pill-btn",
              "aria-label": "Fast forward 15 seconds",
              title: "Fast forward 15 seconds (Alt+Right)",
              onClick: handleSeek(15),
            },
            "+15s",
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "teratts-pill-btn teratts-stop-btn",
              "aria-label": "Stop speech",
              title: "Stop speech (Escape)",
              onClick: toggle,
            },
            React.createElement(IconStopFill16, {}),
          ),
        ),
      );

      const usePortal = typeof document !== "undefined" && document.body && ReactDOM && typeof ReactDOM.createPortal === "function" && typeof window !== "undefined" && !globalThis.__teratts_testNoPortal;
      if (usePortal) {
        return React.createElement(
          React.Fragment,
          null,
          actionButton,
          ReactDOM.createPortal(playerCard, document.body),
        );
      }
      return playerCard;
    }

    const inject = ["remote", "slots"];
    async function apply(ctx) {
      let disposeRemote = null;
      try {
        disposeRemote = await ctx.remote.$mount(REMOTE);
      } catch (error) {
        console.error("[dsh-client-ui-teratts] remote mount failed:", error);
      }
      const voice = ctx.get("remote.terattsVoice");
      const disposeSlot = ctx.slots.inject("conversation.chat.assistant-actions", () =>
        ctx.slots.register(
          {
            name: "conversation.chat.assistant-actions",
            id: "teratts",
            order: 20,
          },
          (props) =>
            React.createElement(TeraTtsAction, {
              ...props,
              voice,
            }),
        ),
      );
      return async () => {
        disposeSlot();
        stopPlayback();
        if (disposeRemote) await disposeRemote();
      };
    }

    module.exports.apply = apply;
    module.exports.inject = inject;
    return module.exports;
  },
});
}
