const STRUCTURAL = /^\s{0,3}#{1,6}\s|^\s*>|^\s*[-*+]\s|^\s*\d+[.)]\s/;
const ALLOWED_CHARS = /[^\p{Script=Cyrillic}a-zA-Z0-9\s.,:;!?\-\u2014\u2013…()\[\]{}«»“”„’"\/\\_+#@%=&~$*|^<>→⇒←⇐↔⇔↑↓≈≤≥≠×÷±−₽€£¥]/gu;

export const FIRST_SPEECH_CHUNK_CHARS = 140;
export const SECOND_SPEECH_CHUNK_CHARS = 240;
export const SPEECH_CHUNK_CHARS = 320;
export const MAX_STREAMED_AUDIO_BYTES = 256 * 1024 * 1024;

export function cleanLine(line) {
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
    .replace(/<(?!\/?(?:ru|en)>)(?:\/?[a-z][a-z0-9:-]*)(?:\s+[^<>]*?)?\/?\s*>/gi, " ")
    .replace(/<=\s*/g, " меньше или равно ")
    .replace(/<(?!\/?(?:ru|en)>)\s*/g, " меньше ")
    .replace(/>=\s*/g, " больше или равно ")
    .replace(/(?<!<\/?(?:ru|en))>\s*/g, " больше ")
    .replace(ALLOWED_CHARS, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function cleanCodeBlock(body) {
  return body
    .split("\n")
    .map((line) =>
      cleanLine(line).replace(/[{}\[\]();"]/g, " ").replace(/\s+/g, " ").trim(),
    )
    .filter(Boolean)
    .map((line) => (/[.!?…:]$/.test(line) ? line : `${line}.`))
    .join(" ");
}

export function sanitizeLanguageTags(text) {
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

export function cleanMarkdown(text) {
  const unified = text
    .replace(/\r/g, "")
    .replace(/```[^\n]*\n([\s\S]*?)```/g, (_fence, body) => `\n${cleanCodeBlock(body)}\n`)
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
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

export function speechChunkLimits(options, laterMaxChars) {
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

export function speechLanguageSpans(text) {
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
      if (active) throw new RangeError("nested speech language tags are not allowed");
      if (match.index > cursor) {
        const plain = text.slice(cursor, match.index).trim();
        if (plain) spans.push({ language: null, text: plain });
      }
      active = language;
      contentStart = tags.lastIndex;
    } else {
      if (active !== language) throw new RangeError("unbalanced speech language tags");
      const content = text.slice(contentStart, match.index).trim();
      if (content) spans.push({ language, text: content });
      active = null;
      cursor = tags.lastIndex;
    }
  }
  if (active) throw new RangeError("unbalanced speech language tags");
  if (cursor < text.length) {
    const plain = text.slice(cursor).trim();
    if (plain) spans.push({ language: null, text: plain });
  }
  return spans;
}

export function nextSpeechCut(text, maxChars) {
  if (text.length <= maxChars) return text.length;
  const window = text.slice(0, maxChars + 1);
  let cut = Math.max(
    window.lastIndexOf(". "),
    window.lastIndexOf("! "),
    window.lastIndexOf("? "),
    window.lastIndexOf("; "),
    window.lastIndexOf(": "),
    window.lastIndexOf("… "),
    window.lastIndexOf("\n"),
  );
  if (cut >= Math.floor(maxChars / 2)) cut += 1;
  else cut = window.lastIndexOf(" ", maxChars);
  if (cut < 1) cut = maxChars;
  const before = text.charCodeAt(cut - 1);
  const after = text.charCodeAt(cut);
  if (before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff) cut -= 1;
  return Math.max(1, cut);
}

export function splitSpeechText(text, options, laterMaxChars) {
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
