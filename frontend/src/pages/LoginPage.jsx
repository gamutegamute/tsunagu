import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setApproverName } from "../utils/approverName.js";

/**
 * 本部(PC)ログイン画面(/login、決定事項24)。
 *
 * MVPスコープのため、パスワードは見た目のみで実際の検証は行わない。
 * ログイン時に入力した担当者名は「承認者名」としてlocalStorageに保存し、
 * Incidentの承認操作(決定事項7・12、今後実装予定)で使用する想定。
 */
export default function LoginPage() {
  const navigate = useNavigate();
  const [nameInput, setNameInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    const trimmedName = nameInput.trim();
    if (!trimmedName) return;

    setApproverName(trimmedName);
    navigate("/dashboard", { replace: true });
  }

  return (
    <div className="login-page">
      <header className="topbar">
        <h1>ShelterOS</h1>
        <span className="login-header-label">本部管理システム</span>
      </header>

      <main className="login-main">
        <form className="login-card" onSubmit={handleSubmit}>
          <div className="login-brand">
            <div className="login-logo">
              <span className="login-logo-mark">S</span>
              <span className="login-logo-text">ShelterOS</span>
            </div>
            <p className="login-subtitle">本部管理システム ログイン</p>
          </div>

          <label>
            担当者名
            <input
              type="text"
              value={nameInput}
              onChange={(event) => setNameInput(event.target.value)}
              placeholder="例: 田中"
              required
            />
          </label>

          <label>
            パスワード
            <input
              type="password"
              value={passwordInput}
              onChange={(event) => setPasswordInput(event.target.value)}
              placeholder="••••••••"
            />
          </label>

          <button type="submit" className="login-button">
            ログイン →
          </button>

          <p className="login-note">ログイン後、本部ダッシュボードに移動します</p>
        </form>
      </main>
    </div>
  );
}
