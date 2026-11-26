"""시간 담당이 사용하는 날짜·시각·공통 후보 계산. 회의실·MCP·조정 담당에 의존하지 않는다."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

def request_zone(request):
    """Windows 표본에서도 한국 시간은 표준 라이브러리만으로 표현한다."""
    return timezone(timedelta(hours=9)) if request["timezone"] == "Asia/Seoul" else ZoneInfo(request["timezone"])


def instant(value, request):
    """시각 표본을 요청 날짜의 aware datetime으로 정규화한다."""
    if len(value) == 5:
        return datetime.combine(date.fromisoformat(request["meeting_date"]), time.fromisoformat(value), request_zone(request))
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("원본 시각에 시간대가 필요합니다.")
    return parsed.astimezone(request_zone(request))


def time_candidates(request, receipts):
    """성공·빈 결과가 확인된 모든 참석자 원본에서만 공통 후보를 계산한다."""
    rows = [receipts.get(f"calendar:{person}") for person in request["participants"]]
    if any(row is None or row["status"] not in ("ok", "empty") for row in rows):
        return None
    step, duration = timedelta(minutes=30), timedelta(minutes=request["duration_minutes"])
    start, end = instant(request["window_start"], request), instant(request["window_end"], request)
    candidates = []
    while start + duration <= end:
        finish = start + duration
        if all(any(instant(r["start"], request) <= start and finish <= instant(r["end"], request)
                   for r in receipt["records"] if r["meeting_date"] == request["meeting_date"]) for receipt in rows):
            candidates.append({"start": start.isoformat(), "end": finish.isoformat()})
        start += step
    return candidates


def utc_now(now=None):
    """근거의 관측 시각을 UTC로 읽는다. 시각 비교는 시간대가 있는 값만 사용한다."""
    value = now() if callable(now) else now
    value = datetime.now(timezone.utc) if value is None else value
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("관측 시각은 시간대가 있어야 합니다.")
    return value.astimezone(timezone.utc)
