"""PostgreSQL의 날짜별 가능 구간과 확정 예약을 대조한다. DB 구조나 예시 원본은 만들지 않는다."""

from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

from ..domain.validation import source_contents


class DomainConflict(Exception):
    """같은 참석자·회의실을 동시에 사용하거나 확인되지 않은 조건을 저장하려 한 경우다."""


def _rows(connection, execute, sql, parameters=()):
    return [dict(row) for row in execute(connection, sql, parameters).fetchall()]


def _required(request):
    sources = ([f"calendar:{person}" for person in request["participants"]]
               if request["intent"] != "room_only" else [])
    return sorted(sources + (["rooms"] if request["intent"] != "time_only" else []))


def lock_resources(connection, execute, request, *, write=False):
    """참석자 ID 정렬 다음 회의실 ID 정렬로 고정 행을 잠근다. 원본 관리도 같은 순서를 따른다."""
    suffix = " FOR UPDATE" if write else " FOR SHARE"
    people = sorted(set(request.get("participants", [])))
    if people:
        placeholders = ",".join("%s" for _ in people)
        rows = _rows(connection, execute,
            f"SELECT id FROM participants WHERE id IN ({placeholders}) ORDER BY id" + suffix, tuple(people))
        if len(rows) != len(people):
            raise DomainConflict("등록된 참석자의 가능 시간만 확인할 수 있습니다.")
    if request["intent"] != "time_only":
        _rows(connection, execute, "SELECT id FROM rooms ORDER BY id" + suffix)


