const stages = { router: "요청 분류", handoff: "담당 인계", supervision: "진행 조정", workers: "담당 조회", worker: "담당 조회", mcp: "회의실 도구 연결", verification: "결과 검증" };
const roles = { intake: "접수 담당", supervisor: "조정 담당", time: "시간 담당", room: "회의실 담당", policy: "검증 정책" };
const statuses = { start: "시작", end: "완료", error: "실패", accepted: "인계 완료", delegated: "조사 위임", completed: "완료", proposal: "제안 정리", no_result: "후보 없음", needs_clarification: "조건 보완 필요", needs_recheck: "재확인 필요", accept: "채택", refresh: "바뀐 근거 다시 확인", stop: "갱신 중단", time_ready: "공통 시간 확인", no_time: "공통 시간 없음", no_room: "회의실 없음", lookup_unavailable: "조회 불가", verified: "검증 완료" };
const tools = { transfer_to_supervisor: "조정 담당으로 인계", investigate_schedule: "담당 조사 요청", finish_coordination: "결과 정리", request_clarification: "조건 보완 요청", find_times: "참석자 일정 조회", find_rooms: "회의실 조회" };

export function executionSummaries(trace = []) {
  const cycles = new Map();
  for (const row of trace) {
    if (!["worker", "workers"].includes(row.stage) || !["time", "room"].includes(row.role) ||
        !["start", "end"].includes(row.status) || !Number.isInteger(row.cycle) || row.cycle < 0 ||
        typeof row.at_ms !== "number" || !Number.isFinite(row.at_ms) || row.at_ms < 0) continue;
    const events = cycles.get(row.cycle) || [];
    events.push(row); cycles.set(row.cycle, events);
  }
  const summaries = [];
  for (const [cycle, events] of cycles) {
    const event = (role, status) => events.filter((row) => row.role === role && row.status === status);
    const pairs = [event("time", "start"), event("time", "end"), event("room", "start"), event("room", "end")];
    if (pairs.some((rows) => rows.length !== 1)) continue;
    const [timeStart, timeEnd, roomStart, roomEnd] = pairs.map((rows) => rows[0].at_ms);
    if (timeEnd < timeStart || roomEnd < roomStart) continue;
    let text;
    if (Math.max(timeStart, roomStart) < Math.min(timeEnd, roomEnd)) text = "시간·회의실 담당의 조회 구간이 겹쳤습니다.";
    else if (timeStart < roomStart && timeEnd <= roomStart) text = "시간 담당 조회 뒤 회의실 담당 조회가 진행됐습니다.";
    else if (roomStart < timeStart && roomEnd <= timeStart) text = "회의실 담당 조회 뒤 시간 담당 조회가 진행됐습니다.";
    if (text) summaries.push({ cycle, text });
  }
  return summaries;
}

export default function ProcessingDetails({ trace, catalog }) {
  const people = new Map((catalog.participants || []).map((person) => [person.id, person.name]));
  function sourceName(source) {
    if (source === "rooms") return "회의실 목록";
    if (typeof source === "string" && source.startsWith("calendar:")) return `${people.get(source.slice(9)) || "참석자"} 일정`;
    return "조회 원본";
  }
  return <details className="processing-details"><summary>처리 내역</summary>
    {!trace?.length ? <p className="help-text">이 문의의 처리 기록이 아직 없습니다.</p> : <>
      {trace.some((row) => typeof row.at_ms === "number" && Number.isFinite(row.at_ms)) && <p className="help-text">시각은 각 조회 회차가 시작된 뒤의 경과 시간입니다.</p>}
      {executionSummaries(trace).map((row) => <p className="help-text" key={row.cycle}>조회 {row.cycle + 1}회차: {row.text}</p>)}
      <ol>{trace.map((row, index) => <li key={index}><div><strong>{stages[String(row.stage).toLowerCase()] || "진행 확인"}{roles[row.role] ? ` · ${roles[row.role]}` : ""}</strong><span>{tools[row.tool] || "처리"} · {statuses[row.status] || "상태 확인"}</span></div>
        <small>{[Number.isInteger(row.cycle) && `조회 ${row.cycle + 1}회차`, typeof row.at_ms === "number" && Number.isFinite(row.at_ms) && `${row.at_ms.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}ms`, row.sources?.length && row.sources.map(sourceName).join(", "), row.retained_sources?.length && `유지: ${row.retained_sources.map(sourceName).join(", ")}`].filter(Boolean).join(" · ")}</small>
      </li>)}</ol>
    </>}
  </details>;
}
