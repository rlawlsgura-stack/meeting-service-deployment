"""조회 기록과 제안을 원본에 대조하는 제공 검사 조건."""

from datetime import datetime, timedelta

from .scheduling import instant, query_scope
from .time_rules import utc_now
from .validation import normalized_source_records

MAX_AGE_SECONDS = 300


def receipt_facts(receipt, request, manifest, now=None):
    """타입·시각·범위 검사는 제공한다. 이전 조회의 원본 내용이 현재 원본과 같은지 대조한다."""
    source_id = receipt.get("source_id")
    known_source = isinstance(source_id, str) and source_id in manifest["sources"]
    try:
        observed = datetime.fromisoformat(receipt["observed_at"])
        aware = observed.tzinfo is not None and observed.utcoffset() is not None
        age = (utc_now(now) - observed).total_seconds() if aware else -1
        fresh = aware and 0 <= age <= MAX_AGE_SECONDS
    except (KeyError, TypeError, ValueError):
        fresh = False
    records = receipt.get("records")
    shape = isinstance(records, list)
    try:
        for row in records if shape else []:
            shape = shape and isinstance(row, dict) and row["meeting_date"] == request["meeting_date"]
            left, right = instant(row["start"], request), instant(row["end"], request)
            shape = shape and left < right and left.date().isoformat() == request["meeting_date"] and right.date().isoformat() == request["meeting_date"]
            if str(source_id).startswith("calendar:"):
                shape = shape and row["attendee"] == source_id.split(":", 1)[1]
            else:
                shape = shape and bool(row["id"]) and bool(row["room"]) and type(row["seats"]) is int and row["seats"] > 0
                shape = shape and isinstance(row["setup"], dict) and all(type(v) is int and v >= 0 for v in row["setup"].values())
    except (KeyError, TypeError, ValueError):
        shape = False
    status = receipt.get("status")
    return {
        "request_context": receipt.get("request_id") == request["request_id"] and type(receipt.get("revision")) is int
                           and receipt.get("revision") == request["revision"],
        "collection_cycle": type(receipt.get("collection_cycle")) is int and receipt["collection_cycle"] >= 0,
        "origin_scope": known_source and receipt.get("origin") == manifest["origin"]
                        and receipt.get("scope") == query_scope(str(source_id), request)
                        and receipt.get("meeting_date") == request["meeting_date"] and receipt.get("timezone") == request["timezone"],
        "source_contents": known_source and shape and isinstance(records, list)
                           and normalized_source_records(records, request) == manifest["sources"][source_id]["records"]
                           and manifest["sources"][source_id].get("error") is None,
        "observed_at": fresh,
        "source_shape": shape and ((status == "ok" and bool(records)) or (status == "empty" and records == []) or status == "error"),
        "lookup_error": status in ("ok", "empty"),
    }


def proposal_facts(proposal, request, receipts):
    """선택 함수를 재호출하지 않고 캘린더·회의실 원본의 실제 제약을 직접 대조한다."""
    intent = request.get("intent", "time_and_room")
    names = ["duration_window"] + ([] if intent == "room_only" else ["participants_available"])
    if intent != "time_only":
        names += ["room_identity", "capacity_equipment", "room_interval_setup"]
    facts = dict.fromkeys(names, False)  # 요청한 업무에 적용되는 조건만 검사한다.
    try:
        start, end = instant(proposal["start"], request), instant(proposal["end"], request)
        facts["duration_window"] = (end - start == timedelta(minutes=request["duration_minutes"])
            and instant(request["window_start"], request) <= start < end <= instant(request["window_end"], request))
        if intent != "room_only":
            facts["participants_available"] = all(
                any(row["attendee"] == person and row["meeting_date"] == request["meeting_date"]
                    and instant(row["start"], request) <= start and end <= instant(row["end"], request)
                    for row in receipts[f"calendar:{person}"]["records"])
                for person in request["participants"])
        if intent == "time_only":
            return facts
        rooms = [row for row in receipts["rooms"]["records"] if row["id"] == proposal["room_id"]]
        # 하나의 실제 방에도 예약을 뺀 가능 구간이 여러 줄일 수 있다.
        facts["room_identity"] = bool(rooms) and all(room["room"] == proposal["room"] for room in rooms)
        checks = []
        for room in rooms:
            setup = room["setup"].get(request["equipment"])
            capacity = (room["seats"] >= request["size"] and setup is not None
                and proposal["equipment"] == request["equipment"] and proposal["setup_minutes"] == setup)
            interval = (room["meeting_date"] == request["meeting_date"] and setup is not None
                and instant(room["start"], request) <= start - timedelta(minutes=setup)
                and end <= instant(room["end"], request))
            checks.append((capacity, interval))
        facts["capacity_equipment"] = any(capacity for capacity, _ in checks)
        facts["room_interval_setup"] = any(capacity and interval for capacity, interval in checks)
    except (KeyError, TypeError, ValueError):
        pass
    return facts
