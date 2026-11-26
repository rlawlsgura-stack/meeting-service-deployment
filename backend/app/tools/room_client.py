"""실제 stdio 연결·도구 발견·원본 응답을 보존하는 제공 MCP 클라이언트."""

import os
from pathlib import Path
import sys
import traceback

from mcp import Client, StdioServerParameters

from ..domain.scheduling import room_request_for
from ..domain.time_rules import utc_now


async def lookup_rooms(request, store, cycle=0, now=None):
    """시간 후보를 기다리지 않고 요청의 방 조건만 MCP에 전달한다."""
    packet = room_request_for(request)  # 서버에는 방 판단에 필요한 투영만 전달한다.
    metadata = {"transport": "stdio", "client_pid": os.getpid(), "connected": False,
                "protocol_version": None, "tools": [], "call_attempted": False,
                "is_error": None, "raw_result": None}
    server = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).with_name("room_server.py").resolve()), str(store.path)])
    try:
        async with Client(server, read_timeout_seconds=10) as client:
            metadata.update(connected=True, protocol_version=client.protocol_version)
            definitions = await client.list_tools()
            metadata["tools"] = [{"name": item.name, "input_schema": item.input_schema} for item in definitions.tools]
            metadata["call_attempted"] = True
            response = await client.call_tool("find_rooms", {"request": packet,
                                                "cycle": cycle, "observed_at": utc_now(now).isoformat() if now is not None else None})
            metadata.update(is_error=response.is_error, raw_result=response.model_dump(mode="json"))
            body = response.structured_content
            if response.is_error or not isinstance(body, dict) or "receipt" not in body:
                raise RuntimeError("MCP 응답에 사용 가능한 원본 영수증이 없습니다.")
            return {**body, "mcp": metadata, "error": None}
    except Exception as error:
        return {"status": "lookup_unavailable", "proposal": None, "receipt": None,
                "room_lookups": None if metadata["call_attempted"] else 0, "mcp": metadata,
                "error": {"type": type(error).__name__, "message": str(error),
                          "traceback": "".join(traceback.format_exception(error))}}
