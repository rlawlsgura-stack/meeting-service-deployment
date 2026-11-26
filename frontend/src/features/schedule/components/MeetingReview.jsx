import { useEffect, useState } from "react";
import { dateLabel, timeRange } from "../formatSchedule.js";
import ProcessingDetails from "./ProcessingDetails.jsx";

const statusText = {
  awaiting_request: "회의 조건을 입력해주세요.", needs_clarification: "조건을 보완하면 후보를 확인합니다.",
  awaiting_confirmation: "조건을 확인한 제안입니다. 내용을 검토한 뒤 등록해주세요.",
  time_ready: "공통 시간 후보를 확인했습니다.", no_time: "선택한 범위에 공통 시간이 없습니다.",
  no_room: "조건을 충족하는 회의실이 없습니다.", needs_recheck: "일정 정보가 바뀌었거나 근거를 확인하지 못했습니다. 다시 조회해주세요.",
  lookup_unavailable: "일부 일정을 읽지 못했습니다. 지금은 확정할 수 없습니다.",
  stopped: "일정이 계속 변경되어 확인을 멈췄습니다.", cancelled: "제안을 취소했습니다. 일정은 등록하지 않았습니다.",
  saved: "확인한 일정을 등록했습니다.", rejected: "현재 제안을 등록하지 않았습니다.",
};

export default function MeetingReview({ session, catalog, capabilities, busy, comparison, history, onDecision, onRetry }) {
  const [feedback, setFeedback] = useState("");
  const [consent, setConsent] = useState(false);
  const pending = session?.pending, proposal = pending?.content || session?.event?.content;
  const request = session?.request;
  const valid = ["time_ready", "awaiting_confirmation", "saved"].includes(session?.status);
  const candidates = valid ? session.time_candidates || [] : [];
  const summary = session?.status === "needs_clarification" ? statusText.needs_clarification
    : session?.reply || (session?.status === "awaiting_confirmation" && !capabilities.registration
      ? "조건을 확인한 제안입니다. 시간과 회의실을 검토해주세요."
      : statusText[session?.status]) || "요청을 보내면 공통 시간과 제안을 확인할 수 있습니다.";
  const comparing = comparison?.before.request && comparison.after.request.revision === request?.revision && session?.status !== "needs_clarification" && Boolean(comparison.before.content || proposal);
  const currentAbsence = session?.status === "needs_recheck" ? "재조회 필요" : "현재 제안 없음";
  useEffect(() => { setConsent(false); setFeedback(""); }, [pending?.proposal_id]);

  return <section className="meeting-review">
    <div className="section-title"><h2>조회 결과</h2>{busy && <span role="status">요청 처리 중…</span>}</div>
    <div className="result-summary" role="status">{summary}</div>
    {!!candidates.length && <div className="review-section"><h3>{request.intent === "room_only" ? "지정한 시간" : "공통 시간 후보"}</h3><table className="data-table compact"><thead><tr><th>시간</th><th>확인 범위</th></tr></thead><tbody>{candidates.map((candidate) => <tr key={candidate.start}><td className="time-cell">{timeRange(candidate, request.timezone)}</td><td>{request.intent === "room_only" ? "지정한 시간" : "참석자 일정"}</td></tr>)}</tbody></table></div>}
    {proposal && valid && !comparing && <div className="review-section"><h3>{session.event ? "등록한 일정" : "검증한 제안"}</h3><dl className="proposal-details"><dt>날짜</dt><dd>{dateLabel(request.meeting_date)}</dd><dt>회의 시간</dt><dd><strong>{timeRange(proposal, request.timezone)}</strong></dd><dt>회의실</dt><dd>{proposal.room}</dd><dt>조건</dt><dd>{request.size}명 · {proposal.equipment} · 준비 {proposal.setup_minutes}분</dd></dl></div>}
    {comparing && <div className="review-section"><h3>제안 전후</h3><table className="data-table compact comparison-table"><thead><tr><th>항목</th><th>이전 제안</th><th>{session.event ? "등록한 제안" : "현재 제안"}</th></tr></thead><tbody>
      <tr><th scope="row">날짜</th><td>{comparison.before.request.meeting_date}</td><td>{request.meeting_date}</td></tr>
      <tr><th scope="row">회의 시간</th><td>{comparison.before.content ? timeRange(comparison.before.content, comparison.before.request.timezone) : "회의실 제안 없음"}</td><td>{proposal && valid ? timeRange(proposal, request.timezone) : currentAbsence}</td></tr>
      <tr><th scope="row">회의실</th><td>{comparison.before.content?.room || "회의실 제안 없음"}</td><td>{proposal && valid ? proposal.room : currentAbsence}</td></tr>
      <tr><th scope="row">장비·준비</th><td>{comparison.before.content ? `${comparison.before.content.equipment} · 준비 ${comparison.before.content.setup_minutes}분` : "해당 없음"}</td><td>{proposal && valid ? `${proposal.equipment} · 준비 ${proposal.setup_minutes}분` : currentAbsence}</td></tr>
    </tbody></table></div>}
    {pending && capabilities.registration && <div className="confirmation"><label><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} disabled={busy} />날짜·시간·회의실을 확인했습니다.</label><div className="button-row"><button className="button primary" disabled={busy || !consent} onClick={() => onDecision("confirm")}>일정 확정 등록</button><button className="button" disabled={busy} onClick={() => onDecision("cancel")}>제안 취소</button></div><p className="help-text">등록 직전에 현재 일정과 충돌 여부를 다시 확인합니다.</p></div>}
    {pending && capabilities.feedback && <section className="review-section explanation"><h3>선택 근거</h3>{!session.explanation ? <button className="button" disabled={busy} onClick={() => onDecision("explain")}>제안 이유 확인</button> : <><p>{session.explanation}</p>{session.previous_explanation && <details><summary>이전 설명과 비교</summary><p>{session.previous_explanation}</p></details>}{session.explanation_round < 2 ? <form onSubmit={(event) => { event.preventDefault(); if (feedback.trim()) { onDecision("explain", feedback); setFeedback(""); } }}><label>설명에 보완할 내용<textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={2} maxLength={600} placeholder="예: 준비 시간을 고려한 이유도 설명해주세요." /></label><button className="button" disabled={busy || !feedback.trim()}>설명 보완</button></form> : <p className="help-text">이전 설명과 현재 설명을 비교해 확인해주세요.</p>}</>}</section>}
    {session?.status === "needs_recheck" && <button className="button" disabled={busy} onClick={onRetry}>현재 조건으로 다시 조회</button>}
    {session && <ProcessingDetails trace={session.trace} catalog={catalog} />}
    {!!history.length && <details className="inquiry-history"><summary>이번 문의 내역</summary>{history.map((item, index) => <div key={index}><p>{item.text}</p><p>{item.reply}</p></div>)}</details>}
  </section>;
}
