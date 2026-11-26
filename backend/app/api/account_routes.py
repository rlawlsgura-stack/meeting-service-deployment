"""계정과 참조 목록 API. 업무 기능 단계와 별도로 인증·membership을 확인한다."""

from fastapi import APIRouter, Depends
from ..domain.models import Actor
from ..workspace import WORKSPACE_ID, WORKSPACE_NAME


def account_router(store, account, actor, capabilities):
    router = APIRouter()

    @router.get("/me")
    def me(user: dict = Depends(account)):
        member = store.get_membership(user["id"])
        display = member.get("display_name") if member else None
        return {"user": {**user, "display_name": display or user["display_name"]},
                "workspace": {"id": WORKSPACE_ID, "name": WORKSPACE_NAME}, "membership": bool(member),
                "message": "모임 팀에 연결되었습니다." if member else "로그인은 확인되었습니다. 팀 관리자에게 멤버 등록을 요청해주세요."}

    @router.get("/catalog")
    def catalog(owner: Actor = Depends(actor)):
        return {**store.catalog(owner), "capabilities": dict(capabilities)}

    return router
