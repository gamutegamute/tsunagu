import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, devLogin, fetchAuthConfig, fetchCurrentUser, logout } from "../api.js";
import { clearApproverName, setApproverName } from "../utils/approverName.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [mode, setMode] = useState("loading");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [config, currentUser] = await Promise.all([fetchAuthConfig(), fetchCurrentUser()]);
      setMode(config.mode);
      setUser(currentUser);
      setApproverName(currentUser.name);
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) console.error(error);
      setUser(null);
      clearApproverName();
      try {
        setMode((await fetchAuthConfig()).mode);
      } catch {
        setMode("unavailable");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo(() => ({
    user,
    mode,
    loading,
    refresh,
    async loginForDevelopment(role) {
      await devLogin(role);
      await refresh();
    },
    async signOut() {
      await logout();
      await refresh();
    },
  }), [user, mode, loading, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
