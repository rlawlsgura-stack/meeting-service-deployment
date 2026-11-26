export function dateLabel(value) {
  if (!value) return "날짜 확인 중";
  return new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric", weekday: "short" })
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}

export function timeLabel(value, timezone = "Asia/Seoul") {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: timezone, hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

export function timeRange(proposal, timezone) {
  return `${timeLabel(proposal.start, timezone)} – ${timeLabel(proposal.end, timezone)}`;
}

export function conditionRows(source, catalog) {
  const people = new Map((catalog.participants || []).map((person) => [person.id, person.name]));
  const names = source.participants?.map((id) => people.get(id) || "등록 정보 확인 필요").join(", ");
  const intent = { time_only: "공통 시간", room_only: "정해진 시간의 회의실", time_and_room: "공통 시간과 회의실" }[source.intent];
  const rows = [
    { key: "intent", label: "조회 항목", value: intent || "확인 필요" },
    { key: "meeting_date", label: "날짜", value: source.meeting_date || "확인 필요" },
    { key: "participants", label: "참석자", value: names || (source.intent === "room_only" ? "참석자 일정 조회 안 함" : "확인 필요") },
    { key: "window", label: "시간 범위", value: source.window_start || source.window_end ? `${source.window_start || "시작 확인 필요"}–${source.window_end || "종료 확인 필요"}` : "확인 필요" },
    { key: "duration_minutes", label: "회의 길이", value: source.duration_minutes ? `${source.duration_minutes}분` : "확인 필요" },
  ];
  if (source.intent !== "time_only") {
    const preference = source.preference || {};
    const time = typeof preference.prefer_early === "boolean" ? preference.prefer_early ? "이른 시간" : "늦은 시간" : null;
    let priority = "조건 확인 후 적용";
    if (preference.allow_later_for_less_setup === true) priority = time ? `준비 시간 우선 · 같으면 ${time}` : "준비 시간 우선 · 시간 순서 확인 중";
    else if (preference.allow_later_for_less_setup === false) priority = time ? `${time} 우선 · 같으면 준비 시간` : "준비를 줄이려는 늦은 시작은 허용하지 않음";
    else if (time) priority = `${time} 선호 · 준비 기준 확인 중`;
    rows.push({ key: "size", label: "필요 인원", value: source.size ? `${source.size}명` : "확인 필요" },
      { key: "equipment", label: "장비", value: source.equipment || "확인 필요" },
      { key: "preference", label: "추천 기준", value: priority });
  }
  return rows;
}
