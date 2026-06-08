// Server-only helper: forwards a request to the private FastAPI service with the
// shared bearer secret. The FastAPI URL and secret live exclusively in
// server-side env vars (never NEXT_PUBLIC_*), so they never reach the browser.
// This module must only be imported from route handlers (server runtime).

export async function forward(
  path: string,
  method: "GET" | "POST",
  body?: string,
): Promise<Response> {
  const base = (process.env.OPENCOLD_API_URL ?? "").replace(/\/$/, "");
  const secret = process.env.OPENCOLD_API_SECRET ?? "";

  if (!base) {
    return Response.json(
      { error: "OPENCOLD_API_URL is not configured on the server" },
      { status: 500 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${base}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${secret}`,
      },
      body,
      cache: "no-store",
    });
  } catch (e) {
    return Response.json(
      { error: `Cannot reach the OpenCold API: ${String(e)}` },
      { status: 502 },
    );
  }

  // Pass the upstream JSON + status straight through. Never log the body — it
  // may carry the user's API key or SMTP password.
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
