import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Lets the app import the shared sample JSON that lives outside frontend/.
    alias: { "@shared": path.resolve(here, "../shared") },
  },
  server: {
    port: 5173,
    fs: { allow: [".."] },
    // In dev, /api/* is forwarded to the backend, so no CORS setup is needed.
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
