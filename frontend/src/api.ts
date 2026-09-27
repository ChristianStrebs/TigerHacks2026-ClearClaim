import type {
  ChatResponse,
  EobScanResponse,
  HealthResponse,
  PlanResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // ignore JSON parse errors, use default message
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function uploadForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

export async function getHealth(): Promise<HealthResponse> {
  return handle<HealthResponse>(await fetch(`${BASE_URL}/api/health`));
}

export async function getPlan(): Promise<PlanResponse> {
  return handle<PlanResponse>(await fetch(`${BASE_URL}/api/plan`));
}

export async function uploadPlan(file: File): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/plan/upload`, {
    method: "POST",
    body: uploadForm(file),
  });
  return handle<PlanResponse>(res);
}

export async function resetPlan(): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/plan/reset`, { method: "POST" });
  return handle<PlanResponse>(res);
}

export async function sendChat(message: string): Promise<ChatResponse> {
  const res = await fetch(`${BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return handle<ChatResponse>(res);
}

export async function scanEob(file: File): Promise<EobScanResponse> {
  const res = await fetch(`${BASE_URL}/api/eob/scan`, {
    method: "POST",
    body: uploadForm(file),
  });
  return handle<EobScanResponse>(res);
}
