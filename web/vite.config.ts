import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run build` writes straight into the Python package so `blueprint serve` needs no Node.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../blueprint/web/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "node" },
});
