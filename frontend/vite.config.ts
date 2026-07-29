/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "Trainer",
        short_name: "Trainer",
        description: "Calisthenics progression tracker",
        theme_color: "#0f172a",
        background_color: "#0f172a",
        display: "standalone",
        start_url: "/",
        lang: "pl-PL",
        icons: [
          {
            src: "/favicon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any maskable",
          },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        // Never SPA-fallback API/docs — SW was serving index.html for /api/docs.
        navigateFallbackDenylist: [/^\/api(?:\/|$)/],
        runtimeCaching: [],
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
      // Logic layer: api clients, schemas, stores. Page shells covered by RTL smoke + Playwright.
      include: [
        "src/lib/**/*.ts",
        "src/stores/**/*.ts",
        "src/features/auth/api.ts",
        "src/features/training/api.ts",
      ],
      exclude: [
        "src/main.tsx",
        "src/lib/i18n.ts",
        "src/test/**",
        "src/**/*.d.ts",
        "src/vite-env.d.ts",
        "src/**/*.test.ts",
        "src/**/*.test.tsx",
        "src/**/*.spec.ts",
        "src/**/*.spec.tsx",
        "src/lib/db/cache.ts",
        "src/lib/db/persist.ts",
        "src/lib/db/open.ts",
        "src/lib/db/meta.ts",
        "src/lib/db/outbox.ts",
        "src/lib/db/types.ts",
        "src/stores/syncStore.ts",
        "src/stores/authStore.ts",
      ],
    },
  },
});
