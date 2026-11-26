import { useState } from "react";
import { dateLabel, timeRange } from "../formatSchedule.js";

export function addDays(value, amount) { const date = new Date(`${value}T12:00:00`); date.setDate(date.getDate() + amount); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }
function weekDates(day) { const weekday = new Date(`${day}T12:00:00`).getDay(); const first = addDays(day, -(weekday === 0 ? 6 : weekday - 1)); return Array.from({ length: 7 }, (_, index) => addDays(first, index)); }

export default function ScheduleAgenda({ date, setDate, events, catalog, busy, onNew, onRefresh }) {
  const [view, setView] = useState("day");
  const days = view === "day" ? [date] : weekDates(date);
  const name = (id) => catalog.participants.find((person) => person.id === id)?.name || "참석자 정보 없음";
  return <section className="agenda">
    <div className="agenda-toolbar"><div className="date-navigation"><button className="square-button" aria-label="이전 기간" onClick={() => setDate(addDays(date, view === "day" ? -1 : -7))}>‹</button><input aria-label="일정 날짜" type="date" value={date} onChange={(event) => setDate(event.target.value || date)} /><button className="square-button" aria-label="다음 기간" onClick={() => setDate(addDays(date, view === "day" ? 1 : 7))}>›</button></div><div className="segmented"><button className={view === "day" ? "active" : ""} onClick={() => setView("day")}>일간</button><button className={view === "week" ? "active" : ""} onClick={() => setView("week")}>주간</button></div><button className="button" onClick={onRefresh} disabled={busy}>새로고침</button><button className="button primary" onClick={onNew} disabled={busy}>새 회의 조율</button></div>
    {days.map((day) => {
      const rows = events.filter((event) => (event.meeting_date || event.content.start.slice(0, 10)) === day).sort((a, b) => a.content.start.localeCompare(b.content.start));
      return <section className="agenda-day" key={day}><div className="day-heading"><h2>{dateLabel(day)}</h2><span>{busy ? "확인 중" : `${rows.length}건`}</span></div><table className="data-table"><thead><tr><th>시간</th><th>회의실</th><th>참석자</th><th>장비</th></tr></thead><tbody>{rows.map((event) => <tr key={event.event_id}><td className="time-cell">{timeRange(event.content)}</td><td>{event.content.room}</td><td>{(event.participants || []).map(name).join(", ") || "회의실 예약"}</td><td>{event.content.equipment}</td></tr>)}</tbody></table>{!rows.length && <div className="empty-row">{busy ? "등록 일정을 확인하고 있습니다." : "등록된 일정이 없습니다."}</div>}</section>;
    })}
  </section>;
}
