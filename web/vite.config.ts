/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the UI runs on :5173 and forwards API calls to the FastAPI
// server (`pricor serve --no-browser`, port 8000 by default).
const API = process.env.PRICOR_API ?? "http://127.0.0.1:8000";
const API_PATHS = ["/imports"];

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/pricor/web_dist", emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, { target: API, changeOrigin: false }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 15000,
  },
});
