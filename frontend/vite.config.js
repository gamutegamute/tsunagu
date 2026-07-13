import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  // 本番ビルドではFastAPIの/static静的マウントに合わせて"/static/"にする。
  // 開発サーバー(vite dev)ではSPAのページルートがbasenameなし(ルート直下)
  // 前提のため、devサーバー自体もルートで配信するようにしないと
  // /login・/dashboard等のパスがReact Routerとかみ合わず真っ白になる。
  base: command === "build" ? "/static/" : "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
}));
