import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `envDir: ".."` lets the SPA read the single root `.env` (see .env.example),
// matching the backend which also reads the repo-root `.env`.
export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
