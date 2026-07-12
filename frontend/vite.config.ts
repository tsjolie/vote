import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves the built assets from /app/static; during dev we proxy the
// API to a locally-running uvicorn instance.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
