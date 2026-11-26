import { useAuth } from "../auth/AuthProvider.jsx";
import Icon from "./Icon.jsx";

export default function AppShell({ children, account, title = "일정", navigation, current, onNavigate, busy }) {
  const auth = useAuth();
  const name = account?.user?.display_name || auth.user?.email?.split("@")[0] || "사용자";
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(event) => event.preventDefault()}>모임<span>회의 조율</span></a>
      <p className="workspace-label">{account?.workspace?.name || "워크스페이스"}</p>
      <nav aria-label="주 메뉴">{navigation.map((item) => <button key={item.id} className={current === item.id ? "nav-item active" : "nav-item"} disabled={busy} onClick={() => onNavigate(item.id)}><Icon name={item.icon} size={17} />{item.label}</button>)}</nav>
    </aside>
    <div className="application-body"><header className="app-header"><h1>{title}</h1><div className="account-menu"><span className="avatar" aria-hidden="true">{name.slice(0, 1)}</span><div><strong>{name}</strong><small>{account?.user?.email || auth.user?.email}</small></div><button className="plain-button" onClick={auth.signOut}>로그아웃</button></div></header><main className="workspace-content">{children}</main></div>
  </div>;
}
