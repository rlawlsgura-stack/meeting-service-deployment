"""프로젝트 설정 예시와 실제 실행 환경을 분리한다."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


def load_environment():
    """로컬 실행은 프로젝트 루트 .env를 읽고 주입된 환경변수는 유지한다."""
    project_root = Path(__file__).resolve().parents[2]
    return load_dotenv(project_root / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_version: str
    model: str
    supabase_url: str
    supabase_publishable_key: str

    @classmethod
    def from_environment(cls):
        required = ("DATABASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
        missing = [key for key in required if not os.getenv(key, "").strip()]
        if missing:
            raise ValueError("실행 환경에서 다음 설정을 확인하세요: " + ", ".join(missing))
        return cls(os.environ["DATABASE_URL"], os.getenv("APP_VERSION", "development"),
                   os.environ["OPENAI_MODEL"], os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"])
