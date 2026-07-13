import { Navigate } from "react-router-dom";
import { isApproverLoggedIn } from "../utils/approverName.js";

/**
 * 本部(PC)ログイン(決定事項24)が済んでいない状態で/dashboardに
 * 直接アクセスされた場合、/loginへリダイレクトするガード。
 */
export default function RequireApprover({ children }) {
  if (!isApproverLoggedIn()) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
