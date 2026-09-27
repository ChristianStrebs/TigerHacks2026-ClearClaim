// Empty means same-origin /api (proxied to FastAPI during Vite development).
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
  /\/+$/,
  "",
);
