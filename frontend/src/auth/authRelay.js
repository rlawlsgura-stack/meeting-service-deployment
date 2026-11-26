const STORAGE_KEY = "moim.auth.relay";
const EXPIRED = "로그인이 만료되었습니다. 다시 로그인해주세요.";
const CONNECTION = "인증 서버에 연결하지 못했습니다. 연결을 확인해주세요.";

export class AuthRelayError extends Error {
  constructor(message, status = 0, code = "connection_error") {
    super(message); this.status = status; this.code = code;
  }
}

function publicMessage(status, code) {
  if (code === "EMAIL_UNCONFIRMED") return "이메일 인증을 완료한 뒤 로그인해주세요.";
  if (code === "AUTH_REJECTED") return "이메일과 비밀번호를 확인해주세요.";
  if (code === "SIGNUP_REJECTED" && status === 409) return "이미 가입한 이메일입니다. 로그인해주세요.";
  if (code === "WEAK_PASSWORD") return "더 안전한 비밀번호를 입력해주세요.";
  if (status === 429) return "요청이 많습니다. 잠시 뒤 다시 시도해주세요.";
  if (status >= 500 || !status) return CONNECTION;
  return "계정 정보를 확인하지 못했습니다. 연결과 입력 내용을 확인해주세요.";
}

function validUser(user) {
  return Boolean(user && typeof user.id === "string" && user.id && typeof user.email === "string");
}

function tokenSession(packet, now) {
  if (!validUser(packet?.user) || packet.user_id !== packet.user.id ||
      typeof packet.access_token !== "string" || !packet.access_token ||
      typeof packet.refresh_token !== "string" || !packet.refresh_token ||
      !Number.isFinite(packet.expires_in) || packet.expires_in <= 0) {
    throw new AuthRelayError("인증 응답을 확인하지 못했습니다. 다시 시도해주세요.", 502, "invalid_response");
  }
  return { user: packet.user, access_token: packet.access_token, refresh_token: packet.refresh_token,
    expires_at: now() + packet.expires_in * 1000 };
}

