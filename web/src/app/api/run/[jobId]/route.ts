import { forward } from "@/lib/upstream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Poll a job's status/results. Proxies to FastAPI GET /v1/run/{jobId}.
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await ctx.params;
  return forward(`/v1/run/${encodeURIComponent(jobId)}`, "GET");
}
