import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base URL is injected at build/dev time via VITE_API_BASE_URL.
// In dev we also proxy /api to the backend so the app works with no config.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
