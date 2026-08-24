export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function GET(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const upstreamUrl = new URL(`${API_INTERNAL_URL}/api/v1/events/stream`);
  incoming.searchParams.forEach((value, key) => upstreamUrl.searchParams.append(key, value));

  const headers = new Headers({ Accept: "text/event-stream" });
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) headers.set("Last-Event-ID", lastEventId);

  const upstream = await fetch(upstreamUrl, {
    cache: "no-store",
    headers,
    signal: request.signal
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/problem+json",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no"
      }
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-store, no-transform",
      "X-Accel-Buffering": "no"
    }
  });
}
