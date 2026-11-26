"""현재 요청과 실제 원본을 대조하는 저장 경계의 독립 검사."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from .scheduling import normalized_records

def relevant_sources(request):
    keys = ([f"calendar:{person}" for person in request["participants"]]
            if request["intent"] != "room_only" else [])
    return keys + (["rooms"] if request["intent"] != "time_only" else [])


def normalized_source_records(records, request):
    """행 순서와 시각 표현을 맞춘 실제 내용이다. 관측 시각이나 임의 번호는 비교하지 않는다."""
    if not isinstance(records, list):
        raise TypeError("원본은 레코드 목록이어야 합니다.")
    return sorted(normalized_records(records, request),
                  key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def source_contents(snapshot, request):
    """현재 업무에 필요한 원본 내용과 조회 실패만 비교한다. 시각 차이만으로 갱신하지 않는다."""
    if not isinstance(snapshot, dict):
        raise TypeError("원천 제공자는 사전 형태의 원본을 반환해야 합니다.")
    calendars, errors = snapshot.get("calendars", {}), snapshot.get("errors", {})
    sources = {}
    for key in relevant_sources(request):
        present = key == "rooms" and "rooms" in snapshot or key.startswith("calendar:") and key.split(":", 1)[1] in calendars
        records = snapshot.get("rooms", []) if key == "rooms" else calendars.get(key.split(":", 1)[1], [])
        error = deepcopy(errors.get(key))
        if error is None and not present:
            error = {"type": "SourceUnavailable", "message": "요청한 원본을 읽지 못했습니다."}
        sources[key] = {"records": normalized_source_records(records, request), "error": error}
    return {"origin": snapshot.get("origin", "schedule-source-provider"), "sources": sources}


def proposal_issues(request, proposal, snapshot):
    """저장 경계의 독립 검사. 모델 응답이나 save 판단만으로 예약을 기록하지 않는다."""
    issues = []
    if any(source["error"] for source in source_contents(snapshot, request)["sources"].values()):
        return ["source_unavailable"]
    if not isinstance(proposal, dict):
        return ["missing_proposal"]
    try:
        start, end = datetime.fromisoformat(proposal["start"]), datetime.fromisoformat(proposal["end"])
        zone = ZoneInfo(request["timezone"])
        left = datetime.fromisoformat(f"{request['meeting_date']}T{request['window_start']}").replace(tzinfo=zone)
        right = datetime.fromisoformat(f"{request['meeting_date']}T{request['window_end']}").replace(tzinfo=zone)
        if not start.tzinfo or not end.tzinfo or start < left or end > right or end - start != timedelta(minutes=request["duration_minutes"]):
            issues.append("request_window")
        if request["intent"] != "room_only":
            for person in request["participants"]:
                records = snapshot["calendars"].get(person, [])
                if not any(datetime.fromisoformat(row["start"]) <= start and end <= datetime.fromisoformat(row["end"]) for row in records):
                    issues.append(f"calendar:{person}")
        if request["intent"] != "time_only":
            rooms = [row for row in snapshot["rooms"] if row["id"] == proposal.get("room_id")]
            room = rooms[0] if rooms else None
            if room is None:
                issues.append("room_identity")
            else:
                setup = room["setup"].get(request["equipment"])
                if setup is None or room["seats"] < request["size"]:
                    issues.append("room_conditions")
                elif not any(datetime.fromisoformat(row["start"]) <= start - timedelta(minutes=setup)
                             and end <= datetime.fromisoformat(row["end"]) for row in rooms):
                    issues.append("room_setup_interval")
                if proposal.get("room") != room["room"] or proposal.get("equipment") != request["equipment"] or proposal.get("setup_minutes") != setup:
                    issues.append("proposal_conditions")
    except (KeyError, TypeError, ValueError):
        issues.append("invalid_proposal")
    return issues
