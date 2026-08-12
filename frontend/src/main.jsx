import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import FieldReportPage from "./pages/FieldReportPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import RequireApprover from "./pages/RequireApprover.jsx";
import IncidentPage from "./pages/IncidentPage.jsx";
import HistoryPage from "./pages/HistoryPage.jsx";
import ShelterDetailPage from "./pages/ShelterDetailPage.jsx";
import TimelinePage from "./pages/TimelinePage.jsx";
import DevPreview from "./DevPreview.jsx";
import DemoControlPage from "./pages/DemoControlPage.jsx";
import { AuthProvider } from "./auth/AuthContext.jsx";
import "./styles.css";

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
    .then(() => navigator.serviceWorker.ready)
    .then(() => window.dispatchEvent(new Event("tsunagu:pwa-ready")))
    .catch(() => {
      // The regular web app remains usable when a browser rejects PWA registration.
    });
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/field-report" replace />} />
          <Route path="/field-report" element={<FieldReportPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/incident" element={<RequireApprover><IncidentPage /></RequireApprover>} />
          <Route
            path="/dashboard"
            element={
              <RequireApprover>
                <DashboardPage />
              </RequireApprover>
            }
          />
          <Route
            path="/dashboard/shelters/:shelterId"
            element={
              <RequireApprover>
                <ShelterDetailPage />
              </RequireApprover>
            }
          />
          <Route
            path="/dashboard/timeline"
            element={
              <RequireApprover>
                <TimelinePage />
              </RequireApprover>
            }
          />
          <Route path="/dev-preview" element={<RequireApprover><DevPreview /></RequireApprover>} />
          <Route path="/demo-control" element={<RequireApprover><DemoControlPage /></RequireApprover>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
);
