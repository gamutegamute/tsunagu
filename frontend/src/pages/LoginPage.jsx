import { useState } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "../auth/AuthContext.jsx";

export default function LoginPage() {
  const { user, mode, loading, loginForDevelopment } = useAuth();
  const location = useLocation();
  const [error, setError] = useState("");
  const from = location.state?.from || "/dashboard";

  if (!loading && user) {
    return <Navigate to={user.role === "hq" ? from : "/field-report"} replace />;
  }

  async function handleDevelopmentLogin(role) {
    setError("");
    try {
      await loginForDevelopment(role);
    } catch {
      setError("ローカルログインに失敗しました");
    }
  }

  return (
    <div className="login-page">
      <header className="topbar">
        <h1>TSUNAGU</h1>
        <span className="login-header-label">本部・現場職員ログイン</span>
      </header>

      <main className="login-main">
        <section className="login-card">
          <div className="login-brand">
            <div className="login-logo">
              <img
                className="login-logo-image"
                src={`${import.meta.env.BASE_URL}logo/logo-stacked.png`}
                alt="TSUNAGU"
              />
            </div>
            <p className="login-subtitle">登録済みのGoogleアカウントでログイン</p>
          </div>

          {mode === "cognito" ? (
            <a className="login-button login-google-button" href={`/api/auth/login?next=${encodeURIComponent(from)}`}>
              Googleでログイン
            </a>
          ) : mode === "dev" ? (
            <div className="dev-login-actions">
              <p className="login-note">ローカル開発モード</p>
              <button type="button" className="login-button" onClick={() => handleDevelopmentLogin("hq")}>
                本部職員としてログイン
              </button>
              <button type="button" className="outline-button" onClick={() => handleDevelopmentLogin("field")}>
                現場職員としてログイン
              </button>
            </div>
          ) : (
            <p className="form-error-message">認証設定が完了していません</p>
          )}

          {error && <p className="form-error-message">{error}</p>}
          <a className="text-link-button" href="/field-report">ログインせず現場報告を送る</a>
        </section>
      </main>
    </div>
  );
}