def _instant(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("업무 원본 시각에는 시간대가 필요합니다.")
    return result


def _subtract(start, end, busy):
    """확정 점유 구간을 뺀 나머지만 반환한다. 닿기만 하는 두 구간은 충돌하지 않는다."""
    segments = [(_instant(start), _instant(end))]
    for busy_start, busy_end in busy:
        left, right = _instant(busy_start), _instant(busy_end)
        next_segments = []
        for begin, finish in segments:
            if finish <= left or right <= begin:
                next_segments.append((begin, finish))
                continue
            if begin < left:
                next_segments.append((begin, left))
            if right < finish:
                next_segments.append((right, finish))
        segments = next_segments
    return [(left.isoformat(), right.isoformat()) for left, right in segments if left < right]


def snapshot_domain(connection, execute, request):
    """요청 날짜에 등록된 가능 구간에서 실제 예약을 뺀다. 다른 날짜 자료를 옮겨 쓰지 않는다."""
    lock_resources(connection, execute, request)
    day = request["meeting_date"]
    calendars, rooms = {}, []
    if request["intent"] != "room_only":
        for person in request["participants"]:
            windows = _rows(connection, execute,
                "SELECT * FROM calendar_windows WHERE participant_id=%s AND meeting_date=%s ORDER BY start_at,id", (person, day))
            busy = _rows(connection, execute,
                "SELECT r.start_at,r.end_at FROM reservations r JOIN reservation_attendees a ON a.proposal_id=r.proposal_id WHERE a.participant_id=%s AND r.meeting_date=%s",
                (person, day))
            records = []
            for window in windows:
                for start, end in _subtract(window["start_at"], window["end_at"], [(row["start_at"], row["end_at"]) for row in busy]):
                    records.append({"id": window["id"], "attendee": person, "meeting_date": day, "start": start, "end": end})
            calendars[person] = records
    if request["intent"] != "time_only":
        windows = _rows(connection, execute,
            "SELECT w.*,r.name,r.seats FROM room_windows w JOIN rooms r ON r.id=w.room_id WHERE w.meeting_date=%s ORDER BY w.room_id,w.start_at,w.id", (day,))
        for window in windows:
            setups = _rows(connection, execute, "SELECT equipment,setup_minutes FROM room_equipment WHERE room_id=%s", (window["room_id"],))
            busy = _rows(connection, execute, "SELECT room_busy_start,end_at FROM reservations WHERE room_id=%s AND meeting_date=%s",
                         (window["room_id"], day))
            for start, end in _subtract(window["start_at"], window["end_at"], [(row["room_busy_start"], row["end_at"]) for row in busy]):
                rooms.append({"id": window["room_id"], "room": window["name"], "seats": window["seats"],
                    "setup": {row["equipment"]: row["setup_minutes"] for row in setups},
                    "meeting_date": day, "start": start, "end": end})
    origin = execute(connection, "SELECT payload FROM schedule_meta WHERE id=%s", ("origin",)).fetchone()
    if origin is None:
        raise DomainConflict("DB 원본 식별자가 없습니다. schema.sql과 seed.sql 준비를 확인하세요.")
    return {"calendars": calendars, "rooms": rooms, "origin": origin["payload"],
            "observed_at": datetime.now(timezone.utc).isoformat()}



def reserve_domain(connection, execute, request, pending):
    """기존 트랜잭션 안에서 충돌·실제 가용성을 재검사하고 예약 한 행과 관계를 저장한다."""
    if request["intent"] == "time_only":
        raise DomainConflict("시간 후보만 조회한 요청은 회의실 예약으로 저장하지 않습니다.")
    if not isinstance(pending.get("source_contents"), dict):
        raise DomainConflict("이전 형식의 제안입니다. 현재 조건으로 다시 조회하세요.")
    lock_resources(connection, execute, request, write=True)
    if len(set(request["participants"])) != len(request["participants"]):
        raise DomainConflict("서로 다른 등록 참석자만 예약에 연결할 수 있습니다.")
    proposal = pending["content"]
    start, end = _instant(proposal["start"]), _instant(proposal["end"])
    day = request["meeting_date"]
    room_id = proposal["room_id"]
    setup = execute(connection, "SELECT setup_minutes FROM room_equipment WHERE room_id=%s AND equipment=%s",
                    (room_id, request["equipment"])).fetchone()
    room = execute(connection, "SELECT name,seats FROM rooms WHERE id=%s", (room_id,)).fetchone()
    if setup is None or room is None or room["seats"] < request["size"]:
        raise DomainConflict("등록된 회의실의 인원·장비 조건과 맞지 않습니다.")
    minutes = setup["setup_minutes"]
    busy_start = start - timedelta(minutes=minutes)
    zone = timezone(timedelta(hours=9)) if request["timezone"] == "Asia/Seoul" else ZoneInfo(request["timezone"])
    window_start = datetime.fromisoformat(f"{day}T{request['window_start']}").replace(tzinfo=zone)
    window_end = datetime.fromisoformat(f"{day}T{request['window_end']}").replace(tzinfo=zone)
    if (start.date().isoformat() != day or end.date().isoformat() != day or end <= start
            or end - start != timedelta(minutes=request["duration_minutes"])
            or start < window_start or end > window_end
            or proposal.get("setup_minutes") != minutes or proposal.get("room") != room["name"]
            or proposal.get("equipment") != request["equipment"]):
        raise DomainConflict("현재 요청과 회의 제안의 날짜·시간·장비가 맞지 않습니다.")
    # 방의 준비 구간도 점유한다. 참석자는 회의 본 시간만 점유한다.
    room_busy = _rows(connection, execute, "SELECT room_busy_start,end_at FROM reservations WHERE room_id=%s AND meeting_date=%s", (room_id, day))
    if any(busy_start < _instant(row["end_at"]) and _instant(row["room_busy_start"]) < end for row in room_busy):
        raise DomainConflict("회의실이 같은 시간에 이미 예약되어 있습니다.")
    for person in request["participants"]:
        busy = _rows(connection, execute,
            "SELECT r.start_at,r.end_at FROM reservations r JOIN reservation_attendees a ON a.proposal_id=r.proposal_id WHERE a.participant_id=%s AND r.meeting_date=%s",
            (person, day))
        if any(start < _instant(row["end_at"]) and _instant(row["start_at"]) < end for row in busy):
            raise DomainConflict(f"{person} 참석자가 같은 시간의 다른 회의에 등록되어 있습니다.")
    snapshot = snapshot_domain(connection, execute, request)
    if source_contents(snapshot, request) != pending["source_contents"]:
        raise DomainConflict("확정하는 동안 원본이 바뀌었습니다. 현재 조건으로 다시 조회하세요.")
    if not any(row["id"] == room_id and _instant(row["start"]) <= busy_start and end <= _instant(row["end"])
               for row in snapshot["rooms"]):
        raise DomainConflict("준비 시간을 포함한 회의실의 실제 가능 구간을 벗어났습니다.")
    if request["intent"] != "room_only" and any(
        not any(_instant(row["start"]) <= start and end <= _instant(row["end"]) for row in snapshot["calendars"].get(person, []))
        for person in request["participants"]):
        raise DomainConflict("현재 참석자 가능 구간과 맞지 않습니다.")
    event = pending["event"]
    if (event.get("proposal_id") != pending["proposal_id"] or event.get("request_id") != request["request_id"]
            or event.get("revision") != request["revision"] or pending.get("revision") != request["revision"]
            or event.get("content") != proposal):
        raise DomainConflict("저장할 예약과 확인한 제안의 요청·내용이 다릅니다.")
    execute(connection, "INSERT INTO reservations (proposal_id,event_id,session_id,owner_id,team_id,request_id,revision,meeting_date,timezone,room_id,start_at,end_at,room_busy_start,equipment,setup_minutes,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (pending["proposal_id"], event["event_id"], event["session_id"], pending["owner_id"], pending["team_id"],
         request["request_id"], request["revision"], day, request["timezone"], room_id, start.isoformat(), end.isoformat(),
         busy_start.isoformat(), request["equipment"], minutes, json.dumps(event, ensure_ascii=False)))
    for person in request["participants"]:
        execute(connection, "INSERT INTO reservation_attendees (proposal_id,participant_id) VALUES (%s,%s)", (pending["proposal_id"], person))
    return event
