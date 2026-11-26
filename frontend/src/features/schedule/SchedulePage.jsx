import { useEffect, useState } from "react";
import AppShell from "../../components/AppShell.jsx";
import useSchedule from "./useSchedule.js";
import RequestComposer from "./components/RequestComposer.jsx";
import RequestSummary from "./components/RequestSummary.jsx";
import MeetingReview from "./components/MeetingReview.jsx";
import ScheduleAgenda from "./components/ScheduleAgenda.jsx";
import "./schedule.css";

export default function SchedulePage() {
  const schedule = useSchedule();
  const { me, catalog, capabilities, session, busy, error } = schedule;
  const [date, setDate] = useState("");
  const [planning, setPlanning] = useState(false);
  const [formKey, setFormKey] = useState(0);
  useEffect(() => {
    if (!date && catalog) {
      const now = new Date();
      const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      setDate(catalog.dates?.[0] || today);
    }
  }, [catalog, date]);
  useEffect(() => { if (session && !session.event) setPlanning(true); }, [session?.id]);
  function newMeeting() { schedule.resetInquiry(); setFormKey((value) => value + 1); setPlanning(true); }
  const navigation = [
    ...(capabilities.registration ? [{ id: "schedule", label: "내 등록 일정", icon: "calendar" }] : []),
    { id: "new", label: capabilities.rooms ? "회의 조율" : "공통 시간 조회", icon: "plus" },
  ];
  const open = planning || !capabilities.registration;
  const inquiryTitle = capabilities.rooms ? "회의 조율" : "공통 시간 조회";
  return <AppShell account={me} title={open ? inquiryTitle : "내 등록 일정"} navigation={me?.membership ? navigation : []} current={open ? "new" : "schedule"} busy={busy} onNavigate={(next) => next === "new" ? newMeeting() : setPlanning(false)}>
    {error && <div className="notice error" role="alert"><span>{error.message}</span><button className="link-button" onClick={schedule.clearError}>닫기</button></div>}
    {!me ? <div className="page-loading" role="status">{busy ? "워크스페이스 확인 중…" : <button className="button" onClick={schedule.reloadWorkspace}>다시 연결</button>}</div> : !me.membership ? <section className="membership-message"><h2>워크스페이스 접근 권한이 필요합니다.</h2><p>{me.message || "관리자에게 계정의 멤버 등록을 요청해주세요."}</p><button className="button" onClick={schedule.reloadWorkspace} disabled={busy}>등록 상태 다시 확인</button></section> : !catalog || !date ? <div className="page-loading">자료 확인 중…</div> : <>
      <div className={open ? "schedule-workbench planning-open" : "schedule-workbench"}>
        {capabilities.registration && !open && <ScheduleAgenda date={date} setDate={setDate} events={schedule.events} catalog={catalog} busy={busy} onNew={newMeeting} onRefresh={schedule.refreshEvents} />}
        {open && <aside className="planning-panel" aria-label={inquiryTitle}><div className="planning-header"><h2>{inquiryTitle}</h2><div className="button-row"><button className="plain-button" onClick={newMeeting} disabled={busy}>새 문의</button>{capabilities.registration && <button className="plain-button" onClick={() => setPlanning(false)} aria-label="회의 조율 닫기">닫기</button>}</div></div><div className="planning-content"><div className="request-panel"><RequestComposer key={formKey} catalog={catalog} session={session} busy={busy} capabilities={capabilities} onQuery={schedule.sendMessage} /><RequestSummary session={session} catalog={catalog} comparison={schedule.comparison} /></div><MeetingReview session={session} catalog={catalog} capabilities={capabilities} busy={busy} comparison={schedule.comparison} history={schedule.history} onDecision={schedule.decide} onRetry={() => schedule.sendMessage("현재 조건으로 다시 조회해주세요.")} /></div></aside>}
      </div>
    </>}
  </AppShell>;
}
