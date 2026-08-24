import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { constants, createGzip } from "node:zlib";
import { createServer } from "node:http";
import { once } from "node:events";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const standaloneServer = resolve(repositoryRoot, "apps/web/.next/standalone/apps/web/server.js");
const nextPort = 3131;
const upstreamPort = 8766;
let releaseSecond = () => undefined;
let observedStreamRequest;
let resolveAbort;
const abortObserved = new Promise((resolve) => { resolveAbort = resolve; });

if (!existsSync(standaloneServer)) {
  throw new Error("Production build missing. Run the web build before test:sse.");
}

const upstream = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${upstreamPort}`);
  if (url.pathname !== "/api/v1/events/stream") {
    response.writeHead(404).end();
    return;
  }
  if (url.searchParams.get("mode") === "abort") {
    let open = true;
    const finish = () => {
      if (!open) return;
      open = false;
      clearInterval(keepalive);
      resolveAbort();
    };
    request.on("aborted", finish);
    request.on("close", finish);
    response.on("close", finish);
    response.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache"
    });
    response.write("id: 50\nevent: promotion_event\ndata: {\"sequence\":50}\n\n");
    const keepalive = setInterval(() => response.write(": keepalive\n\n"), 250);
    return;
  }

  observedStreamRequest = {
    candidateId: url.searchParams.get("candidate_id"),
    after: url.searchParams.get("after"),
    lastEventId: request.headers["last-event-id"],
    acceptEncoding: request.headers["accept-encoding"]
  };
  response.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Content-Encoding": "gzip",
    "Cache-Control": "no-cache",
    "X-Upstream-Only": "must-not-forward"
  });
  const gzip = createGzip({ flush: constants.Z_SYNC_FLUSH });
  gzip.pipe(response);
  gzip.write("id: 41\nevent: promotion_event\ndata: {\"sequence\":41}\n\n");
  gzip.flush();
  releaseSecond = () => {
    gzip.write("id: 42\nevent: promotion_event\ndata: {\"sequence\":42}\n\n");
    gzip.end();
  };
});

async function waitForHealth() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${nextPort}/api/health`, { cache: "no-store" });
      if (response.ok) return;
    } catch {
      // The production server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Next.js production server did not become healthy.");
}

await new Promise((resolve, reject) => {
  upstream.once("error", reject);
  upstream.listen(upstreamPort, "127.0.0.1", resolve);
});

const next = spawn(process.execPath, [standaloneServer], {
  cwd: repositoryRoot,
  env: {
    ...process.env,
    PORT: String(nextPort),
    HOSTNAME: "127.0.0.1",
    API_INTERNAL_URL: `http://127.0.0.1:${upstreamPort}`,
    NODE_ENV: "production"
  },
  stdio: ["ignore", "pipe", "pipe"]
});
let childOutput = "";
next.stdout.on("data", (chunk) => { childOutput += chunk.toString(); });
next.stderr.on("data", (chunk) => { childOutput += chunk.toString(); });

try {
  await waitForHealth();
  const response = await fetch(
    `http://127.0.0.1:${nextPort}/api/events/stream?candidate_id=candidate-1&after=40`,
    {
      headers: {
        "Accept-Encoding": "gzip",
        "Last-Event-ID": "40"
      }
    }
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "text/event-stream; charset=utf-8");
  assert.equal(response.headers.get("cache-control"), "no-cache, no-store, no-transform");
  assert.equal(response.headers.get("x-accel-buffering"), "no");
  assert.equal(response.headers.get("content-encoding"), null);
  assert.equal(response.headers.get("content-length"), null);
  assert.equal(response.headers.get("x-upstream-only"), null);

  const reader = response.body.getReader();
  const first = await Promise.race([
    reader.read(),
    new Promise((_, reject) => setTimeout(() => reject(new Error("Event A was buffered.")), 1_500))
  ]);
  const firstText = new TextDecoder().decode(first.value);
  assert.match(firstText, /"sequence":41/);
  assert.doesNotMatch(firstText, /"sequence":42/);
  releaseSecond();
  const second = await reader.read();
  assert.match(new TextDecoder().decode(second.value), /"sequence":42/);
  assert.deepEqual(observedStreamRequest, {
    candidateId: "candidate-1",
    after: "40",
    lastEventId: "40",
    acceptEncoding: "gzip, deflate"
  });

  const abortController = new AbortController();
  const abortResponse = await fetch(
    `http://127.0.0.1:${nextPort}/api/events/stream?mode=abort`,
    { signal: abortController.signal }
  );
  const abortReader = abortResponse.body.getReader();
  await abortReader.read();
  abortController.abort();
  await Promise.race([
    abortObserved,
    new Promise((_, reject) => setTimeout(() => reject(new Error("Client disconnect did not abort upstream.")), 2_000))
  ]);

  process.stdout.write("Production SSE proxy: progressive streaming, replay, gzip stripping, and abort propagation passed.\n");
} catch (error) {
  if (childOutput) process.stderr.write(childOutput);
  throw error;
} finally {
  next.kill();
  upstream.close();
  await Promise.race([once(next, "exit"), new Promise((resolve) => setTimeout(resolve, 2_000))]);
}
