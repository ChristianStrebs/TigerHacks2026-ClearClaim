import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const proxy = {
    "/api": {
      target:
        process.env.VITE_API_PROXY_TARGET ??
        env.VITE_API_PROXY_TARGET ??
        "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };
  return {
    plugins: [react()],
    server: { host: true, port: 5173, strictPort: true, proxy },
    preview: { host: true, port: 4173, strictPort: true, proxy },
  };
});
