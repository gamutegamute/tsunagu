import { useAuth } from "../auth/AuthContext.jsx";

export default function AuthStatus() {
  const { user, signOut } = useAuth();

  if (!user) return <a className="topbar-auth-link" href="/login">ログイン</a>;

  return (
    <div className="auth-status">
      <span>{user.name}</span>
      <span className="auth-role">{user.role === "hq" ? "本部" : "現場"}</span>
      <button type="button" className="topbar-auth-button" onClick={signOut}>ログアウト</button>
    </div>
  );
}
