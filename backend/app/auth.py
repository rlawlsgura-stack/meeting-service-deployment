"""Supabase SDK로 인증을 중계한다. 사용자 검증은 Auth 서버의 get_user가 맡는다."""

from urllib.parse import urlparse
from uuid import UUID

import httpx
from supabase import acreate_client
from supabase.lib.client_options import AsyncClientOptions
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError, AuthError as SDKAuthError


class AuthError(Exception):
    """공개 오류만 보관한다. 공급자 원문·토큰·비밀번호는 응답하지 않는다."""

    def __init__(self, detail, *, status_code=401, code="AUTH_REJECTED"):
        super().__init__(detail)
        self.detail, self.status_code, self.code = detail, status_code, code


def bearer_token(authorization):
    parts = (authorization or "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 16000:
        raise AuthError("로그인한 뒤 다시 시도해주세요.", code="LOGIN_REQUIRED")
    return parts[1]


class SupabaseAuth:
    def __init__(self, supabase_url, publishable_key, *, http_client=None, client_factory=None):
        self.url = supabase_url.rstrip("/")
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("SUPABASE_URL에는 HTTPS 프로젝트 주소가 필요합니다.")
        if not publishable_key or publishable_key.startswith("sb_secret_"):
            raise ValueError("SUPABASE_PUBLISHABLE_KEY가 필요합니다.")
        self.key, self.client_factory = publishable_key, client_factory
        self.http = http_client or httpx.AsyncClient(timeout=10)
        self.owns_http = http_client is None

    async def _client(self):
        factory = self.client_factory or acreate_client
        # 요청마다 SDK 상태를 새로 만든다. 공유 HTTP 풀의 사용자 헤더는 바꾸지 않는다.
        return await factory(self.url, self.key, options=AsyncClientOptions(
            httpx_client=self.http, persist_session=False, auto_refresh_token=False))

    async def _call(self, operation, *, signup=False):
        try:
            client = await self._client()
            return await operation(client.auth)
        except AuthWeakPasswordError as error:
            raise AuthError("프로젝트의 비밀번호 조건을 확인해주세요.", status_code=422, code="WEAK_PASSWORD") from error
        except AuthApiError as error:
            if error.status == 429:
                raise AuthError("요청이 많습니다. 잠시 뒤 다시 시도해주세요.", status_code=429, code="AUTH_RATE_LIMIT") from error
            if error.status >= 500:
                raise AuthError("인증 서버 요청을 완료하지 못했습니다.", status_code=502, code="AUTH_UNAVAILABLE") from error
            if error.code == "email_not_confirmed":
                raise AuthError("이메일을 확인한 뒤 로그인해주세요.", status_code=403, code="EMAIL_UNCONFIRMED") from error
            if signup:
                status = 409 if error.code in {"user_already_exists", "email_exists"} else 400
                raise AuthError("가입 조건과 이메일 발송 설정을 확인해주세요.", status_code=status, code="SIGNUP_REJECTED") from error
            raise AuthError("인증 정보를 확인하고 다시 로그인해주세요.") from error
        except (SDKAuthError, httpx.RequestError) as error:
            raise AuthError("인증 서버에 연결하지 못했습니다.", status_code=502, code="AUTH_UNAVAILABLE") from error

    @staticmethod
    def _user(user):
        if user is None or user.role != "authenticated" or user.is_anonymous is True:
            raise AuthError("로그인한 계정을 확인할 수 없습니다.")
        try:
            identity = str(UUID(str(user.id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise AuthError("로그인한 계정을 확인할 수 없습니다.") from error
        metadata = user.user_metadata if isinstance(user.user_metadata, dict) else {}
        name = metadata.get("display_name", metadata.get("full_name"))
        return {"id": identity, "email": user.email,
                "display_name": name.strip()[:200] if isinstance(name, str) else None}

    @classmethod
    def _tokens(cls, result):
        user, session = cls._user(result.user), result.session
        if (session is None or not isinstance(session.access_token, str) or not session.access_token
                or not isinstance(session.refresh_token, str) or not session.refresh_token
                or type(session.expires_in) is not int or session.expires_in <= 0):
            raise AuthError("로그인 결과를 확인할 수 없습니다.")
        return {"user_id": user["id"], "user": user, "access_token": session.access_token,
                "refresh_token": session.refresh_token, "expires_in": session.expires_in}

    async def verify(self, token):
        if not isinstance(token, str) or not token or len(token) > 16000:
            raise AuthError("로그인한 뒤 다시 시도해주세요.", code="LOGIN_REQUIRED")
        # 토큰을 로컬 decode하지 않는다. 모든 서명 방식은 Auth 서버가 검증한다.
        result = await self._call(lambda auth: auth.get_user(token))
        return self._user(result.user if result else None)

    async def signup(self, email, password):
        result = await self._call(lambda auth: auth.sign_up({"email": email, "password": password}), signup=True)
        try:
            identity = str(UUID(str(result.user.id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise AuthError("가입 결과를 확인할 수 없습니다.", status_code=502, code="AUTH_UNAVAILABLE") from error
        # Confirm email 설정과 무관하게 가입 응답에는 토큰을 전달하지 않는다.
        return {"user_id": identity, "email_confirmation_required": result.session is None}

    async def login(self, email, password):
        return self._tokens(await self._call(lambda auth: auth.sign_in_with_password({"email": email, "password": password})))

    async def refresh(self, refresh_token):
        return self._tokens(await self._call(lambda auth: auth.refresh_session(refresh_token)))

    async def logout(self, access_token):
        # admin 이름과 별개로 공개 키+사용자 JWT로 해당 세션만 종료한다.
        await self._call(lambda auth: auth.admin.sign_out(access_token, scope="local"))

    async def aclose(self):
        if self.owns_http:
            await self.http.aclose()
