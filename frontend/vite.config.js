import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig(({ command }) => ({
  // 本番ビルドではFastAPIの/static静的マウントに合わせて"/static/"にする。
  // 開発サーバー(vite dev)ではSPAのページルートがbasenameなし(ルート直下)
  // 前提のため、devサーバー自体もルートで配信するようにしないと
  // /login・/dashboard等のパスがReact Routerとかみ合わず真っ白になる。
  base: command === "build" ? "/static/" : "/",
  plugins: [
    react(),
    VitePWA({
      filename: "service-worker.js",
      registerType: "prompt",
      injectRegister: null,
      manifest: {
        name: "TSUNAGU",
        short_name: "TSUNAGU",
        start_url: "/field-report",
        display: "standalone",
        background_color: "#f5f7f4",
        theme_color: "#16201f",
        icons: [
          {
            src: "/static/logo/logo-icon.png",
            sizes: "1315x1471",
            type: "image/png",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,webmanifest}"],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        modifyURLPrefix: {
          "": "/static/",
        },
        manifestTransforms: [
          async (entries) => ({
            manifest: entries.filter((entry) => entry.url.startsWith("/static/")),
            warnings: [],
          }),
        ],
        navigateFallback: "/static/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/health$/, /^\/ready$/],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
  },
}));
