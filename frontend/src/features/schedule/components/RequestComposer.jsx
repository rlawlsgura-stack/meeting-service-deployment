import { useState } from "react";

export default function RequestComposer({ session, catalog, capabilities, busy, onQuery }) {
  const [message, setMessage] = useState("");
  const clarifying = session?.status === "needs_clarification";
  const correcting = Boolean(session?.request && capabilities.rooms);
  async function submit(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    const packet = await onQuery(text);
    if (packet) setMessage((current) => current.trim() === text ? "" : current);
  }
  return <form className="request-composer" onSubmit={submit}>
    <div className="section-title"><h2>{correcting ? "조건 수정 · 추가 요청" : "회의 요청"}</h2></div>
    {clarifying && <div className="clarification-question" role="status"><strong>조금 더 알려주세요.</strong><p>{session.reply}</p></div>}
    <label htmlFor="meeting-request">{clarifying ? "보완할 내용" : "원하는 회의를 문장으로 알려주세요."}</label>
    <textarea id="meeting-request" value={message} onChange={(event) => setMessage(event.target.value)} rows={5} maxLength={4000}
      placeholder={correcting ? "예: 종료 시각만 10시 30분으로 바꾸고 다른 조건은 유지해주세요." : "예: 내일 오전에 김민준과 이서연이 30분 만날 수 있는 시간을 찾아주세요."}
      aria-describedby="meeting-request-help" autoFocus disabled={busy} />
    <p className="help-text" id="meeting-request-help">{capabilities.rooms ? "날짜·참석자·시간 범위·회의 길이를 적어주세요. 회의실이 필요하면 인원과 장비도 함께 알려주세요." : "날짜·참석자·시간 범위·회의 길이를 적어주세요. 공통 시간 후보를 확인합니다."}</p>
    <button className="button primary" disabled={busy || !message.trim()} type="submit">{busy ? "확인 중…" : clarifying ? "조건 보완하기" : correcting ? "요청 반영하기" : "문의 보내기"}</button>
    {session?.request && !capabilities.rooms && <p className="help-text">같은 문의에서 날짜나 시간 범위를 바꾸고 나머지 조건은 유지해달라고 요청할 수 있습니다.</p>}
    {!session && <p className="catalog-note">조회 가능한 참석자: {(catalog.participants || []).map((person) => person.name).join(", ") || "등록된 참석자 없음"}</p>}
  </form>;
}
