"""HTTP 요청 본문. 모델 지시나 DB 쓰기 코드는 포함하지 않는다."""

from pydantic import BaseModel, ConfigDict, Field

class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    proposal_id: str | None = None
    revision: int | None = None
    content: dict | None = None
    changes: dict | None = None
    message: str | None = Field(default=None, max_length=4000)


class CredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=4096)


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1, max_length=16000)


class PublicUser(BaseModel):
    id: str
    email: str | None
    display_name: str | None


class TokensResponse(BaseModel):
    user_id: str
    user: PublicUser
    access_token: str
    refresh_token: str
    expires_in: int


class SignupResponse(BaseModel):
    user_id: str
    email_confirmation_required: bool


class UserResponse(BaseModel):
    user: PublicUser
