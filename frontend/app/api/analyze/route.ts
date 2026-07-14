import { NextRequest } from "next/server";

// Streaming proxy for the SSE analyze endpoint. The default next.config rewrite
// buffers streamed responses in dev (the whole SSE stream is held until the
// upstream connection closes, so live agent-status updates never arrive
// incrementally). A Route Handler streams the upstream body straight through
// to the browser, so each `data:` event is delivered as it's produced. Route
// handlers take precedence over afterFiles rewrites, so only this path is
// handled here; all other /api/* paths keep using the rewrite.

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_ORIGIN = process.env.ARCHER_API_ORIGIN || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const upstream = await fetch(`${API_ORIGIN}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await req.text(),
    // @ts-expect-error — Node fetch needs duplex for streaming request bodies
    duplex: "half",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
