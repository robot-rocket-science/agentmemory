/**
 * Email Worker for agentmemory telemetry ingestion.
 *
 * Receives emails at data@robotrocketscience.com, extracts JSONL telemetry
 * from the email body or attachments, validates and stores in D1, then
 * forwards the original email to Gmail as notification.
 *
 * Deployed as Cloudflare Worker "dry-term-30e8".
 */
import * as PostalMime from "postal-mime";

const SCHEMA_VERSION = 1;
const REQUIRED_KEYS = ["v", "ts", "session", "feedback", "beliefs", "graph"];
const FORWARD_TO = "jonsobol@gmail.com";

function validateSnapshot(obj) {
  if (typeof obj !== "object" || obj === null) return "not an object";
  for (const key of REQUIRED_KEYS) {
    if (!(key in obj)) return `missing key: ${key}`;
  }
  if (obj.v !== SCHEMA_VERSION) return `unsupported version: ${obj.v}`;
  if (typeof obj.ts !== "string" || !obj.ts) return "invalid ts";
  return null;
}

/**
 * Try to parse JSONL from a string. Returns an array of valid snapshot objects
 * and a count of rejected lines.
 */
function parseJsonl(text) {
  const lines = text.split("\n").filter((l) => l.trim());
  const accepted = [];
  let rejected = 0;

  for (const line of lines) {
    try {
      const obj = JSON.parse(line);
      const err = validateSnapshot(obj);
      if (err) {
        rejected++;
        continue;
      }
      accepted.push({ obj, raw: line });
    } catch {
      rejected++;
    }
  }

  return { accepted, rejected };
}

/**
 * Store validated snapshots in D1.
 */
async function storeSnapshots(db, snapshots) {
  let stored = 0;
  for (const { obj, raw } of snapshots) {
    try {
      await db
        .prepare("INSERT INTO snapshots (ts, v, payload) VALUES (?, ?, ?)")
        .bind(obj.ts, obj.v, raw)
        .run();
      stored++;
    } catch {
      // skip duplicates or DB errors
    }
  }
  return stored;
}

export default {
  async email(message, env, ctx) {
    const db = env.TELEMETRY_DB;
    const from = message.from;
    const subject = message.headers.get("subject") || "(no subject)";

    // Parse the raw email with postal-mime
    const parser = new PostalMime.default();
    const rawEmail = new Response(message.raw);
    const parsed = await parser.parse(await rawEmail.arrayBuffer());

    let totalAccepted = 0;
    let totalRejected = 0;

    // Try to extract JSONL from the plain text body
    if (parsed.text) {
      const { accepted, rejected } = parseJsonl(parsed.text);
      if (accepted.length > 0 && db) {
        const stored = await storeSnapshots(db, accepted);
        totalAccepted += stored;
      }
      totalRejected += rejected;
    }

    // Try to extract JSONL from attachments (.jsonl or .json files)
    if (parsed.attachments && parsed.attachments.length > 0) {
      for (const attachment of parsed.attachments) {
        const filename = (attachment.filename || "").toLowerCase();
        if (
          filename.endsWith(".jsonl") ||
          filename.endsWith(".json") ||
          attachment.mimeType === "application/json"
        ) {
          const decoder = new TextDecoder();
          const text = decoder.decode(attachment.content);
          const { accepted, rejected } = parseJsonl(text);
          if (accepted.length > 0 && db) {
            const stored = await storeSnapshots(db, accepted);
            totalAccepted += stored;
          }
          totalRejected += rejected;
        }
      }
    }

    console.log(
      `Email from ${from} (${subject}): accepted=${totalAccepted}, rejected=${totalRejected}`
    );

    // Forward the original email to Gmail as notification
    try {
      await message.forward(FORWARD_TO);
    } catch (err) {
      console.error(`Forward failed: ${err.message}`);
    }
  },
};
