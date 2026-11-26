"""PostgreSQL의 업무 원본·문의·예약을 읽고 저장한다. DB 준비는 SQL 파일로 분리한다."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..workspace import WORKSPACE_ID, WORKSPACE_NAME
from .availability import DomainConflict, reserve_domain, snapshot_domain


class ConflictError(Exception):
    pass


class OwnershipError(Exception):
    pass


class ScheduleRepository:
    """다른 요청이 먼저 바꾼 문의는 덮어쓰지 않고, 같은 제안은 한 번만 저장한다."""

    def __init__(self, database_url):
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("Supabase PostgreSQL DATABASE_URL이 필요합니다.")
        self.pool = ConnectionPool(database_url, open=False, min_size=1, max_size=10, timeout=10,
                                   kwargs={"row_factory": dict_row})

    def open(self):
        """서버 시작 때 연결을 준비한다. 테이블이나 초기 데이터를 만들지 않는다."""
        self.pool.open(wait=True, timeout=10)

    def close(self):
        """서버 종료 때 빌려준 연결이 돌아오면 풀을 닫는다."""
        self.pool.close()

    @contextmanager
    def _connection(self, *, write=False):
        with self.pool.connection() as connection:
            with connection.transaction():
                connection.execute("SET LOCAL search_path TO schedule_service, pg_catalog")
                yield connection

    def _execute(self, connection, sql, parameters=()):
        return connection.execute(sql, parameters)

    def get_membership(self, user_id):
        """계정 인증과 별개인 서버 명단. 요청의 team_id/user_metadata는 조회 기준이 아니다."""
        with self._connection() as connection:
            row = self._execute(connection,
                "SELECT workspace_id,user_id,display_name,role FROM workspace_memberships WHERE workspace_id=%s AND user_id=%s",
                (WORKSPACE_ID, user_id)).fetchone()
        return dict(row) if row else None

    def participant_catalog(self):
        """UI와 Router가 공유하는 등록 참석자 ID/이름이다. Auth 사용자 명단이 아니다."""
        with self._connection() as connection:
            rows = self._execute(connection, "SELECT id,name FROM participants ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def catalog(self, actor):
        if actor.team_id != WORKSPACE_ID:
            raise OwnershipError("등록된 workspace의 참조 목록만 볼 수 있습니다.")
        with self._connection() as connection:
            people = self._execute(connection, "SELECT id,name FROM participants ORDER BY id").fetchall()
            rooms = self._execute(connection, "SELECT id,name,seats FROM rooms ORDER BY id").fetchall()
            equipment = self._execute(connection, "SELECT room_id,equipment,setup_minutes FROM room_equipment ORDER BY room_id,equipment").fetchall()
            days = self._execute(connection, "SELECT meeting_date FROM calendar_windows UNION SELECT meeting_date FROM room_windows ORDER BY meeting_date").fetchall()
        values = []
        for room in rooms:
            setup = {row["equipment"]: row["setup_minutes"] for row in equipment if row["room_id"] == room["id"]}
            values.append({**dict(room), "equipment": list(setup), "setup": setup})
        return {"workspace": {"id": WORKSPACE_ID, "name": WORKSPACE_NAME},
                "participants": [dict(row) for row in people], "rooms": values,
                "dates": [row["meeting_date"].isoformat() if hasattr(row["meeting_date"], "isoformat") else row["meeting_date"] for row in days]}

    @staticmethod
    def _owned(row, actor):
        if row is None:
            raise KeyError("문의를 찾을 수 없습니다.")
        if row["owner_id"] != actor.owner_id or row["team_id"] != actor.team_id:
            raise OwnershipError("이 문의에 접근할 수 없습니다.")

    def create_session(self, actor):
        identity = str(uuid4())
        payload = {"id": identity, "request": None, "draft": {}, "pending": None,
                   "result": None, "active_agent": "intake", "status": "awaiting_request",
                   "reply": "날짜·참석자·시간 범위와 회의 길이를 알려주세요.",
                   "trace": [], "event": None}
        with self._connection(write=True) as connection:
            self._execute(connection, "INSERT INTO schedule_sessions (id,owner_id,team_id,version,payload) VALUES (%s,%s,%s,%s,%s)",
                          (identity, actor.owner_id, actor.team_id, 1, json.dumps(payload, ensure_ascii=False)))
        return {**payload, "version": 1}

    def get_session(self, identity, actor):
        with self._connection() as connection:
            row = self._execute(connection, "SELECT * FROM schedule_sessions WHERE id=%s", (identity,)).fetchone()
            self._owned(row, actor)
            return {**json.loads(row["payload"]), "version": row["version"]}

    def update_session(self, identity, actor, payload, *, expected_version, explanation_token=None):
        clean = {key: deepcopy(value) for key, value in payload.items() if key != "version"}
        with self._connection(write=True) as connection:
            row = self._execute(connection, "SELECT * FROM schedule_sessions WHERE id=%s FOR UPDATE", (identity,)).fetchone()
            self._owned(row, actor)
            if row["version"] != expected_version:
                raise ConflictError("다른 작업으로 상태가 바뀌었습니다. 현재 상태를 다시 확인하세요.")
            if explanation_token is not None:
                held = self._execute(connection,
                    "SELECT id FROM schedule_sessions WHERE id=%s AND explanation_token=%s AND explanation_until > CURRENT_TIMESTAMP",
                    (identity, explanation_token)).fetchone()
                if held is None:
                    raise ConflictError("설명 처리 시간이 지났거나 다른 요청이 처리를 이어받았습니다.")
            cursor = self._execute(connection, "UPDATE schedule_sessions SET payload=%s,version=version+1 WHERE id=%s AND version=%s",
                                   (json.dumps(clean, ensure_ascii=False), identity, expected_version))
            if cursor.rowcount != 1:
                raise ConflictError("다른 작업으로 상태가 바뀌었습니다.")
        return {**clean, "version": expected_version + 1}

    def get_event(self, proposal_id, actor):
        with self._connection() as connection:
            row = self._execute(connection, "SELECT * FROM reservations WHERE proposal_id=%s", (proposal_id,)).fetchone()
            if row is None:
                return None
            self._owned(row, actor)
            return json.loads(row["payload"])

    def confirm_event(self, identity, actor, pending, payload, *, expected_version, source_contents):
        """현재 원본과 문의를 다시 확인한 뒤 예약과 화면 상태를 함께 저장한다."""
        clean = {key: deepcopy(value) for key, value in payload.items() if key != "version"}
        with self._connection(write=True) as connection:
            row = self._execute(connection, "SELECT * FROM schedule_sessions WHERE id=%s FOR UPDATE", (identity,)).fetchone()
            self._owned(row, actor)
            existing = self._execute(connection, "SELECT * FROM reservations WHERE proposal_id=%s", (pending["proposal_id"],)).fetchone()
            if existing:
                self._owned(existing, actor)
                event = json.loads(existing["payload"])
                if event["session_id"] != identity or event["content"] != pending["content"] or event["revision"] != pending["revision"]:
                    raise ConflictError("이미 저장한 제안과 요청 내용이 다릅니다.")
                return {**json.loads(row["payload"]), "version": row["version"]}, event
            if row["version"] != expected_version:
                raise ConflictError("확인하는 동안 요청이 바뀌었습니다.")
            if pending.get("source_contents") != source_contents:
                raise ConflictError("확인한 제안의 원본 근거가 다릅니다. 다시 조회하세요.")
            event = {"event_id": str(uuid4()), "proposal_id": pending["proposal_id"], "session_id": identity,
                     "request_id": clean["request"]["request_id"], "revision": pending["revision"],
                     "content": deepcopy(pending["content"]), "participants": deepcopy(clean["request"]["participants"]),
                     "meeting_date": clean["request"]["meeting_date"], "workspace_id": actor.team_id, "saved_at": datetime.now(ZoneInfo("UTC")).isoformat()}
            try:
                reserve_domain(connection, self._execute, clean["request"],
                    {**pending, "event": event, "owner_id": actor.owner_id, "team_id": actor.team_id})
            except DomainConflict as error:
                raise ConflictError(str(error)) from error
            clean.update(status="saved", pending=None, event=event, reply="확인한 회의 제안을 저장했습니다.")
            cursor = self._execute(connection, "UPDATE schedule_sessions SET payload=%s,version=version+1 WHERE id=%s AND version=%s",
                          (json.dumps(clean, ensure_ascii=False), identity, expected_version))
            if cursor.rowcount != 1:
                raise ConflictError("확인하는 동안 요청이 바뀌었습니다.")
        return {**clean, "version": expected_version + 1}, event

    def snapshot_sources(self, request):
        """실제 날짜의 가능 구간에서 저장된 예약을 제외한 원본을 읽는다."""
        with self._connection() as connection:
            return snapshot_domain(connection, self._execute, request)

    def list_events(self, actor):
        """화면·자동화용 읽기. 호출자의 소유 범위 밖 사건은 반환하지 않는다."""
        with self._connection() as connection:
            rows = self._execute(connection,
                "SELECT payload FROM reservations WHERE owner_id=%s AND team_id=%s ORDER BY proposal_id",
                (actor.owner_id, actor.team_id)).fetchall()
        return sorted((json.loads(row["payload"]) for row in rows), key=lambda row: row["saved_at"], reverse=True)

    def health(self):
        with self._connection() as connection:
            row = self._execute(connection, "SELECT id FROM schedule_meta WHERE id=%s", ("origin",)).fetchone()
            if row is None:
                raise RuntimeError("DB의 schema.sql과 seed.sql 준비를 확인하세요.")
        return "ok"

    def claim_explanation(self, identity, actor, *, expected_version):
        """같은 문의의 설명 생성을 하나만 시작한다. 모델 응답을 기다릴 때 DB 연결은 반환한다."""
        with self._connection(write=True) as connection:
            row = self._execute(connection, "SELECT * FROM schedule_sessions WHERE id=%s FOR UPDATE", (identity,)).fetchone()
            self._owned(row, actor)
            if row["version"] != expected_version:
                raise ConflictError("다른 작업으로 문의가 바뀌었습니다. 현재 상태를 다시 확인하세요.")
            active = self._execute(connection,
                "SELECT id FROM schedule_sessions WHERE id=%s AND explanation_token IS NOT NULL AND explanation_until > CURRENT_TIMESTAMP",
                (identity,)).fetchone()
            if active is not None:
                raise ConflictError("설명을 생성하고 있습니다. 완료한 뒤 다시 확인해주세요.")
            token = str(uuid4())
            self._execute(connection,
                "UPDATE schedule_sessions SET explanation_token=%s,explanation_until=CURRENT_TIMESTAMP + INTERVAL '180 seconds' WHERE id=%s",
                (token, identity))
        return token

    def release_explanation(self, identity, actor, token):
        """자신이 시작한 설명의 진행 표시만 끝낸다. 다른 요청의 표시는 지우지 않는다."""
        with self._connection(write=True) as connection:
            row = self._execute(connection, "SELECT * FROM schedule_sessions WHERE id=%s FOR UPDATE", (identity,)).fetchone()
            self._owned(row, actor)
            self._execute(connection,
                "UPDATE schedule_sessions SET explanation_token=NULL,explanation_until=NULL WHERE id=%s AND explanation_token=%s",
                (identity, token))
