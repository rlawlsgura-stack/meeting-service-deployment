"""설정을 읽고 실제 DB·모델·인증을 연결해 API 서버를 시작한다."""

import logging
import os

from langchain_openai import ChatOpenAI
from fastapi.concurrency import run_in_threadpool
import uvicorn

from app.api.routes import application_capabilities
from app.auth import SupabaseAuth
from app.config import Settings, load_environment
from app.main import create_app
from app.agents.engine import AgentEngine
from app.repositories.store import ScheduleRepository


def main():
    load_environment()
    settings = Settings.from_environment()
    store = ScheduleRepository(settings.database_url)
    model = ChatOpenAI(model=settings.model, timeout=45, max_retries=1)
    auth = SupabaseAuth(settings.supabase_url, settings.supabase_publishable_key)

    # DB를 기다리는 동안 다른 사용자의 API 요청을 막지 않는다.
    async def source_provider(request):
        return await run_in_threadpool(store.snapshot_sources, request)

    async def participant_provider():
        return await run_in_threadpool(store.participant_catalog)

    capabilities = application_capabilities()
    engine = AgentEngine(model, source_provider, participant_provider=participant_provider,
                         rooms=capabilities["rooms"], parallel=capabilities["parallel"],
                         collaboration=capabilities["collaboration"])
    app = create_app(store, engine, auth, app_version=settings.app_version)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    uvicorn.run(app, host=os.getenv("SERVICE_HOST", "127.0.0.1"),
                port=int(os.getenv("SERVICE_PORT", "8000")), access_log=False)


if __name__ == "__main__":
    main()
