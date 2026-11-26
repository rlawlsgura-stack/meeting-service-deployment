"""같은 파일 원본을 읽는 별도 MCP 프로세스. stdout은 프로토콜 전용이다."""

import os
from pathlib import Path
import sys

from mcp.server import MCPServer

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.domain.scheduling import validate_room_request
from app.tools.source_io import SourceStore

mcp = MCPServer("verified-schedule-room-source", log_level="WARNING")


@mcp.tool()
def find_rooms(request: dict, cycle: int = 0, observed_at: str | None = None) -> dict[str, object]:
    """시간 후보를 기다리지 않고 요청 범위의 방 원본을 조사한다."""
    request = validate_room_request(request)
    store = SourceStore(Path(sys.argv[1]))
    # 서버는 읽기만 한다. 실제 조회 횟수는 반환값을 받은 앱이 기록한다.
    receipt = store.read_source("rooms", request, cycle, observed_at)
    return {"status": "lookup_unavailable" if receipt["status"] == "error" else "ready", "receipt": receipt,
            "room_lookups": 1, "server_pid": os.getpid()}


if __name__ == "__main__":
    mcp.run(transport="stdio")
