const STRUCTURAL = /^\s{0,3}#{1,6}\s|^\s*>|^\s*[-*+]\s|^\s*\d+[.)]\s/;

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
    // Strip only syntactically valid HTML-like tags; keep comparisons such as
    // `3 < 5 and 5 > 2` and preserve exact Tera <ru>/<en> language tags.
    .replace(/<(?!\/?(?:ru|en)>)(?:\/?[a-z][a-z0-9:-]*)(?:\s+[^<>]*?)?\/?\s*>/gi, " ")
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

function cleanMarkdown(text) {
  return text
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
      if (structural && !/[.!?…:](?:<\/(?:ru|en)>)?$/.test(cleaned)) return cleaned + ".";
      return cleaned;
    })
    .filter(Boolean)
    .join(" ")
    .replace(/\s*→\s*/g, ", ")
    .replace(/\s*×\s*/g, ", ")
    .replace(/\s+/g, " ")
    .trim();
}

const SPEECH_CHUNK_CHARS = 800;
const MAX_MERGED_WAV_BYTES = 16 * 1024 * 1024;

function splitSpeechText(text, maxChars = SPEECH_CHUNK_CHARS) {
  if (!Number.isInteger(maxChars) || maxChars < 1) throw new RangeError("invalid speech chunk size");
  const chunks = [];
  let rest = text.trim();
  if (/<\/?(?:ru|en)>/.test(rest)) return rest ? [rest] : [];
  while (rest.length > maxChars) {
    const window = rest.slice(0, maxChars + 1);
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
    chunks.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

function mergeMonoPcmWavs(wavs, maxBytes = MAX_MERGED_WAV_BYTES) {
  if (!Array.isArray(wavs) || wavs.length === 0) throw new TypeError("missing WAV chunks");
  if (!Number.isInteger(maxBytes) || maxBytes < 44) throw new RangeError("invalid WAV limit");
  let totalBytes = 44;
  let first = null;
  const payloads = wavs.map((bytes) => {
    if (!(bytes instanceof Uint8Array) || bytes.length < 44) throw new TypeError("invalid WAV chunk");
    const tag = (offset) => String.fromCharCode(...bytes.subarray(offset, offset + 4));
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const valid =
      tag(0) === "RIFF" &&
      tag(8) === "WAVE" &&
      tag(12) === "fmt " &&
      tag(36) === "data" &&
      view.getUint32(4, true) === bytes.length - 8 &&
      view.getUint32(16, true) === 16 &&
      view.getUint16(20, true) === 1 &&
      view.getUint16(22, true) === 1 &&
      view.getUint32(28, true) === view.getUint32(24, true) * 2 &&
      view.getUint16(32, true) === 2 &&
      view.getUint16(34, true) === 16 &&
      view.getUint32(40, true) === bytes.length - 44 &&
      view.getUint32(40, true) % 2 === 0;
    if (!valid) throw new TypeError("unsupported WAV chunk");
    if (first) {
      for (let index = 20; index < 36; index += 1) {
        if (bytes[index] !== first[index]) throw new TypeError("WAV formats do not match");
      }
    } else {
      first = bytes;
    }
    const payload = bytes.subarray(44);
    if (payload.length > maxBytes - totalBytes) throw new RangeError("Speech audio is too large");
    totalBytes += payload.length;
    return payload;
  });
  const merged = new Uint8Array(totalBytes);
  merged.set(first.subarray(0, 44));
  const header = new DataView(merged.buffer);
  header.setUint32(4, totalBytes - 8, true);
  header.setUint32(40, totalBytes - 44, true);
  let offset = 44;
  for (const payload of payloads) {
    merged.set(payload, offset);
    offset += payload.length;
  }
  return merged;
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
  globalThis.__teratts_mergeMonoPcmWavs = mergeMonoPcmWavs;
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
      ],
    };

    const styleId = "dsh-client-ui-teratts/action";
    if (!document.querySelector(`style[data-plugin-css=${JSON.stringify(styleId)}]`)) {
      const style = document.createElement("style");
      style.dataset.plugin = "dsh-client-ui-teratts";
      style.dataset.pluginCss = styleId;
      style.textContent = ".teratts-action{width:28px;height:28px;color:var(--dsw-alias-label-tertiary);cursor:pointer;background:0 0;border:none;border-radius:28px;justify-content:center;align-items:center;padding:4px;display:inline-flex}.teratts-action:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}.teratts-action:disabled{cursor:default;opacity:.5}.teratts-action[data-active]{color:var(--dsw-alias-label-primary)}.teratts-loading{animation:teratts-spin 1s linear infinite}.teratts-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.teratts-group{display:inline-flex;align-items:center;gap:2px}.teratts-control{min-width:28px;height:28px;padding:0 4px;color:var(--dsw-alias-label-tertiary);cursor:pointer;background:0 0;border:none;border-radius:14px;justify-content:center;align-items:center;display:inline-flex;font-size:11px;font-weight:600;line-height:1;white-space:nowrap;font-family:inherit}.teratts-control:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}@keyframes teratts-spin{to{transform:rotate(360deg)}}";
      document.head.appendChild(style);
    }

    function messageText(snapshot, messageId) {
      const node = snapshot.chat?.legacy?.nodes?.find(
        (candidate) => candidate.kind === "assistant" && candidate.messageId === messageId,
      );
      return cleanMarkdown(
        node?.blocks
          .filter((block) => block.kind === "text")
          .map((block) => block.text)
          .join("\n") || "",
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
      state: "idle",
      error: null,
      errorOwner: null,
      errorSeq: 0,
      abort: null,
      audio: null,
      url: null,
      listeners: new Set(),
      rate: 1,
    };

    function snapshot() {
      return {
        owner: playback.owner,
        state: playback.state,
        error: playback.error,
        errorOwner: playback.errorOwner,
        errorSeq: playback.errorSeq,
        rate: playback.rate,
      };
    }

    function publish() {
      const next = snapshot();
      for (const listener of playback.listeners) listener(next);
    }

    function setPlaybackRate(rate) {
      playback.rate = rate;
      if (playback.audio) {
        playback.audio.playbackRate = rate;
      }
      publish();
    }

    function cyclePlaybackRate() {
      setPlaybackRate(nextPlaybackRate(playback.rate));
    }

    function seekPlayback(offset) {
      if (playback.audio) {
        const duration = playback.audio.duration;
        if (typeof duration === "number" && Number.isFinite(duration) && duration > 0) {
          playback.audio.currentTime = clampSeekTime(playback.audio.currentTime, offset, duration);
        }
      }
    }

    function releaseMedia() {
      playback.abort?.abort();
      playback.abort = null;
      if (playback.audio) {
        playback.audio.onended = null;
        playback.audio.onerror = null;
        playback.audio.pause();
        playback.audio.removeAttribute("src");
        playback.audio.load();
        playback.audio = null;
      }
      if (playback.url) {
        URL.revokeObjectURL(playback.url);
        playback.url = null;
      }
    }

    function stopPlayback() {
      playback.epoch += 1;
      releaseMedia();
      playback.owner = null;
      playback.state = "idle";
      publish();
    }

    function failPlayback(epoch, message) {
      if (epoch !== playback.epoch) return;
      const errorOwner = playback.owner;
      releaseMedia();
      playback.owner = null;
      playback.state = "idle";
      playback.error = message;
      playback.errorOwner = errorOwner;
      playback.errorSeq += 1;
      publish();
    }

    function decodeAudio(chunks) {
      const wavs = chunks.map(({ audioBase64, mimeType }) => {
        if (mimeType?.split(";", 1)[0].trim().toLowerCase() !== "audio/wav") {
          throw new TypeError("unsupported TeraTTS audio format");
        }
        const binary = atob(audioBase64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index);
        }
        return bytes;
      });
      return new Blob([mergeMonoPcmWavs(wavs)], { type: "audio/wav" });
    }

    function unwrapAudio(result) {
      if (result && typeof result.audioBase64 === "string") return result;
      if (result && result.ok === true && result.value) return result.value;
      if (result && result.ok === false) {
        throw new Error(result.error?.message || "Speech generation failed");
      }
      throw new TypeError("invalid TeraTTS audio response");
    }

    async function startPlayback(owner, text, voice) {
      stopPlayback();
      const epoch = playback.epoch;
      const abort = new AbortController();
      playback.owner = owner;
      playback.state = "loading";
      playback.error = null;
      playback.errorOwner = null;
      playback.abort = abort;
      publish();
      try {
        if (!voice) throw new Error("TeraTTS voice service is unavailable");
        const audioChunks = [];
        for (const chunk of splitSpeechText(text)) {
          const result = await voice.synthesize(chunk, abort.signal);
          if (epoch !== playback.epoch) return;
          audioChunks.push(unwrapAudio(result));
        }
        const url = URL.createObjectURL(decodeAudio(audioChunks));
        if (epoch !== playback.epoch) {
          URL.revokeObjectURL(url);
          return;
        }
        const element = new Audio(url);
        element.playbackRate = playback.rate;
        playback.abort = null;
        playback.audio = element;
        playback.url = url;
        element.onended = () => {
          if (epoch === playback.epoch) stopPlayback();
        };
        element.onerror = () => failPlayback(epoch, "Audio playback failed");
        await element.play();
        if (epoch !== playback.epoch) return;
        playback.state = "playing";
        publish();
      } catch (error) {
        if (epoch !== playback.epoch) return;
        if (error?.name === "AbortError") {
          failPlayback(epoch, "Request timed out");
          return;
        }
        failPlayback(epoch, error instanceof Error ? error.message : "Speech playback failed");
      }
    }

    function usePlayback() {
      const [value, setValue] = React.useState(snapshot);
      React.useEffect(() => {
        playback.listeners.add(setValue);
        return () => playback.listeners.delete(setValue);
      }, []);
      return value;
    }

    function TeraTtsAction({ messageId, useSession, voice }) {
      const text = useSession((session) => messageText(session, messageId));
      const current = usePlayback();
      const owner = React.useRef(Symbol(messageId));
      const buttonRef = React.useRef(null);
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

      if (active && state === "playing") {
        const rateText = `${current.rate || 1}×`;
        const control = (label, content, onClick, className = "teratts-control", ref) =>
          React.createElement(
            Tooltip,
            { label, side: "bottom" },
            React.createElement(
              "button",
              {
                ref,
                type: "button",
                className,
                "aria-label": label,
                "data-active": className === "teratts-action" || undefined,
                onClick,
              },
              content,
            ),
          );
        return React.createElement(
          "div",
          { className: "teratts-group" },
          control("Rewind 10 seconds", "-10", handleSeek(-10)),
          control(`Playback speed ${rateText}`, rateText, handleRate),
          control("Fast forward 15 seconds", "+15", handleSeek(15)),
          control(
            "Stop speech",
            React.createElement(IconStopFill16, {}),
            toggle,
            "teratts-action",
            buttonRef,
          ),
        );
      }

      const label =
        state === "loading"
          ? "Generating speech"
          : "Read response aloud";

      return React.createElement(
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
