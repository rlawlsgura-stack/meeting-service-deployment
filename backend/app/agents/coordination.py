"""현재 담당 전환과 중앙 도구 배분. 그래프 실행·원본 조회는 engine/workflow가 맡는다."""

import json
from langchain.agents import AgentState, create_agent
from langchain.messages import AIMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command
from typing_extensions import NotRequired
from ..domain.scheduling import validate_request


class CoordinationState(AgentState):
    request: NotRequired[dict]
    active_agent: NotRequired[str]
    result: NotRequired[dict | None]
    decision: NotRequired[str]
    answer: NotRequired[str]
    transfers: NotRequired[list[dict]]
    trace: NotRequired[list[dict]]


def message_for_tool(text, call_id):
    return ToolMessage(content=json.dumps(text, ensure_ascii=False, default=str), tool_call_id=call_id)


def handoff_update(runtime):
    """제공 검사: 유효 요청과 원래 호출/응답 쌍을 만든다. 다음 담당은 Command가 정한다."""
    request = validate_request(runtime.state["request"])
    call = runtime.state["messages"][-1]
    if not isinstance(call, AIMessage) or len(call.tool_calls) != 1:
        raise ValueError("인계 도구는 한 번에 하나만 호출합니다.")
    if call.tool_calls[0]["id"] != runtime.tool_call_id:
        raise ValueError("인계 도구의 원래 호출 ID가 필요합니다.")
    transfer = {"from": "intake", "to": "supervisor", "tool_call_id": runtime.tool_call_id}
    return {"active_agent": "supervisor", "request": request,
        "messages": [call, message_for_tool({"request": request, "accepted": True}, runtime.tool_call_id)],
        "transfers": [*runtime.state.get("transfers", []), transfer],
        "trace": [*runtime.state.get("trace", []), {"stage": "handoff", "role": "intake",
                  "tool": "transfer_to_supervisor", "status": "accepted", **transfer}]}


INTAKE_RULES = '너는 일정 접수 담당이다. 구조 검사된 현재 request를 transfer_to_supervisor로 중앙 조정 담당에게 인계한다. 도구는 하나씩 호출하고 인계 뒤 응답은 다음 담당에게 맡긴다.'
SUPERVISOR_RULES = '너는 일정 조정 Supervisor다. 실제 조사 결과가 없으면 investigate_schedule을 호출해 필요한 담당에게 맡긴다. 조건이 모순되어 조회할 수 없으면 request_clarification으로 묻는다. 조사 결과를 읽고 결과가 있으면 finish_coordination으로 마무리한다. 도구는 하나씩 호출한다. 원본 확인 실패는 성공으로 바꾸지 않는다. 조사 결과가 이미 있으면 중복 조사를 하지 않는다. 종료 도구를 호출한 뒤에는 짧게 응답하고 끝낸다. 예약 확정과 저장은 서비스가 사용자 승인을 받아 처리하며 너에게는 쓰기 권한이 없다.'


def create_coordination_agents(model, investigate_tool, clarify_tool, finish_tool):
    """TODO 3 · 현재 담당을 넘기는 인계와 결과를 받는 중앙 담당을 연결한다.

    입력: 모델과 제공된 조사/질문/종료 도구. 반환: (접수 에이전트, 중앙 에이전트).
    읽기: CoordinationState → handoff_update → 이 함수 → engine._coordination_graph.
    """
    @tool
    def transfer_to_supervisor(runtime: ToolRuntime) -> Command:
        """검사된 일정 요청을 중앙 조정 담당에게 넘긴다. 예약을 확정하지 않는다."""
        return Command(goto="supervisor", graph=Command.PARENT, update=handoff_update(runtime))
    intake = create_agent(model, tools=[transfer_to_supervisor], state_schema=CoordinationState,
                          system_prompt=INTAKE_RULES)
    supervisor = create_agent(model, tools=[investigate_tool, clarify_tool, finish_tool],
                              state_schema=CoordinationState, system_prompt=SUPERVISOR_RULES)
    return intake, supervisor
