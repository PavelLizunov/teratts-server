window.__ModuleLoader__.load({
  id: "dsh-client-ui-teratts",
  factory: (require) => {
    const module = { exports: {} };
    const React = require("react");
    const { Tooltip } = require("@deepseek-ai/dsh-client-ui-primitives");
    const TTS_URL = window.localStorage.getItem("teratts.url") || "http://127.0.0.1:8088";
    const styleId = "dsh-client-ui-teratts/action";
    if (!document.querySelector(`style[data-plugin-css=${JSON.stringify(styleId)}]`)) {
      const style = document.createElement("style");
      style.dataset.plugin = "dsh-client-ui-teratts";
      style.dataset.pluginCss = styleId;
      style.textContent = ".teratts-action{width:28px;height:28px;color:var(--dsw-alias-label-tertiary);cursor:pointer;background:0 0;border:none;border-radius:28px;justify-content:center;align-items:center;padding:4px;display:inline-flex;font-size:16px}.teratts-action:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-secondary)}.teratts-action:disabled{cursor:default;opacity:.5}.teratts-action[data-playing]{color:var(--dsw-alias-label-primary)}";
      document.head.appendChild(style);
    }

    function cleanMarkdown(text) {
      return text
        .replace(/```[\s\S]*?```/g, " блок кода ")
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
      const node = snapshot.chat.legacy.nodes.find(
        (candidate) => candidate.kind === "assistant" && candidate.messageId === messageId,
      );
      return cleanMarkdown(
        node?.blocks
          .filter((block) => block.kind === "text")
          .map((block) => block.text)
          .join("\n") || "",
      );
    }

    function SpeakerIcon({ stop }) {
      return React.createElement(
        "span",
        { "aria-hidden": true },
        stop ? "⏹" : "🔊",
      );
    }

    function TeraTtsAction({ messageId, useSession }) {
      const text = useSession((snapshot) => messageText(snapshot, messageId));
      const [state, setState] = React.useState("idle");
      const audioRef = React.useRef(null);
      const urlRef = React.useRef(null);
      const abortRef = React.useRef(null);

      const stop = React.useCallback(() => {
        abortRef.current?.abort();
        abortRef.current = null;
        if (audioRef.current) {
          audioRef.current.pause();
          audioRef.current.currentTime = 0;
          audioRef.current = null;
        }
        if (urlRef.current) {
          URL.revokeObjectURL(urlRef.current);
          urlRef.current = null;
        }
        setState("idle");
      }, []);

      React.useEffect(() => stop, [stop]);

      const toggle = React.useCallback(async () => {
        if (state !== "idle") {
          stop();
          return;
        }
        if (!text) return;
        const controller = new AbortController();
        abortRef.current = controller;
        setState("loading");
        try {
          const response = await fetch(`${TTS_URL}/tts`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ text, voice: "ru_f1", duration_scale: 1.0 }),
            signal: controller.signal,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const url = URL.createObjectURL(await response.blob());
          urlRef.current = url;
          const audio = new Audio(url);
          audioRef.current = audio;
          audio.onended = stop;
          audio.onerror = stop;
          await audio.play();
          setState("playing");
        } catch (error) {
          if (error?.name !== "AbortError") console.error("[ui-teratts]", error);
          stop();
        }
      }, [state, stop, text]);

      const label = state === "loading" ? "Генерация речи" : state === "playing" ? "Остановить озвучку" : "Озвучить ответ";
      return React.createElement(
        Tooltip,
        { label, side: "bottom" },
        React.createElement(
          "button",
          {
            type: "button",
            className: "teratts-action",
            "aria-label": label,
            "aria-pressed": state === "playing",
            "data-playing": state === "playing" || undefined,
            disabled: !text,
            onClick: toggle,
          },
          state === "loading" ? "⏳" : React.createElement(SpeakerIcon, { stop: state === "playing" }),
        ),
      );
    }

    const inject = ["slots"];
    function apply(ctx) {
      ctx.slots.inject("conversation.chat.assistant-actions", () =>
        ctx.slots.register(
          {
            name: "conversation.chat.assistant-actions",
            id: "teratts",
            order: 20,
          },
          TeraTtsAction,
        ),
      );
    }

    module.exports.apply = apply;
    module.exports.inject = inject;
    return module.exports;
  },
});
