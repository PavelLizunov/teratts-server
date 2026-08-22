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

    const styleId = "dsh-client-ui-teratts/action";
    if (!document.querySelector(`style[data-plugin-css=${JSON.stringify(styleId)}]`)) {
      const style = document.createElement("style");
      style.dataset.plugin = "dsh-client-ui-teratts";
      style.dataset.pluginCss = styleId;
      style.textContent = ".teratts-action{width:28px;height:28px;color:var(--dsw-alias-label-tertiary);cursor:pointer;background:0 0;border:none;border-radius:28px;justify-content:center;align-items:center;padding:4px;display:inline-flex}.teratts-action:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}.teratts-action:disabled{cursor:default;opacity:.5}.teratts-action[data-active]{color:var(--dsw-alias-label-primary)}.teratts-loading{animation:teratts-spin 1s linear infinite}.teratts-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@keyframes teratts-spin{to{transform:rotate(360deg)}}";
      document.head.appendChild(style);
    }

    function cleanMarkdown(text) {
      return text
        .replace(/```[\s\S]*?```/g, " code block ")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/^\s{0,3}#{1,6}\s+/gm, "")
        .replace(/^\s*>\s?/gm, "")
        .replace(/^\s*[-*+]\s+/gm, "")
        .replace(/^\s*\d+[.)]\s+/gm, "")
        .replace(/[*_~]/g, "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
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
    };

    function snapshot() {
      return {
        owner: playback.owner,
        state: playback.state,
        error: playback.error,
        errorOwner: playback.errorOwner,
        errorSeq: playback.errorSeq,
      };
    }

    function publish() {
      const next = snapshot();
      for (const listener of playback.listeners) listener(next);
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

    function decodeAudio({ audioBase64, mimeType }) {
      const binary = atob(audioBase64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
      return new Blob([bytes], { type: mimeType || "audio/wav" });
    }

    async function startPlayback(owner, text, runner) {
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
        const result = await runner.invoke("synthesize", { text }, abort.signal);
        if (epoch !== playback.epoch) return;
        if (!result.ok) {
          if (result.error?.code === "cancelled") return;
          throw new Error(result.error?.message || "Speech generation failed");
        }
        const url = URL.createObjectURL(decodeAudio(result.value));
        if (epoch !== playback.epoch) {
          URL.revokeObjectURL(url);
          return;
        }
        const audio = new Audio(url);
        playback.abort = null;
        playback.audio = audio;
        playback.url = url;
        audio.onended = () => {
          if (epoch === playback.epoch) stopPlayback();
        };
        audio.onerror = () => failPlayback(epoch, "Audio playback failed");
        await audio.play();
        if (epoch !== playback.epoch) return;
        playback.state = "playing";
        publish();
      } catch (error) {
        if (epoch !== playback.epoch || error?.name === "AbortError") return;
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

    function TeraTtsAction({ messageId, useSession, runner }) {
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

      const toggle = React.useCallback(() => {
        if (active) stopPlayback();
        else if (text) startPlayback(owner.current, text, runner);
      }, [active, runner, text]);

      const label =
        state === "loading"
          ? "Generating speech"
          : state === "playing"
            ? "Stop speech"
            : "Read response aloud";
      const error =
        current.errorOwner === owner.current && current.errorSeq ? current.error : null;

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
              : state === "playing"
                ? React.createElement(IconStopFill16, {})
                : React.createElement(SpeakerIcon),
          ),
        ),
        error &&
          React.createElement(
            React.Fragment,
            null,
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
          ),
      );
    }

    const inject = ["slots", "remote"];
    async function apply(ctx) {
      let disposeSlot;
      try {
        disposeSlot = ctx.slots.inject("conversation.chat.assistant-actions", () =>
          ctx.slots.register(
            {
              name: "conversation.chat.assistant-actions",
              id: "teratts",
              order: 20,
            },
            (props) =>
              React.createElement(TeraTtsAction, {
                ...props,
                runner: ctx.remote.dynamicCordisRunner,
              }),
          ),
        );
      } catch (error) {
        throw error;
      }
      return async () => {
        disposeSlot();
        stopPlayback();
      };
    }

    module.exports.apply = apply;
    module.exports.inject = inject;
    return module.exports;
  },
});
