/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The production build is written into the Python package so `pip install`
// ships the web app without Node. FastAPI serves it under /static/ and returns
// index.html for every other non-API path (client-side routing).
const api = process.env.AG_API ?? "http://127.0.0.1:8765";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  build: {
    outDir: path.resolve(import.meta.dirname, "../src/anomalyguard/monitor/static"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "charts", test: /node_modules[\\/](recharts|d3-|victory-vendor|es-toolkit|decimal\.js)/ },
            { name: "vendor", test: /node_modules[\\/](react|react-dom|react-router|scheduler|@tanstack|@radix-ui|cmdk|sonner)/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": api, "/health": api },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
}));
