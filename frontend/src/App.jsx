import { useAuth } from "./auth/AuthProvider.jsx";
import AuthScreen from "./auth/AuthScreen.jsx";
import SchedulePage from "./features/schedule/SchedulePage.jsx";

export default function App() {
  const auth = useAuth();
  if (auth.loading) return <div className="page-loading" role="status">계정 상태 확인 중…</div>;
  if (!auth.user) return <AuthScreen />;
  return <SchedulePage key={auth.user.id} />;
}
