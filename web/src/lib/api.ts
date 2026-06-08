// Client-side helpers for talking to the OpenCold API *through the Next.js BFF*.
// The browser only ever calls same-origin `/api/*` routes — it never sees the
// FastAPI URL or the shared secret (those live in server-only env vars).

export type Lead = Record<string, string>;

export type ProviderPayload = {
  type: "anthropic" | "openai" | "proxy";
  api_key: string;
  model: string;
  base_url?: string;
  max_tokens?: number;
};

export type RunPayload = {
  leads: Lead[];
  campaign: { title: string; description: string; pitch: string };
  identity: { name: string; email: string };
  profile: { company: string; role: string; bio: string; pitch: string };
  provider: ProviderPayload;
  options: {
    workers?: number;
    delay?: number;
    template?: string;
    system_prompt?: string;
    max_tokens?: number;
    do_resolve_websites?: boolean;
    do_enrich?: boolean;
    do_verify?: boolean;
    drop_invalid?: boolean;
  };
};

export type ResultRow = {
  name?: string;
  company?: string;
  email?: string;
  website?: string;
  generated_subject?: string;
  generated_email?: string;
  quality_warnings?: string;
  [key: string]: string | undefined;
};

export type Progress = { current?: number; total?: number; message?: string };

export type JobStatus = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  phase?: string | null;
  progress?: Progress | null;
  results?: ResultRow[] | null;
  error?: string | null;
};

export type SmtpConfig = {
  host: string;
  port: number;
  username: string;
  password: string;
  sender_email: string;
  sender_name?: string;
  use_tls?: boolean;
};

export type SendItem = { email: string; name?: string; subject: string; body: string };

export type SendResponse = {
  results: { email: string; sent: boolean; error?: string | null }[];
  sent: number;
  failed: number;
};

async function asJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Bad response (${res.status}): ${text.slice(0, 200)}`);
  }
  if (!res.ok) {
    const detail =
      (body as { detail?: string; error?: string })?.detail ??
      (body as { error?: string })?.error ??
      res.statusText;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return body as T;
}

export async function startRun(payload: RunPayload): Promise<{ job_id: string }> {
  const res = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return asJson<{ job_id: string }>(res);
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<JobStatus> {
  const res = await fetch(`/api/run/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
    signal,
  });
  return asJson<JobStatus>(res);
}

/** Poll a job until it finishes (or the signal aborts), reporting each tick. */
export async function pollRun(
  jobId: string,
  onUpdate: (job: JobStatus) => void,
  { intervalMs = 2000, signal }: { intervalMs?: number; signal?: AbortSignal } = {},
): Promise<JobStatus> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const job = await getJob(jobId, signal);
    onUpdate(job);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise<void>((resolve, reject) => {
      const id = setTimeout(resolve, intervalMs);
      signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(id);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}

export async function sendEmails(
  smtp: SmtpConfig,
  items: SendItem[],
): Promise<SendResponse> {
  const res = await fetch("/api/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ smtp, items }),
  });
  return asJson<SendResponse>(res);
}

export async function testSmtp(smtp: SmtpConfig): Promise<{ ok: boolean; error: string | null }> {
  const res = await fetch("/api/smtp/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(smtp),
  });
  return asJson<{ ok: boolean; error: string | null }>(res);
}

/**
 * Minimal CSV parser → array of row objects keyed by lower-cased headers.
 * Handles quoted fields, escaped quotes (""), and CRLF. Good enough for the
 * small lead lists this tool processes; the Python side does the heavy lifting.
 */
export function parseCsv(text: string): Lead[] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;

  const pushField = () => {
    row.push(field);
    field = "";
  };
  const pushRow = () => {
    pushField();
    rows.push(row);
    row = [];
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      pushField();
    } else if (ch === "\n") {
      pushRow();
    } else if (ch === "\r") {
      // swallow; \n handles the row break
    } else {
      field += ch;
    }
  }
  // flush trailing field/row if the file didn't end with a newline
  if (field.length > 0 || row.length > 0) pushRow();

  const nonEmpty = rows.filter((r) => r.some((c) => c.trim() !== ""));
  if (nonEmpty.length < 2) return [];

  const headers = nonEmpty[0].map((h) => h.trim().toLowerCase());
  return nonEmpty.slice(1).map((cells) => {
    const obj: Lead = {};
    headers.forEach((h, idx) => {
      if (h) obj[h] = (cells[idx] ?? "").trim();
    });
    return obj;
  });
}
