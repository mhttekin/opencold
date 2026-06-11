import { forward } from "@/lib/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Verify SMTP credentials without sending. Proxies to FastAPI POST /v1/smtp/test.
export async function POST(req: Request) {
  const body = await req.text();
  return forward("/v1/smtp/test", "POST", body);
}
