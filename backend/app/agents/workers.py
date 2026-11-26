"""동일한 실제 조회를 직접 실행하거나 두 create_agent 담당에게 맡기는 제공 경계."""

import asyncio
import json
import traceback

from time import perf_counter

from langchain.agents import create_agent
from langchain_core.tools import tool


def create_time_agent(model, worker_tool):
    """시간 담당에게는 참석자 원본을 확인하는 find_times만 제공한다."""
    return create_agent(model=model, tools=[worker_tool], system_prompt=(
        "너는 시간 담당이다. 받은 요청은 find_times 도구로 실제 확인한다. 결과를 지어내지 않는다."))


def create_room_agent(model, worker_tool):
    """TODO 1 · 방 조회 책임과 허용 도구를 가진 실제 에이전트를 만든다.

    입력: 모델과 제공된 방 읽기 도구. 반환: 실행 가능한 create_agent 결과.
    읽기: 위 create_time_agent → 이 함수 → run_worker가 전달하는 방 조건.
    """
    return create_agent(model=model, tools=[worker_tool], system_prompt=(
        "너는 회의실 담당이다. 받은 독립 조회 조건은 find_rooms 도구로 실제 확인한다. 결과를 지어내지 않는다."))


async def run_worker(role, model, payload, operation):
    """model=None은 직접 도구 모드이며 에이전트 실행으로 세지 않는다."""
    if model is None:
        result = await operation()
        return {"role": role, "mode": "direct_tools", "result": result,
                "messages": [], "tool_calls": 1, "provided_tools": [], "error": None}
    observed, lock = {"result": None, "tool_calls": 0}, asyncio.Lock()

    async def execute():
        """요청 범위의 실제 원본과 조회 결과를 확인한다."""
        observed["tool_calls"] += 1
        async with lock:
            if observed["result"] is None:
                observed["result"] = await operation()
            return observed["result"]

    # 이름은 실제 모델 메시지의 tool_calls와 ToolMessage에서 확인한다.
    name = "find_times" if role == "time" else "find_rooms"
    worker_tool = tool(name, return_direct=True)(execute)
    worker_tool.description = "요청 범위의 실제 원본과 조회 결과를 확인한다."
    factory = create_time_agent if role == "time" else create_room_agent
    agent = factory(model, worker_tool)
    try:
        reply = await agent.ainvoke({"messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
                                   config={"recursion_limit": 8})
        return {"role": role, "mode": "agents", "result": observed["result"],
                "messages": [message.model_dump(mode="json") for message in reply["messages"]],
                "tool_calls": observed["tool_calls"], "provided_tools": [worker_tool.name], "error": None}
    except NotImplementedError:
        raise
    except Exception as error:
        return {"role": role, "mode": "agents", "result": observed["result"], "messages": [],
                "tool_calls": observed["tool_calls"], "provided_tools": [worker_tool.name], "error": {"type": type(error).__name__, "message": str(error),
                                                           "traceback": "".join(traceback.format_exception(error))}}


async def run_workers(jobs, *, parallel=True):
    """같은 담당 작업을 순차 또는 병렬로 실행하고 실제 시작·종료·오류를 남긴다."""
    events, origin = [], perf_counter()
    async def execute(role, operation):
        events.append({"role": role, "phase": "start", "at_ms": (perf_counter()-origin)*1000})
        try:
            run = await operation()
            events.append({"role": role, "phase": "error" if run["error"] else "end", "at_ms": (perf_counter()-origin)*1000})
            return run
        except NotImplementedError:
            raise
        except Exception as error:
            events.append({"role": role, "phase": "error", "at_ms": (perf_counter()-origin)*1000})
            return {"role": role, "mode": "error", "result": None, "messages": [], "tool_calls": 0,
                    "provided_tools": [], "error": {"type": type(error).__name__, "message": str(error),
                    "traceback": "".join(traceback.format_exception(error))}}
    values = (await asyncio.gather(*(execute(role, operation) for role, operation in jobs.items()))
              if parallel else [await execute(role, operation) for role, operation in jobs.items()])
    return dict(zip(jobs, values)), events
