import type {
  ChatResponse,
  EobScanResponse,
  HealthResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore JSON parse errors, use default message
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export async function getHealth(): Promise<HealthResponse> {
  return handle<HealthResponse>(await fetch(`${BASE_URL}/api/health`));
}

export async function sendChat(
  message: string,
  billedAmount?: number,
): Promise<ChatResponse> {
  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      billed_amount: billedAmount ?? null,
    }),
  });
  return handle<ChatResponse>(res);
}

export async function scanEob(file: File): Promise<EobScanResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/api/eob/scan`, {
    method: "POST",
    body: form,
  });
  return handle<EobScanResponse>(res);
}
