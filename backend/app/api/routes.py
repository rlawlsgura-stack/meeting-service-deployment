"""공개 API와 실제 조립할 기능을 한곳에서 정한다. 요청이 실행 모드를 고르지 않는다."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from ..domain.models import Actor
from .account_routes import account_router
from .schemas import DecisionInput, MessageInput

# API와 화면에서 제공하는 기능을 같은 설정으로 구성한다.
CAPABILITIES = {'time': True, 'rooms': True, 'parallel': True, 'collaboration': True, 'registration': True, 'feedback': True}


def application_capabilities():
    """한 레지스트리로 앱 조립과 API 노출이 같은 기능을 가리키게 한다."""
    value = dict(CAPABILITIES)
    if set(value) != {"time", "rooms", "parallel", "collaboration", "registration", "feedback"} or any(type(item) is not bool for item in value.values()):
        raise ValueError("기능 연결 항목은 여섯 불리언입니다.")
    if not value["time"] or (value["parallel"] and not value["rooms"]) or (value["registration"] and not value["rooms"]) or (value["feedback"] and not value["registration"]):
        raise ValueError("병렬 조회와 등록에는 회의실 조회가, 설명에는 등록 연결이 필요합니다.")
    return value


def build_router(service, store, actor, account, *, capabilities=None):
    capabilities = application_capabilities() if capabilities is None else capabilities
    router = APIRouter(prefix="/api")
    router.include_router(account_router(store, account, actor, capabilities))

    @router.get("/health")
    def health():
        try:
            return {"status": store.health()}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})

    @router.get("/version")
    async def version(request: Request):
        return {"app_version": request.app.state.app_version}

    @router.post("/sessions", status_code=201)
    def sessions(owner: Actor = Depends(actor)):
        return service.public(store.create_session(owner))

    @router.get("/sessions/{session_id}")
    def session(session_id: str, owner: Actor = Depends(actor)):
        return service.public(store.get_session(session_id, owner))

    @router.post("/sessions/{session_id}/messages")
    async def message(session_id: str, body: MessageInput, owner: Actor = Depends(actor)):
        return await service.message(session_id, owner, body.message)

    if capabilities["registration"]:
        @router.get("/events")
        async def events(owner: Actor = Depends(actor)):
            return {"events": await service.list_events(owner)}

        @router.post("/sessions/{session_id}/decision")
        async def decision(session_id: str, body: DecisionInput, owner: Actor = Depends(actor)):
            allowed = {"confirm", "cancel", "modify"} | ({"explain"} if capabilities["feedback"] else set())
            if body.action not in allowed:
                raise ValueError("현재 API가 다루는 결정이 아닙니다.")
            return await service.decision(session_id, owner, body)

    return router
