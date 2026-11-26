"""HTTP 요청을 인증·업무 처리·저장소에 연결한다."""

from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool

from .auth import AuthError, bearer_token
from .workspace import WORKSPACE_ID
from .domain.models import Actor
from .api.routes import application_capabilities, build_router
from .api.auth_routes import auth_router
from .repositories.store import ConflictError, OwnershipError
from .services.scheduling import ScheduleService


logger = logging.getLogger("schedule.api")


def create_app(store, engine, auth, *, app_version="development"):
    """준비된 DB·에이전트·인증 연결로 API를 구성한다. 연결 생성은 serve.py에서 읽는다."""
    capabilities = application_capabilities()
    service = ScheduleService(store, engine, capabilities=capabilities)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await run_in_threadpool(store.open)
            yield
        finally:
            try:
                await auth.aclose()
            finally:
                await run_in_threadpool(store.close)

    app = FastAPI(title="일정 조정 서비스", version="1.0.0", lifespan=lifespan)
    app.state.store, app.state.engine, app.state.service = store, engine, service
    app.state.app_version, app.state.auth = app_version, auth

    async def account(request: Request):
        if not hasattr(request.state, "account"):
            token = bearer_token(request.headers.get("authorization"))
            request.state.account = await auth.verify(token)
        return request.state.account

    async def actor(user: dict = Depends(account)):
        member = await run_in_threadpool(store.get_membership, user["id"])
        if member is None:
            raise OwnershipError("팀 관리자에게 멤버 등록을 요청해주세요.")
        return Actor(owner_id=user["id"], team_id=WORKSPACE_ID)

    @app.middleware("http")
    async def request_id(request, call_next):
        correlation_id = str(uuid4())
        request.state.request_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            # 공급자 오류 원문이나 사용자 입력을 로그에 그대로 남기지 않는다.
            logger.warning("request_id=%s stage=service status=needs_recheck version=%s", correlation_id, app.state.app_version)
            response = JSONResponse(status_code=503, content={"status": "needs_recheck",
                "detail": "일시적으로 확인을 마치지 못했습니다. 잠시 뒤 다시 시도해주세요.", "request_id": correlation_id})
        response.headers["X-Request-ID"] = correlation_id
        if not request.url.path.startswith("/static") and request.url.path != "/":
            logger.info("request_id=%s stage=http status=%s version=%s", correlation_id, response.status_code, app.state.app_version)
        return response

    @app.exception_handler(AuthError)
    async def authentication_error(request, exc):
        headers = {"Cache-Control": "no-store"}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(status_code=exc.status_code, content={"status": "unauthorized" if exc.status_code == 401 else "auth_error",
            "code": exc.code, "detail": exc.detail, "request_id": request.state.request_id}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # 기본 검증 응답의 input에 비밀번호·refresh token을 포함하지 않는다.
        return JSONResponse(status_code=422, content={"status": "invalid_input", "code": "INVALID_INPUT",
            "detail": "입력 형식을 확인해주세요.", "request_id": request.state.request_id}, headers={"Cache-Control": "no-store"})

    @app.exception_handler(OwnershipError)
    async def ownership_error(request, exc):
        return JSONResponse(status_code=403, content={"status": "forbidden", "detail": str(exc), "request_id": request.state.request_id})

    @app.exception_handler(ConflictError)
    async def conflict_error(request, exc):
        return JSONResponse(status_code=409, content={"status": "conflict", "detail": str(exc), "request_id": request.state.request_id})

    @app.exception_handler(KeyError)
    async def missing_error(request, exc):
        return JSONResponse(status_code=404, content={"status": "not_found", "detail": "세션을 찾을 수 없습니다.", "request_id": request.state.request_id})

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        # 잘못된 입력값을 응답에 그대로 돌려주지 않는다.
        return JSONResponse(status_code=422, content={"status": "invalid_input", "detail": "일정 조건이나 반환 형식을 확인하세요.", "request_id": request.state.request_id})

    @app.exception_handler(RuntimeError)
    async def execution_error(request, exc):
        logger.warning("request_id=%s stage=execute status=needs_recheck version=%s", request.state.request_id, app.state.app_version)
        return JSONResponse(status_code=503, content={"status": "needs_recheck", "detail": "조회나 검증을 완료하지 못했습니다. 같은 요청을 다시 확인하세요.", "request_id": request.state.request_id})

    app.include_router(auth_router(account))
    app.include_router(build_router(service, store, actor, account, capabilities=capabilities))
    return app
