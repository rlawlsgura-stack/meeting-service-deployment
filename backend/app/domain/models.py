"""업무 요청과 현재 사용자의 공통 약속."""

from datetime import date, time
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .preferences import default_preference


class Actor(BaseModel):
    owner_id: str
    team_id: str


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    revision: int = Field(ge=1, strict=True)
    meeting_date: str
    timezone: str = "Asia/Seoul"
    intent: str = "time_and_room"
    participants: list[str]
    duration_minutes: int = Field(gt=0, strict=True)
    window_start: str
    window_end: str
    size: int = Field(gt=0, strict=True)
    equipment: str = Field(min_length=1)
    preference: dict[str, bool] = Field(default_factory=default_preference)

    @field_validator("meeting_date")
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def valid_scope(self):
        ZoneInfo(self.timezone)
        if not self.request_id.strip():
            raise ValueError("요청 ID가 필요합니다.")
        if self.intent not in {"time_only", "room_only", "time_and_room"}:
            raise ValueError("조회 업무를 확인하세요.")
        if time.fromisoformat(self.window_start) >= time.fromisoformat(self.window_end):
            raise ValueError("조회 종료는 시작보다 늦어야 합니다.")
        if self.intent != "room_only" and not self.participants:
            raise ValueError("시간 조회에는 참석자가 필요합니다.")
        if set(self.preference) != {"prefer_early", "allow_later_for_less_setup"}:
            raise ValueError("선호 조건의 필드를 확인하세요.")
        return self


REQUEST_FIELDS = set(ScheduleRequest.model_fields) - {"request_id", "revision"}


def new_request(changes, request_id):
    """첫 요청의 기본값만 보충한다. 날짜·시간은 사용자 입력을 사용한다."""
    supplied = {key: value for key, value in changes.items() if key in REQUEST_FIELDS}
    intent = supplied.get("intent", "time_and_room")
    supplied.setdefault("intent", intent)
    supplied.setdefault("timezone", "Asia/Seoul")
    supplied["preference"] = {**default_preference(), **supplied.get("preference", {})}
    if intent == "room_only":
        supplied.setdefault("participants", [])
    if "size" not in supplied and supplied.get("participants"):
        supplied["size"] = len(supplied["participants"])
    if intent == "time_only":
        supplied.setdefault("equipment", "해당 없음")
        supplied.setdefault("size", max(1, len(supplied.get("participants", []))))
    return ScheduleRequest(request_id=request_id, revision=1, **supplied).model_dump()
