import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { createAuthRelay } from "./authRelay.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [relay] = useState(() => createAuthRelay());
  const state = useSyncExternalStore(relay.subscribe, relay.getSnapshot, relay.getSnapshot);
  useEffect(() => { relay.start(); return relay.stop; }, [relay]);
  const value = useMemo(() => ({ ...state, user: state.session?.user || null, configured: true,
    getAccessToken: relay.getAccessToken, refreshAccessToken: relay.refreshAccessToken,
    invalidateSession: relay.invalidateSession, isCurrentUser: relay.isCurrentUser,
    signIn: relay.signIn, signUp: relay.signUp, signOut: relay.signOut, retryRestore: relay.retryRestore,
  }), [relay, state]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() { return useContext(AuthContext); }
