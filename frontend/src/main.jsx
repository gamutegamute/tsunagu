import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import DevPreview from "./DevPreview.jsx";
import "./styles.css";

// 開発確認用: URLのハッシュに #dev-preview を指定した場合だけプレビューページを表示する。
// 本番の画面(ハッシュなし)には一切影響しない。ハッシュの変更に追従できるよう再読み込みする。
window.addEventListener("hashchange", () => window.location.reload());

const RootComponent = window.location.hash === "#dev-preview" ? DevPreview : App;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RootComponent />
  </React.StrictMode>,
);
