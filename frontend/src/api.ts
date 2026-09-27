import { accessToken, resetSession, sessionsEnabled } from "./session";
import type {
  ChatHistoryItem,
  ChatResponse,
  ChatTurn,
  EobScanResponse,
  HealthResponse,
  PlanResponse,
  SampleFile,
} from "./types";

// Empty means same-origin /api (proxied to FastAPI during Vite development).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const READ_TIMEOUT_MS = 20_000;
const AI_TIMEOUT_MS = 180_000;
export const UPLOAD_ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.webp,.heic,.heif,application/pdf,image/png,image/jpeg,image/webp,image/heic,image/heif";

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Public backend routes; they must keep working even if sign-in fails.
const PUBLIC_PATHS = ["/api/health", "/api/samples"];

async function authHeaders(path: string, init: RequestInit): Promise<Headers> {
  const headers = new Headers(init.headers);
  if (PUBLIC_PATHS.some((prefix) => path.startsWith(prefix))) return headers;
  try {
    const token = await accessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  } catch (error) {
    throw new ApiError(
      error instanceof Error
        ? error.message
        : "We couldn't start your session. Refresh the page.",
    );
  }
  return headers;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = READ_TIMEOUT_MS,
  read: (response: Response) => Promise<T> = (response) => response.json(),
  retried = false,
): Promise<T> {
  const headers = await authHeaders(path, init);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    if (response.status === 401 && sessionsEnabled && !retried) {
      await resetSession();
      return await request(path, init, timeoutMs, read, true);
    }
    if (!response.ok) {
      let message = `Request failed (${response.status}). Please try again.`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") message = body.detail;
        else if (Array.isArray(body.detail))
          message = "Check the entered values and file, then try again.";
      } catch {
        // A proxy may return HTML instead of FastAPI's JSON error body.
      }
      throw new ApiError(message, response.status);
    }
    return await read(response);
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError(
        "The request timed out. The server may still be processing it. Refresh the plan before repeating a plan change.",
      );
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      error instanceof TypeError
        ? "Cannot reach the backend. Check that FastAPI is running and the API address is correct."
        : "The backend returned an unreadable response. Check that the matching backend version is running.",
    );
  } finally {
    clearTimeout(timer);
  }
}

function jsonPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    AI_TIMEOUT_MS,
  );
}

export function uploadForm(file: File): FormData {
  const mimeByExtension: Record<string, string> = {
    pdf: "application/pdf",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    webp: "image/webp",
    heic: "image/heic",
    heif: "image/heif",
  };
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  // Some browsers omit HEIC MIME types. Supply one only when unknown/generic.
  const mime =
    !file.type || file.type === "application/octet-stream"
      ? mimeByExtension[extension]
      : file.type;
  if (!Object.values(mimeByExtension).includes(mime))
    throw new ApiError("Choose a PDF, PNG, JPEG, WebP, HEIC, or HEIF file.");
  if (!file.size) throw new ApiError("The selected file is empty.");
  if (file.size > 15 * 1024 * 1024)
    throw new ApiError("Choose a file no larger than 15 MB.");
  const form = new FormData();
  form.append("file", new Blob([file], { type: mime }), file.name);
  return form;
}

export const getHealth = () => request<HealthResponse>("/api/health");
export const getPlan = () => request<PlanResponse>("/api/plan");
export const getSamples = () => request<SampleFile[]>("/api/samples");
export const chooseSamplePlan = () =>
  jsonPost<PlanResponse>("/api/plan/sample");
export const clearPlan = () => jsonPost<PlanResponse>("/api/plan/clear");
export const getScans = () => request<EobScanResponse[]>("/api/eob/scans");
export const deleteScan = (scanId: string) =>
  request<void>(
    `/api/eob/scans/${encodeURIComponent(scanId)}`,
    { method: "DELETE" },
    READ_TIMEOUT_MS,
    async () => undefined,
  );
export const getChatHistory = () =>
  request<ChatHistoryItem[]>("/api/chat/history");
export const submitPlanText = (title: string, text: string) =>
  jsonPost<PlanResponse>("/api/plan/text", { title, text });
export const uploadPlan = (file: File) =>
  request<PlanResponse>(
    "/api/plan/upload",
    { method: "POST", body: uploadForm(file) },
    AI_TIMEOUT_MS,
  );
export const scanEob = (file: File) =>
  request<EobScanResponse>(
    "/api/eob/scan",
    { method: "POST", body: uploadForm(file) },
    AI_TIMEOUT_MS,
  );
export const sendChat = (message: string, history: ChatTurn[] = []) =>
  jsonPost<ChatResponse>("/api/chat", { message, history });

export async function downloadSample(sample: SampleFile): Promise<File> {
  // Construct the known backend route; never fetch an arbitrary response URL.
  const blob = await request<Blob>(
    `/api/samples/${encodeURIComponent(sample.name)}`,
    {},
    READ_TIMEOUT_MS,
    (response) => response.blob(),
  );
  return new File([blob], sample.name, { type: "application/pdf" });
}
