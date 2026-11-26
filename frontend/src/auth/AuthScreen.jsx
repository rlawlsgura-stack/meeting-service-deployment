import { useState } from "react";
import { useAuth } from "./AuthProvider.jsx";
import { AuthRelayError } from "./authRelay.js";

function errorMessage(error) {
  if (error instanceof AuthRelayError) return error.message;
  return "계정 정보를 확인하지 못했습니다. 연결과 입력 내용을 확인해주세요.";
}

export default function AuthScreen() {
  const auth = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      if (mode === "login") await auth.signIn(email.trim(), password);
      else {
        const result = await auth.signUp(email.trim(), password);
        setMessage(result.confirmationRequired ? "인증 메일을 보냈습니다. 메일의 링크를 확인한 뒤 로그인해주세요." : "가입을 마쳤습니다. 로그인해주세요."); setPassword("");
      }
    } catch (failure) { setError(errorMessage(failure)); }
    finally { setBusy(false); }
  }
  return <main className="auth-page"><header className="auth-brand">모임 <span>팀 일정</span></header><section className="auth-content">
    <h1>{mode === "login" ? "로그인" : "이메일 회원가입"}</h1>
    <p className="muted">팀 워크스페이스의 일정과 회의 조건을 확인합니다.</p>
    {!auth.configured ? <div className="notice error">로그인 연결을 설정하지 못했습니다. 서비스 관리자에게 문의해주세요.</div> : <>
      <div className="auth-tabs"><button className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); setMessage(""); }} disabled={busy}>로그인</button><button className={mode === "signup" ? "active" : ""} onClick={() => { setMode("signup"); setError(""); setMessage(""); }} disabled={busy}>회원가입</button></div>
      {(error || auth.authError) && <div className="notice error" role="alert">{error || auth.authError}</div>}
      {auth.canRetry && <button className="button" onClick={auth.retryRestore} disabled={busy}>로그인 상태 다시 확인</button>}
      {message && <div className="notice" role="status">{message}</div>}
      <form onSubmit={submit}><label htmlFor="auth-email">이메일</label><input id="auth-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoFocus /><label htmlFor="auth-password">비밀번호</label><input id="auth-password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} minLength={mode === "signup" ? 8 : undefined} required />{mode === "signup" && <small>8자 이상의 비밀번호를 사용해주세요.</small>}<button className="button primary" disabled={busy} type="submit">{busy ? "확인 중…" : mode === "login" ? "로그인" : "인증 메일 받기"}</button></form>
    </>}
    <p className="auth-help">가입 후에는 관리자의 워크스페이스 멤버 등록이 필요할 수 있습니다.</p>
  </section></main>;
}
