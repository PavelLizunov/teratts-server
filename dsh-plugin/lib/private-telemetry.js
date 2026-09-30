import { Buffer } from "node:buffer";

export function privateIngestUrl(value) {
  if (!value) return null;
  const url = new URL(value);
  const parts = url.hostname.split(".").map(Number);
  const tailnet = parts.length === 4 && parts.every((x) => Number.isInteger(x) && x >= 0 && x <= 255)
    && parts[0] === 100 && parts[1] >= 64 && parts[1] <= 127;
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if (url.protocol !== "http:" || (!tailnet && !loopback) || url.pathname !== "/record"
      || url.username || url.password || url.search || url.hash) {
    throw new Error("Telemetry endpoint must be private Tailnet/loopback /record");
  }
  return url.href;
}

export function encodePrivateRecord(metadata, attachments = {}) {
  const entries = Object.entries(attachments).map(([name, value]) => [name, Buffer.from(value)]);
  const header = Buffer.from(JSON.stringify({ metadata, attachments: entries.map(([name, bytes]) => ({ name, size: bytes.length })) }));
  if (header.length > 1024 * 1024) throw new Error("Telemetry metadata too large");
  const size = Buffer.alloc(4);
  size.writeUInt32BE(header.length);
  const body = Buffer.concat([size, header, ...entries.map(([, bytes]) => bytes)]);
  if (body.length > 34 * 1024 * 1024) throw new Error("Telemetry record too large");
  return body;
}

export class PrivateTelemetry {
  constructor(endpoint, sender = globalThis.fetch) {
    this.endpoint = privateIngestUrl(endpoint);
    this.sender = sender;
    this.pending = 0;
  }

  async record(metadata, attachments = {}) {
    if (!this.endpoint) return { status: "disabled" };
    if (this.pending >= 4) return { status: "dropped", reason: "queue_full" };
    this.pending++;
    try {
      const response = await this.sender(this.endpoint, {
        method: "POST", redirect: "error", headers: { "content-type": "application/octet-stream" },
        body: encodePrivateRecord(metadata, attachments), signal: AbortSignal.timeout(8000),
      });
      if (!response.ok) throw new Error(`Ingest HTTP ${response.status}`);
      const result = await response.json();
      return { status: "saved", sampleId: result.sample_id };
    } catch {
      return { status: "dropped", reason: "ingest_unavailable" };
    } finally {
      this.pending--;
    }
  }
}
