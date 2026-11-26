"""자연어 분류 → 담당 인계 → 중앙 조정 → 검증된 일정 제안을 연결한다.

모델은 요청을 해석하고 조회를 위임한다. 예약 저장과 사용자 승인 판단은 서비스 계층의 일이다.
"""

from copy import deepcopy
import inspect
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import ToolRuntime, tool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ..domain.scheduling import validate_request
from .router import ScheduleRouter
from .coordination import CoordinationState, create_coordination_agents, message_for_tool as _message
from .explanation import EXPLANATION_RULES, explanation_packet, explanation_text
from ..tools.source_io import ProviderSourceStore
from ..domain.verification import bound_receipt_issues, proposal_issues
from .workflow import run_collaboration
from .runtime import investigation_trace


logger = logging.getLogger("schedule.coordination")


class AgentEngine:
    """동일한 모델·원천 제공자를 주입받는다. 엔진에는 예약을 쓰는 도구가 없다."""

    def __init__(self, model, source_provider, *, max_refreshes=2, participant_provider=None, rooms=False, parallel=False, collaboration=False):
        if model is None:
            raise ValueError("Router와 담당 에이전트가 사용할 모델이 필요합니다.")
        self.model, self.source_provider, self.max_refreshes = model, source_provider, max_refreshes
        self.rooms, self.parallel, self.collaboration = rooms, parallel, collaboration
        self.router = ScheduleRouter(model, participant_provider=participant_provider)

    async def parse(self, message, current_request=None):
        """요청 해석은 독립 Router에 맡긴다."""
        context = current_request if self.rooms else {"intent": "time_only", **(current_request or {})}
        return await self.router.parse(message, context)

    async def explain_proposal(self, request, result, *, previous_explanation="", feedback=""):
        """TODO 5 · 검증된 제안과 피드백으로 실제 설명 모델을 호출한다.

        입력: 요청/검증 결과/직전 설명/사용자 피드백. 반환: 설명 문자열.
        읽기: explanation_packet → EXPLANATION_RULES → 이 함수 → 서비스의 채택 전 재검사.
        """
        packet = explanation_packet(request, result, previous_explanation, feedback)
        response = await self.model.ainvoke([
            SystemMessage(content=EXPLANATION_RULES),
            HumanMessage(content=json.dumps(packet, ensure_ascii=False)),
        ])
        return explanation_text(response, packet)

    async def _snapshot(self, request):
        value = self.source_provider(deepcopy(request))
        return await value if inspect.isawaitable(value) else value

    async def _investigate_sources(self, request):
        """임시 원본만 MCP 프로세스와 공유한다. 실행 기록 파일은 저장하지 않는다."""
        snapshot = await self._snapshot(request)
        with TemporaryDirectory(prefix="schedule-sources-") as folder:
            store = ProviderSourceStore(Path(folder) / "sources.json", request, self.source_provider, snapshot)
            return await run_collaboration(request, store, model=self.model, max_refreshes=self.max_refreshes, parallel=self.parallel)

    async def validate_latest(self, request, result):
        """확정 직전 현재 요청·원본 내용·원본 제약을 다시 검사하는 서버 측 경계다."""
        request = validate_request(request)
        snapshot = await self._snapshot(request)
        with TemporaryDirectory(prefix="schedule-check-") as folder:
            store = ProviderSourceStore(Path(folder) / "sources.json", request, self.source_provider, snapshot)
            manifest = store.manifest()
            keys = ([f"calendar:{person}" for person in request["participants"]]
                    if request["intent"] != "room_only" else [])
            if request["intent"] != "time_only":
                keys.append("rooms")
            receipts = result.get("receipts", {})
            issues = [issue for key in keys for issue in bound_receipt_issues(
                key, receipts.get(key, {}), request, manifest)]
            if request["intent"] == "time_only":
                proposals = result.get("time_candidates") or []
            else:
                proposals = [result["proposal"]] if result.get("proposal") else []
            if not proposals:
                issues.append({"source_id": None, "reason": "missing_proposal"})
            if not issues:
                issues.extend({"source_id": None, "reason": reason} for proposal in proposals
                              for reason in proposal_issues(proposal, request, receipts))
            return issues

    def _coordination_graph(self):
        """Handoffs는 담당 전환, Supervisor는 도구로 부른 조사 결과의 다음 처리다."""
        @tool
        async def investigate_schedule(runtime: ToolRuntime) -> Command:
            """현재 조건의 시간·회의실 담당에게 조사를 위임하고 원본 검증·필요한 부분 갱신 결과를 받는다."""
            if runtime.state.get("result") is not None:
                return Command(update={"messages": [_message("이번 요청의 조사 결과가 이미 있습니다. 결과에 따라 마무리하세요.", runtime.tool_call_id)]})
            result = await self._investigate_sources(runtime.state["request"])
            summary = {"status": result["status"], "proposal": result["proposal"],
                       "time_candidates": result["time_candidates"], "refreshes": result["counters"]["refreshes"]}
            trace = list(runtime.state.get("trace", []))
            request = runtime.state["request"]
            trace.append({"stage": "supervision", "role": "supervisor", "tool": "investigate_schedule", "status": "delegated"})
            trace += investigation_trace(request, result)
            return Command(update={"result": result, "trace": trace,
                                   "messages": [_message(summary, runtime.tool_call_id)]})

        @tool(return_direct=True)
        def request_clarification(question: str, runtime: ToolRuntime) -> Command:
            """일정을 정하는 데 부족하거나 모순된 조건을 사용자에게 묻고 현재 조정을 끝낸다."""
            return Command(update={"decision": "needs_clarification", "answer": question,
                "trace": [*runtime.state.get("trace", []), {"stage": "supervision", "role": "supervisor",
                          "tool": "request_clarification", "status": "needs_clarification"}],
                "messages": [_message({"question": question}, runtime.tool_call_id)]})

        @tool(return_direct=True)
        def finish_coordination(runtime: ToolRuntime) -> Command:
            """실제 조사 결과에 맞춰 제안 또는 처리 불가를 정리한다. 승인이나 예약 쓰기는 수행하지 않는다."""
            result = runtime.state.get("result")
            status = result.get("status") if result else "incomplete"
            decision = ("proposal" if status in ("verified", "time_ready") else
                        "no_result" if status in ("no_time", "no_room") else "needs_recheck")
            answer = {"proposal": "현재 조건과 원본으로 확인한 후보입니다. 확정 전에 제안을 확인해주세요.",
                      "no_result": "현재 조건을 만족하는 후보가 없습니다. 조건을 조정해 다시 조회할 수 있습니다.",
                      "needs_recheck": "원본을 확인하지 못해 제안을 채택하지 않았습니다. 원천 상태를 확인한 뒤 다시 조회해주세요."}[decision]
            return Command(update={"decision": decision, "answer": answer,
                "trace": [*runtime.state.get("trace", []), {"stage": "supervision", "role": "supervisor",
                          "tool": "finish_coordination", "status": decision}],
                "messages": [_message({"kind": decision, "status": status, "reservation_written": False}, runtime.tool_call_id)]})

        intake, supervisor = create_coordination_agents(
            self.model, investigate_schedule, request_clarification, finish_coordination)

        async def call_intake(state):
            return await intake.ainvoke(state)

        async def call_supervisor(state):
            # 필요한 인계 호출·응답과 현재 조건만 전달한다. 이전 사용자 대화 전체를 재전송하지 않는다.
            messages = state["messages"]
            if state.get("transfers"):
                start = next(index for index, message in enumerate(messages) if isinstance(message, AIMessage)
                             and any(call["name"] == "transfer_to_supervisor" for call in message.tool_calls))
                messages = messages[start:]
            return await supervisor.ainvoke({**state, "messages": messages})

        builder = StateGraph(CoordinationState)
        builder.add_node("intake", call_intake)
        builder.add_node("supervisor", call_supervisor)
        builder.add_conditional_edges(START, lambda state: state.get("active_agent", "intake"), ["intake", "supervisor"])
        builder.add_edge("intake", END)
        builder.add_edge("supervisor", END)
        return builder.compile()

    async def investigate(self, request, *, active_agent="intake"):
        """접수/중앙 담당이 실제 에이전트 조사 결과를 받는다. 대화의 담당은 API가 보관한다."""
        request = validate_request(request)
        if request["intent"] != "time_only" and not self.rooms:
            return {"status": "unsupported", "kind": "unsupported", "request": request, "proposal": None,
                    "time_candidates": [], "receipts": {}, "rounds": [], "trace": [], "active_agent": "time",
                    "answer": "지금은 공통 시간 조회를 도와드려요. 회의실 조사는 아직 연결하지 않았어요."}
        if not self.collaboration:
            result = await self._investigate_sources(request)
            status = result["status"]
            kind = ("proposal" if status in ("verified", "time_ready") else
                    "no_result" if status in ("no_time", "no_room") else "needs_recheck")
            answer = {"proposal": "현재 조건과 원본으로 확인한 후보입니다. 아직 예약을 등록하지 않았습니다.",
                      "no_result": "현재 조건을 만족하는 후보가 없습니다. 조건을 조정해 다시 조회할 수 있습니다.",
                      "needs_recheck": "원본을 확인하지 못해 제안을 채택하지 않았습니다. 다시 조회해주세요."}[kind]
            return {**result, "kind": kind, "answer": answer, "active_agent": "direct" if self.rooms else "time",
                    "trace": investigation_trace(request, result)}
        # 같은 문의를 확장해도 이전 직접 담당을 중앙 접수 담당으로 이어서 시작한다.
        if active_agent in ("time", "direct"):
            active_agent = "intake"
        if active_agent not in ("intake", "supervisor"):
            raise ValueError("현재 담당은 intake 또는 supervisor여야 합니다.")
        state = await self._coordination_graph().ainvoke({
            "request": request, "active_agent": active_agent, "result": None, "decision": "incomplete",
            "answer": "", "transfers": [], "trace": [],
            "messages": [HumanMessage(content=json.dumps({"request": request}, ensure_ascii=False))],
        }, config={"recursion_limit": 18})
        result, decision = state.get("result"), state.get("decision", "incomplete")
        answer, trace = state.get("answer", ""), list(state.get("trace", []))
        errors = [message for message in state["messages"]
                  if getattr(message, "type", None) == "tool" and getattr(message, "status", None) == "error"]
        expected = ("proposal" if result and result.get("status") in ("verified", "time_ready") else
                    "no_result" if result and result.get("status") in ("no_time", "no_room") else "needs_recheck")
        reason = ("missing_terminal_decision" if decision not in ("proposal", "no_result", "needs_recheck", "needs_clarification") else
                  "empty_terminal_answer" if not isinstance(answer, str) or not answer.strip() else
                  "missing_investigation_result" if decision != "needs_clarification" and not result else
                  "terminal_result_mismatch" if decision != "needs_clarification" and decision != expected else None)
        if reason and errors:
            reason = "tool_call_error"
        result = deepcopy(result) if result else {"proposal": None, "request": request,
                 "receipts": {}, "rounds": [], "time_candidates": [], "counters": {}}
        if reason:
            # 종료 계약 실패를 성공이나 '후보 없음'으로 바꾸지 않는다. 원본 조회를 다시 실행하지 않는다.
            logger.warning("request_id=%s revision=%s stage=coordination reason=%s active_agent=%s",
                           request["request_id"], request["revision"], reason, state.get("active_agent", active_agent))
            trace.append({"stage": "supervision", "role": state.get("active_agent", active_agent),
                          "tool": "coordination_guard", "status": "needs_recheck", "reason": reason,
                          "error_tool": getattr(errors[-1], "name", None) if errors else None})
            result.update(status="needs_recheck", proposal=None, time_candidates=[])
            decision, answer = "needs_recheck", "조정이 완료되지 않아 조회 결과를 채택하지 않았습니다. 같은 조건으로 다시 조회해주세요."
        elif decision == "needs_clarification":
            result["status"] = "needs_clarification"
        return {**result, "active_agent": state.get("active_agent", active_agent),
                "kind": decision,
                "answer": answer,
                "trace": trace,
                "coordination": {"transfers": state.get("transfers", []),
                                 "messages": [message.model_dump(mode="json") for message in state["messages"]]}}
