import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev the browser only ever talks to Vite; /api/* is proxied to FastAPI so the
// session cookie is same-origin and no secrets ever reach the frontend bundle.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: apiTarget, changeOrigin: true } },
  },
  build: {
    chunkSizeWarningLimit: 600, // recharts alone is ~560 kB (157 kB gzipped)
    rollupOptions: {
      output: { manualChunks: { charts: ["recharts"], vendor: ["react", "react-dom", "@tanstack/react-query"] } },
    },
  },
});
