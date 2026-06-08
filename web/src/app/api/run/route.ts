import { forward } from "@/lib/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Start a draft-generation job. Proxies to FastAPI POST /v1/run.
export async function POST(req: Request) {
  const body = await req.text();
  return forward("/v1/run", "POST", body);
}
