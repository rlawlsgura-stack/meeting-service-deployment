"""업무 원본을 호스트와 별도 MCP 프로세스가 함께 읽는 임시 자료로 투영한다."""

import asyncio
from copy import deepcopy
import inspect
import json
from pathlib import Path

from ..domain.scheduling import query_scope
from ..domain.time_rules import utc_now
from ..domain.validation import source_contents


class SourceStore:
    """MCP와 공유하는 임시 원본이다. 실행 기록이나 영구 업무 DB를 저장하지 않는다."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.exists():
            self._write({"sources": {}})

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def snapshot(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def manifest(self):
        value = self.snapshot()
        return {"origin": value.get("origin", str(self.path)),
                "sources": {key: {"records": row["records"], "error": row.get("error")}
                            for key, row in value["sources"].items()}}

    def read_source(self, source_id, request, cycle=0, now=None):
        value = self.snapshot()
        source = value["sources"].get(source_id)
        error = source.get("error") if source else {"type": "SourceUnavailable", "message": "요청한 원본이 없습니다."}
        records = deepcopy(source["records"]) if source and not error else []
        return {"source_id": source_id, "origin": value.get("origin", str(self.path)),
                "request_id": request["request_id"], "revision": request["revision"], "collection_cycle": cycle,
                "scope": query_scope(source_id, request), "meeting_date": request["meeting_date"], "timezone": request["timezone"],
                "observed_at": source.get("observed_at") or utc_now(now).isoformat() if source else utc_now(now).isoformat(),
                "status": "error" if error else "ok" if records else "empty", "records": records, "error": deepcopy(error)}


class ProviderSourceStore(SourceStore):
    """앱이 읽은 실제 원본을 MCP에 전달하고 채택 직전에 현재 원본을 다시 읽는다."""

    def __init__(self, path, request, provider, snapshot):
        self.provider = provider
        super().__init__(path)
        self.sync(request, snapshot)

    def sync(self, request, snapshot):
        value = source_contents(snapshot, request)
        for row in value["sources"].values():
            row["observed_at"] = snapshot.get("observed_at")
        self._write(value)

    async def advance(self, request, cycle):
        snapshot = self.provider(deepcopy(request))
        if inspect.isawaitable(snapshot):
            snapshot = await snapshot
        self.sync(request, snapshot)


async def read_calendars(request, store, source_ids, cycle=0, now=None):
    """각 참석자 원본의 성공·정상 빈 결과·실패를 구분해 받는다."""
    async def read(source_id):
        await asyncio.sleep(0)
        return store.read_source(source_id, request, cycle, now)
    return await asyncio.gather(*(read(source_id) for source_id in source_ids))