/** 서버가 확인한 계정만 공개한다. 이전 계정의 늦은 응답은 상태와 저장소를 바꾸지 못한다. */
export function createAuthRelay({ fetchImpl = (...args) => fetch(...args), browser = globalThis.window, now = () => Date.now() } = {}) {
  let state = { session: null, loading: true, authError: null, canRetry: false };
  let active = false, generation = 0, current = null, refreshing = null;
  const listeners = new Set();
  const emit = (changes) => { state = { ...state, ...changes }; for (const listener of listeners) listener(); };
  const owns = (version) => active && generation === version;
  function storage(name) { try { return browser?.[name]; } catch { return null; } }
  function removeAuth() { try { storage("sessionStorage")?.removeItem(STORAGE_KEY); } catch { /* Storage is optional. */ } }
  function clearBusinessStorage() {
    for (const name of ["localStorage", "sessionStorage"]) {
      const store = storage(name);
      try { for (const key of Object.keys(store || {})) {
        if (key === "schedule-session-id" || ["moim.schedule.", "moim.time.", "moim.workspace."].some((prefix) => key.startsWith(prefix))) store.removeItem(key);
      } } catch { /* Storage is optional. */ }
    }
  }
  function cleanLegacy() {
    let migrated = false;
    for (const name of ["localStorage", "sessionStorage"]) {
      const store = storage(name);
      try { for (const key of Object.keys(store || {})) {
        if (key === "moim.auth" || key.startsWith("moim.auth-")) { store.removeItem(key); migrated = true; }
        if (key === "schedule-session-id" || key.startsWith("moim.schedule.") || key.startsWith("moim.time.")) store.removeItem(key);
      } } catch { /* Storage is optional. */ }
    }
    if (migrated) clearBusinessStorage();
    // Confirmation links may contain provider tokens. They are never adopted as a session.
    try {
      const hash = browser?.location?.hash || "";
      if (/(?:^#|&)(?:access_token|refresh_token|error|error_description)=/.test(hash)) {
        browser.history.replaceState(null, "", browser.location.pathname + browser.location.search);
      }
    } catch { /* History can be unavailable in embedded browsers. */ }
  }
  function savedSession() {
    try {
      const saved = JSON.parse(storage("sessionStorage")?.getItem(STORAGE_KEY) || "null");
      if (validUser(saved?.user) && typeof saved.access_token === "string" && saved.access_token &&
          typeof saved.refresh_token === "string" && saved.refresh_token && Number.isFinite(saved.expires_at)) return saved;
    } catch { /* Invalid local data is not an authenticated session. */ }
    removeAuth(); return null;
  }
  function publish(next, version) {
    if (!owns(version)) return false;
    if (current?.user.id && current.user.id !== next.user.id) clearBusinessStorage();
    current = next;
    try { storage("sessionStorage")?.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* In-memory login still works. */ }
    emit({ session: next, loading: false, authError: null, canRetry: false }); return true;
  }
  function clear(message = null) {
    current = null; refreshing = null; removeAuth(); clearBusinessStorage();
    emit({ session: null, loading: false, authError: message, canRetry: false });
  }
  async function request(action, { method = "POST", body, token } = {}) {
    let response;
    try { response = await fetchImpl(`/api/auth/${action}`, { method, cache: "no-store",
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) }); }
    catch { throw new AuthRelayError(CONNECTION); }
    if (response.status === 204) return null;
    let packet;
    try { packet = await response.json(); }
    catch { throw new AuthRelayError("인증 응답을 확인하지 못했습니다. 다시 시도해주세요.", 502, "invalid_response"); }
    if (!response.ok) throw new AuthRelayError(publicMessage(response.status, packet?.code), response.status, packet?.code || "auth_error");
    return packet;
  }
  async function restore() {
    const version = ++generation;
    cleanLegacy(); current = null; refreshing = null;
    emit({ session: null, loading: true, authError: null, canRetry: false });
    const saved = savedSession();
    if (!saved) { if (owns(version)) clear(); return; }
    try {
      let next;
      try {
        const packet = await request("user", { method: "GET", token: saved.access_token });
        if (!owns(version)) return;
        if (!validUser(packet?.user) || packet.user.id !== saved.user.id) throw new AuthRelayError(EXPIRED, 401, "identity_changed");
        next = { ...saved, user: packet.user };
      } catch (error) {
        if (error.status !== 401) throw error;
        if (!owns(version)) return;
        const packet = await request("refresh", { body: { refresh_token: saved.refresh_token } });
        next = tokenSession(packet, now);
        if (next.user.id !== saved.user.id) throw new AuthRelayError(EXPIRED, 401, "identity_changed");
      }
      publish(next, version);
    } catch (error) {
      if (!owns(version)) return;
      if ([401, 403].includes(error.status)) clear(EXPIRED);
      else emit({ loading: false, authError: "로그인 상태를 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도해주세요.", canRetry: true });
    }
  }
  async function refreshAccessToken(expectedUserId) {
    if (!active || !current || (expectedUserId && current.user.id !== expectedUserId)) return null;
    const version = generation, candidate = current;
    if (refreshing?.version === version) return refreshing.promise;
    const job = { version, promise: null };
    job.promise = (async () => {
      try {
        const packet = await request("refresh", { body: { refresh_token: candidate.refresh_token } });
        if (!owns(version) || current?.user.id !== candidate.user.id) return null;
        const next = tokenSession(packet, now);
        if (next.user.id !== candidate.user.id) { ++generation; clear(EXPIRED); return null; }
        return publish(next, version) ? next.access_token : null;
      } catch (error) {
        if (!owns(version)) return null;
        if ([401, 403].includes(error.status)) { ++generation; clear(EXPIRED); return null; }
        throw error;
      } finally { if (refreshing === job) refreshing = null; }
    })();
    refreshing = job; return job.promise;
  }
  return {
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    getSnapshot: () => state,
    start: () => { active = true; return restore(); },
    stop: () => { active = false; ++generation; refreshing = null; },
    retryRestore: () => active ? restore() : Promise.resolve(),
    isCurrentUser: (id) => Boolean(active && id && current?.user.id === id),
    getAccessToken: async (expectedUserId) => {
      if (!active || !current || (expectedUserId && current.user.id !== expectedUserId)) return null;
      if (current.expires_at <= now() + 30000) return refreshAccessToken(expectedUserId);
      return current.access_token;
    },
    refreshAccessToken,
    invalidateSession: (expectedUserId) => {
      if (expectedUserId && current?.user.id !== expectedUserId) return;
      ++generation; clear(EXPIRED);
    },
    signIn: async (email, password) => {
      if (!active) return;
      const version = ++generation;
      clear();
      const packet = await request("login", { body: { email, password } });
      if (!owns(version)) return;
      const next = tokenSession(packet, now);
      publish(next, version); return { user: next.user };
    },
    signUp: async (email, password) => {
      const version = generation;
      const packet = await request("signup", { body: { email, password } });
      if (!owns(version)) return { confirmationRequired: false };
      if (typeof packet?.user_id !== "string" || typeof packet.email_confirmation_required !== "boolean") {
        throw new AuthRelayError("가입 응답을 확인하지 못했습니다. 다시 시도해주세요.", 502, "invalid_response");
      }
      return { confirmationRequired: packet.email_confirmation_required };
    },
    signOut: async () => {
      const token = current?.access_token, version = ++generation;
      clear();
      if (!token) return;
      try { await request("logout", { token }); }
      catch { if (owns(version)) emit({ authError: "이 기기에서는 로그아웃했습니다. 서버의 세션 종료는 확인하지 못했습니다." }); }
    },
  };
}
