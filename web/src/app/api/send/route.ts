import { forward } from "@/lib/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Send selected drafts via SMTP. Proxies to FastAPI POST /v1/send.
export async function POST(req: Request) {
  const body = await req.text();
  return forward("/v1/send", "POST", body);
}
