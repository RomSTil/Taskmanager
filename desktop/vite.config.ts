import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ["VITE_", "TAURI_ENV_"],
  build: {
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: process.env.TAURI_ENV_DEBUG ? false : "esbuild",
    sourcemap: Boolean(process.env.TAURI_ENV_DEBUG),
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("@tiptap") || id.includes("prosemirror")) return "editor";
          if (id.includes("react") || id.includes("@tanstack")) return "react";
          if (id.includes("@dnd-kit")) return "dragdrop";
          if (id.includes("@tauri-apps")) return "tauri";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/testSetup.ts"],
  },
});
