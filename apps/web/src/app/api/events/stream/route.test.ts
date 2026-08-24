import { GET } from "./route";

describe("Next.js server-sent event proxy", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("forwards replay filters and streams the first frame without waiting for closure", async () => {
    let releaseSecond: (() => void) | undefined;
    let secondReleased = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("id: 41\nevent: promotion_event\ndata: {\"sequence\":41}\n\n"));
        releaseSecond = () => {
          secondReleased = true;
          controller.enqueue(new TextEncoder().encode("id: 42\nevent: promotion_event\ndata: {\"sequence\":42}\n\n"));
          controller.close();
        };
      }
    });
    const upstreamFetch = vi.fn().mockResolvedValue(new Response(stream, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Content-Encoding": "gzip",
        "Content-Length": "999",
        "Transfer-Encoding": "chunked"
      }
    }));
    vi.stubGlobal("fetch", upstreamFetch);
    const controller = new AbortController();
    const request = new Request(
      "http://localhost:3001/api/events/stream?candidate_id=candidate-1&after=40",
      { headers: { "Last-Event-ID": "40", "Accept-Encoding": "gzip" }, signal: controller.signal }
    );
    const response = await GET(request);

    expect(response.headers.get("content-type")).toBe("text/event-stream; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-store, no-transform");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(response.headers.get("content-encoding")).toBeNull();
    expect(response.headers.get("content-length")).toBeNull();
    const [upstreamUrl, init] = upstreamFetch.mock.calls[0]!;
    expect(String(upstreamUrl)).toContain("candidate_id=candidate-1&after=40");
    expect((init.headers as Headers).get("last-event-id")).toBe("40");
    expect(init.signal).toBe(request.signal);

    const reader = response.body!.getReader();
    const first = await reader.read();
    expect(new TextDecoder().decode(first.value)).toContain("sequence\":41");
    expect(secondReleased).toBe(false);
    releaseSecond!();
    const second = await reader.read();
    expect(new TextDecoder().decode(second.value)).toContain("sequence\":42");
  });
});
