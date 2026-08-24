export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { status: "healthy", service: "promotion-web" },
    { status: 200, headers: { "Cache-Control": "no-store" } }
  );
}
