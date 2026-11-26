"""브라우저는 Auth API를 호출하고 받은 토큰을 다음 요청의 Bearer로 전달한다."""

from fastapi import APIRouter, Depends, Request, Response

from ..auth import AuthError, bearer_token
from .schemas import CredentialsInput, RefreshInput, SignupResponse, TokensResponse, UserResponse


def auth_router(account):
    router = APIRouter(prefix="/api/auth", tags=["인증"])

    def auth_service(request):
        if request.app.state.auth is None:
            raise AuthError("인증 연결을 확인해주세요.", status_code=502, code="AUTH_UNAVAILABLE")
        return request.app.state.auth

    @router.post("/signup", response_model=SignupResponse, status_code=201)
    async def signup(body: CredentialsInput, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return await auth_service(request).signup(body.email, body.password)

    @router.post("/login", response_model=TokensResponse)
    async def login(body: CredentialsInput, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return await auth_service(request).login(body.email, body.password)

    @router.post("/refresh", response_model=TokensResponse)
    async def refresh(body: RefreshInput, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return await auth_service(request).refresh(body.refresh_token)

    @router.post("/logout", status_code=204)
    async def logout(request: Request):
        token = bearer_token(request.headers.get("authorization"))
        await auth_service(request).logout(token)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @router.get("/user", response_model=UserResponse)
    async def user(response: Response, identity: dict = Depends(account)):
        response.headers["Cache-Control"] = "no-store"
        return {"user": identity}

    return router
