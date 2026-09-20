import { createHash } from "node:crypto";
import { cleanMarkdown, splitSpeechText } from "./speech-text.js";

export function normalizeEndpointWithoutAuth(endpointStr) {
  try {
    const u = new URL(typeof endpointStr === "string" ? endpointStr : "http://127.0.0.1:8088");
    return `${u.origin}${u.pathname}`.replace(/\/+$/, "");
  } catch {
    return String(endpointStr || "").replace(/\/+$/, "");
  }
}

export function audioKey(text, config, synthesisRevision = "unknown") {
  const cleanEndpoint = normalizeEndpointWithoutAuth(config?.endpoint);
  return createHash("sha256")
    .update(
      JSON.stringify([
        text,
        config?.voice ?? "ru_f1",
        config?.language ?? "ru",
        config?.stress === true,
        config?.speechFront !== false,
        cleanEndpoint,
        synthesisRevision,
        "v1_140_240_320",
      ]),
    )
    .digest("hex");
}

export class AudioCache {
  constructor(maxItems = 64) {
    this.maxItems = maxItems;
    this.cache = new Map();
    this.inFlight = new Map();
  }

  get(key) {
    const value = this.cache.get(key);
    if (value !== undefined) {
      this.cache.delete(key);
      this.cache.set(key, value);
      return value;
    }
    return undefined;
  }

  set(key, value) {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    } else if (this.cache.size >= this.maxItems) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey !== undefined) this.cache.delete(oldestKey);
    }
    this.cache.set(key, value);
  }

  clear() {
    this.cache.clear();
    this.inFlight.clear();
  }
}

export class PlaybackCoordinator {
  constructor() {
    this.activeOwnerId = null;
    this.activeEpoch = null;
    this.activeUntil = 0;

    this.backgroundRunning = 0; // <= 1
    this.backgroundPending = null; // <= 1
    this.currentBackgroundTask = null; // { key, isForeground, abortController, promise }
  }

  isForegroundActive() {
    return this.activeOwnerId !== null;
  }

  acquireForeground(ownerId, epoch) {
    this.activeOwnerId = String(ownerId);
    this.activeEpoch = Number(epoch);
    this.activeUntil = Date.now() + 15_000;
    this.backgroundPending = null;
    return { ok: true };
  }

  renewForeground(ownerId, epoch) {
    if (this.activeOwnerId === String(ownerId) && this.activeEpoch === Number(epoch)) {
      this.activeUntil = Date.now() + 15_000;
      return { ok: true };
    }
    return { ok: false };
  }

  releaseForeground(ownerId, epoch) {
    if (this.activeOwnerId === String(ownerId) && this.activeEpoch === Number(epoch)) {
      this.activeOwnerId = null;
      this.activeEpoch = null;
      this.activeUntil = 0;
      this.pumpBackground();
      return { ok: true };
    }
    return { ok: false };
  }

  scheduleBackground(candidate) {
    this.backgroundPending = candidate;
    this.pumpBackground();
  }

  pumpBackground() {
    if (this.backgroundRunning >= 1) return;
    if (this.isForegroundActive()) return;
    if (!this.backgroundPending) return;

    const candidate = this.backgroundPending;
    this.backgroundPending = null;

    this.backgroundRunning = 1;
    const abortController = new AbortController();
    const task = {
      key: candidate.key,
      isForeground: false,
      abortController,
      promise: null,
    };
    this.currentBackgroundTask = task;

    task.promise = (async () => {
      try {
        if (this.isForegroundActive()) return;
        await candidate.run(abortController.signal);
      } catch {
        // Discard background errors
      } finally {
        if (this.currentBackgroundTask === task) {
          this.currentBackgroundTask = null;
        }
        this.backgroundRunning = 0;
        this.pumpBackground();
      }
    })();
  }

  promoteToForeground(key) {
    if (this.currentBackgroundTask && this.currentBackgroundTask.key === key) {
      this.currentBackgroundTask.isForeground = true;
      return this.currentBackgroundTask.promise;
    }
    return null;
  }

  cancelBackground(reason) {
    this.backgroundPending = null;
    if (this.currentBackgroundTask && !this.currentBackgroundTask.isForeground) {
      this.currentBackgroundTask.abortController.abort(
        reason instanceof Error ? reason : new Error(reason || "Cancelled by foreground"),
      );
    }
  }
}

export function messageFirstChunk(session, messageId) {
  if (!session || typeof session.deriveMessages !== "function") return null;
  const message = session.deriveMessages().find((item) => item.id === messageId && item.role === "assistant");
  if (!message) return null;
  const text = message.content
    ?.filter((block) => block.type === "text")
    ?.map((block) => block.text)
    ?.join("\n");
  if (!text || text.length > 100_000) return null;
  const cleaned = cleanMarkdown(text);
  if (!cleaned) return null;
  const chunks = splitSpeechText(cleaned);
  return chunks.length > 0 ? chunks[0] : null;
}
