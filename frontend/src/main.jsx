import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import FieldReportPage from "./pages/FieldReportPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import DevPreview from "./DevPreview.jsx";
import "./styles.css";

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/service-worker.js");
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter basename="/static">
      <Routes>
        <Route path="/" element={<Navigate to="/field-report" replace />} />
        <Route path="/field-report" element={<FieldReportPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/dev-preview" element={<DevPreview />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
