import { Navigate, useLocation } from "react-router";
import { useAuth } from "../auth/AuthContext.jsx";

export default function RequireApprover({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <main className="auth-loading">認証状態を確認しています</main>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.role !== "hq") return <Navigate to="/field-report" replace />;
  return children;
}
