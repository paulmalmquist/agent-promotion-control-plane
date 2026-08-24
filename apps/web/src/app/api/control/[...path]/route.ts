export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_INTERNAL_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const responseHeaderAllowList = ["content-type", "location", "x-correlation-id", "retry-after"];

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const incoming = new URL(request.url);
  const upstream = new URL(`${API_INTERNAL_URL}/${path.map(encodeURIComponent).join("/")}`);
  incoming.searchParams.forEach((value, key) => upstream.searchParams.append(key, value));

  const headers = new Headers();
  for (const name of ["accept", "content-type", "idempotency-key", "x-correlation-id", "if-match"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(upstream, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
    signal: request.signal
  });
  const responseHeaders = new Headers({ "Cache-Control": "no-store" });
  responseHeaderAllowList.forEach((name) => {
    const value = response.headers.get(name);
    if (value) responseHeaders.set(name, value);
  });
  return new Response(response.body, { status: response.status, headers: responseHeaders });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
