"""현재 일정 조건의 범위와 회의실·시간 조합을 계산한다."""

from copy import deepcopy
from datetime import date, timedelta
from .time_rules import instant, request_zone, time_candidates


def validate_common_request(request):
    """문의 식별·일시·길이·공간 조건의 제공 검사. 대화나 담당 선택은 다루지 않는다."""
    value = deepcopy(request)
    if not isinstance(value.get("request_id"), str) or not value["request_id"].strip():
        raise ValueError("request_id가 필요합니다.")
    if type(value.get("revision")) is not int or value["revision"] < 1:
        raise ValueError("revision은 1 이상의 정수입니다.")
    date.fromisoformat(value["meeting_date"])
    if type(value["duration_minutes"]) is not int or value["duration_minutes"] <= 0:
        raise ValueError("회의 길이는 양의 정수입니다.")
    if type(value["size"]) is not int or value["size"] <= 0 or not value["equipment"]:
        raise ValueError("양의 정원과 장비 조건이 필요합니다.")
    left, right = instant(value["window_start"], value), instant(value["window_end"], value)
    if left >= right or left.date().isoformat() != value["meeting_date"] or right.date().isoformat() != value["meeting_date"]:
        raise ValueError("문의 시간 범위가 잘못되었습니다.")
    if any(type(value["preference"].get(key)) is not bool for key in ("prefer_early", "allow_later_for_less_setup")):
        raise ValueError("선호는 불리언 두 값으로 지정합니다.")
    return value


def validate_request(request):
    """앞서 배운 Router가 분류한 intent와 구조화된 조건을 받는다. 자연어를 다시 분류하지 않는다."""
    value = validate_common_request(request)
    value.setdefault("intent", "time_and_room")  # 기존 일정 서비스가 보내던 요청과 호환한다.
    if value["intent"] not in ("time_only", "time_and_room", "room_only"):
        raise ValueError("의도는 time_only/time_and_room/room_only 중 하나입니다.")
    people = value["participants"]
    if not isinstance(people, list) or any(not isinstance(p, str) or not p for p in people) or len(set(people)) != len(people):
        raise ValueError("서로 다른 참석자가 필요합니다.")
    if value["intent"] != "room_only" and not people:
        raise ValueError("공통 시간 조회에는 참석자가 필요합니다.")
    if value["size"] < len(people):
        raise ValueError("정원은 참석 인원 이상이어야 합니다.")
    if value["intent"] == "room_only":
        left, right = instant(value["window_start"], value), instant(value["window_end"], value)
        if right - left != timedelta(minutes=value["duration_minutes"]):
            raise ValueError("방만 찾을 때는 사용자가 지정한 시작·종료와 회의 길이가 일치해야 합니다.")
    return value


def route_request(request):
    """분류 결과로 필요한 담당을 고르는 제공 Router 경계다."""
    intent = request["intent"]
    return {"intent": intent, "time_basis": "user" if intent == "room_only" else "calendar",
            "reason": "사용자 지정 시각으로 방만 확인" if intent == "room_only" else
                      "공통 시간 결과로 종료" if intent == "time_only" else "시간·회의실 담당 조사 후 결과 통합"}


def user_time_candidates(request):
    """캘린더를 읽지 않고 사용자가 지정한 정확한 시각을 후보로 투영한다."""
    return [{"start": instant(request["window_start"], request).isoformat(),
             "end": instant(request["window_end"], request).isoformat()}]


ROOM_REQUEST_FIELDS = ("request_id", "revision", "meeting_date", "timezone", "duration_minutes",
                       "window_start", "window_end", "size", "equipment", "preference", "time_basis")


def room_request_for(request):
    """회의실 담당·서버에 필요한 값만 보낸다. 참석자·전체 대화·캘린더 원문은 제외한다."""
    packet = {key: deepcopy(request[key]) for key in ROOM_REQUEST_FIELDS if key != "time_basis"}
    packet["time_basis"] = "user" if request["intent"] == "room_only" else "calendar"
    return validate_room_request(packet)


def validate_room_request(packet):
    """MCP 서버의 전달 계약. 앱의 전체 request를 그대로 보내면 거절한다."""
    if set(packet) != set(ROOM_REQUEST_FIELDS):
        raise ValueError("방 조회용 전달 필드만 허용합니다.")
    value = validate_common_request(packet)
    if value["time_basis"] not in ("user", "calendar"):
        raise ValueError("시각의 근거는 user 또는 calendar입니다.")
    return value


def normalized_records(records, request):
    values = deepcopy(records)
    for row in values:
        row["meeting_date"] = row.get("meeting_date", request["meeting_date"])
        row["start"], row["end"] = instant(row["start"], request).isoformat(), instant(row["end"], request).isoformat()
    return values


def query_scope(source_id, request):
    """원천별 조회 범위. 회차가 달라도 이 범위가 맞고 최신이면 재사용 가능하다."""
    scope = {key: deepcopy(request[key]) for key in ("meeting_date", "timezone", "window_start", "window_end")}
    if source_id.startswith("calendar:"):
        scope["attendee"] = source_id.split(":", 1)[1]
    else:
        scope.update(size=request["size"], equipment=request["equipment"])
    return scope


def choose_room(request, candidates, records):
    """앱이 두 담당 결과로 만드는 제안. 별도 검증 함수는 이 함수를 다시 부르지 않는다."""
    options = []
    for slot in candidates:
        start, end = instant(slot["start"], request), instant(slot["end"], request)
        for room in records:
            setup = room["setup"].get(request["equipment"])
            if room["meeting_date"] != request["meeting_date"] or room["seats"] < request["size"] or setup is None:
                continue
            if instant(room["start"], request) <= start - timedelta(minutes=setup) and end <= instant(room["end"], request):
                options.append({**slot, "room": room["room"], "room_id": room["id"],
                                "equipment": request["equipment"], "setup_minutes": setup})
    if not options:
        return None
    direction = 1 if request["preference"]["prefer_early"] else -1
    def time_rank(row):
        return direction * instant(row["start"], request).timestamp()
    if request["preference"]["allow_later_for_less_setup"]:
        return min(options, key=lambda row: (row["setup_minutes"], time_rank(row)))
    return min(options, key=lambda row: (time_rank(row), row["setup_minutes"]))
