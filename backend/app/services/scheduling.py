"""대화와 명시적 확정을 분리하는 업무 경계. 모델에는 이 저장 경로를 주지 않는다."""

from copy import deepcopy
import inspect
import logging
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool

from ..domain.models import REQUEST_FIELDS, ScheduleRequest, new_request
from ..repositories.store import ConflictError
from ..domain import policies
from ..domain.validation import source_contents, proposal_issues


logger = logging.getLogger("schedule.service")


class ScheduleService:
    def __init__(self, store, engine, *, capabilities=None):
        self.store, self.engine = store, engine
        self.capabilities = capabilities or {"time": True, "rooms": True, "parallel": True, "collaboration": True, "registration": True, "feedback": True}

    async def list_events(self, actor):
        """현재 계정의 확정 일정을 실제 DB에서 읽는다."""
        return await run_in_threadpool(self.store.list_events, actor)


    @staticmethod
    def public(session, **overrides):
        # 조회 원본·모델 대화 전체 대신 화면에서 읽을 상태와 근거 요약만 돌려준다.
        fields = ("id", "version", "status", "request", "draft", "pending", "reply", "trace", "event", "active_agent",
                  "explanation", "previous_explanation", "feedback", "explanation_round")
        value = {**{key: deepcopy(session.get(key)) for key in fields},
                 "time_candidates": deepcopy((session.get("result") or {}).get("time_candidates", [])), **overrides}
        if value.get("pending"):
            value["pending"] = {key: deepcopy(value["pending"][key]) for key in ("proposal_id", "revision", "content")}
        return value

    async def _save(self, original, actor, updated, *, explanation_token=None):
        return await run_in_threadpool(self.store.update_session, original["id"], actor, updated,
            expected_version=original["version"], explanation_token=explanation_token)

    def _merge(self, current, changes):
        if not changes or set(changes) - REQUEST_FIELDS:
            raise ValueError("수정할 일정 조건만 전달하세요.")
        # 수정 정책이 서버의 ID나 변경하지 않은 조건을 바꾸지 못하게 확인한다.
        expected = deepcopy(current)
        for key, value in changes.items():
            expected[key] = ({**expected[key], **value} if key == "preference" else deepcopy(value))
        expected["revision"] += 1
        actual = policies.merge_correction(deepcopy(current), deepcopy(changes))
        if actual != expected:
            raise ValueError("바꾸지 않은 조건과 요청 ID를 유지하고 수정 번호만 한 번 늘려야 합니다.")
        return ScheduleRequest.model_validate(actual).model_dump()

    async def _validate(self, request, result, snapshot):
        candidates = result.get("time_candidates", []) if request["intent"] == "time_only" else [result.get("proposal")]
        issues = [reason for proposal in candidates for reason in proposal_issues(request, proposal, snapshot)]
        if not candidates:
            issues.append("missing_proposal")
        if result.get("request") != request:
            issues.append("request_context")
        validator = getattr(self.engine, "validate_latest", None)
        if validator is not None:
            extra = validator(deepcopy(request), deepcopy(result))
            extra = await extra if inspect.isawaitable(extra) else extra
            issues.extend(extra)
        return issues

    async def _investigate(self, request, active_agent):
        # 단일 시간 서비스에서 이어 온 대화는 아직 인계하지 않았다. 실제 접수부터 시작한다.
        start_agent = "intake" if active_agent == "time" else active_agent
        result = await self.engine.investigate(deepcopy(request), active_agent=start_agent)
        # 실행 근거는 문의 상태에 저장한다. 임시 파일 경로를 원본 식별자로 쓰지 않는다.
        result = deepcopy(result)
        snapshot = await run_in_threadpool(self.store.snapshot_sources, request)
        result["source_contents"] = source_contents(snapshot, request)
        result["validation_issues"] = (await self._validate(request, result, snapshot)
                                       if result.get("status") in {"verified", "time_ready"} else [])
        if result["validation_issues"]:
            result["status"] = "needs_recheck"
            result["proposal"] = None
        return result

    @staticmethod
    def _with_result(session, request, result):
        updated = deepcopy(session)
        updated.update(request=request, draft={}, result=result,
                       active_agent=result.get("active_agent", "supervisor"), trace=result.get("trace", []),
                       reply=result.get("answer") or "조회 결과를 확인해주세요.", event=None,
                       explanation=None, previous_explanation=None, feedback=None, explanation_round=0)
        status = result.get("status", "needs_recheck")
        if status == "verified" and result.get("proposal"):
            updated["pending"] = {"proposal_id": str(uuid4()), "revision": request["revision"],
                                  "content": deepcopy(result["proposal"]),
                                  "source_contents": deepcopy(result["source_contents"])}
            updated["status"] = "awaiting_confirmation"
        else:
            updated["pending"] = None
            updated["status"] = status
        return updated

    async def message(self, identity, actor, message):
        session = await run_in_threadpool(self.store.get_session, identity, actor)
        current = session["request"] or session.get("draft") or None
        parsed = await self.engine.parse(message, deepcopy(current))
        if parsed["intent"] != "schedule":
            updated = {**session, "reply": parsed["reply"]}
            return self.public(await self._save(session, actor, updated))
        if session.get("request") and parsed.get("missing"):
            return self.public(await self._save(session, actor, {**session, "status": "needs_clarification", "pending": None, "reply": parsed["reply"]}))
        changes = parsed.get("changes", {})
        if not self.capabilities["rooms"] and changes.get("intent", "time_only") != "time_only":
            return self.public(await self._save(session, actor, {**session, "reply": "지금은 참석자의 공통 시간 조회를 도와드릴 수 있습니다. 회의실 조건은 아직 처리하지 않습니다."}))
        if session["request"]:
            request = self._merge(session["request"], changes) if changes else session["request"]
        else:
            draft = {"intent": "time_and_room" if self.capabilities["rooms"] else "time_only", **session.get("draft", {}), **changes}
            if "preference" in changes:
                draft["preference"] = {**session.get("draft", {}).get("preference", {}), **changes["preference"]}
            if parsed.get("missing"):
                updated = {**session, "draft": draft, "status": "needs_clarification", "reply": parsed["reply"]}
                return self.public(await self._save(session, actor, updated))
            request = new_request(draft, str(uuid4()))
        result = await self._investigate(request, session["active_agent"])
        updated = self._with_result(session, request, result)
        logger.info("schedule_id=%s stage=investigate status=%s revision=%s", request["request_id"], updated["status"], request["revision"])
        return self.public(await self._save(session, actor, updated))

    async def _explain(self, identity, actor, decision):
        session = await run_in_threadpool(self.store.get_session, identity, actor)
        self._assert_pending(session, decision)
        token = await run_in_threadpool(self.store.claim_explanation, identity, actor,
                                       expected_version=session["version"])
        try:
            pending, request, result = session["pending"], session["request"], session["result"]
            snapshot = await run_in_threadpool(self.store.snapshot_sources, request)
            changed = pending.get("source_contents") != source_contents(snapshot, request)
            issues = await self._validate(request, result, snapshot)
            if changed or issues:
                updated = {**session, "status": "needs_recheck", "pending": None,
                           "reply": "제안의 근거가 바뀌었습니다. 현재 조건으로 다시 조회한 뒤 설명을 요청해주세요."}
                return self.public(await self._save(session, actor, updated, explanation_token=token))
            if session.get("explanation_round", 0) >= 2:
                return self.public(await self._save(session, actor, {**session,
                    "reply": "이 제안의 첫 설명과 한 번의 보완을 마쳤습니다. 현재 설명을 확인하거나 조건을 바꿔 새 제안을 받아주세요."},
                    explanation_token=token))
            feedback = (decision.message or "이 시간과 회의실을 고른 이유를 설명해주세요.").strip()
            previous = session.get("explanation") or ""
            explanation = await self.engine.explain_proposal(deepcopy(request), deepcopy(result),
                previous_explanation=previous, feedback=feedback)
            # 모델 응답을 기다리는 동안 원천이 바뀌었을 수 있다. 생성과 채택은 별개다.
            after = await run_in_threadpool(self.store.snapshot_sources, request)
            changed_after = pending.get("source_contents") != source_contents(after, request)
            issues_after = await self._validate(request, result, after)
            if changed_after or issues_after:
                updated = {**session, "status": "needs_recheck", "pending": None,
                           "explanation": None, "previous_explanation": None, "feedback": feedback,
                           "explanation_round": session.get("explanation_round", 0) + 1,
                           "reply": "설명을 생성하는 동안 근거가 바뀌어 새 설명을 반영하지 않았습니다. 다시 조회한 뒤 제안을 확인해주세요."}
                return self.public(await self._save(session, actor, updated, explanation_token=token))
            updated = {**session, "previous_explanation": previous or None, "explanation": explanation,
                       "feedback": feedback, "explanation_round": session.get("explanation_round", 0) + 1,
                       "reply": "현재 검증한 근거로 설명을 준비했습니다. 내용이 충분한지 확인해주세요."}
            return self.public(await self._save(session, actor, updated, explanation_token=token))
        finally:
            await run_in_threadpool(self.store.release_explanation, identity, actor, token)

    async def decision(self, identity, actor, decision):
        session = await run_in_threadpool(self.store.get_session, identity, actor)
        action = decision.action
        if action == "explain":
            return await self._explain(identity, actor, decision)
        if action == "modify":
            if decision.message:
                return await self.message(identity, actor, decision.message)
            if not session["request"]:
                raise ValueError("먼저 조회할 일정을 알려주세요.")
            request = self._merge(session["request"], decision.changes or {})
            result = await self._investigate(request, session["active_agent"])
            return self.public(await self._save(session, actor, self._with_result(session, request, result)))
        if action == "cancel":
            self._assert_pending(session, decision)
            return self.public(await self._save(session, actor, {**session, "pending": None, "status": "cancelled", "reply": "제안을 취소했습니다. 예약은 저장하지 않았습니다."}))
        if action != "confirm":
            raise ValueError("confirm·cancel·modify·explain 중 하나를 선택하세요.")
        existing = await run_in_threadpool(self.store.get_event, decision.proposal_id, actor)
        if existing:
            if existing["session_id"] != identity or decision.revision != existing["revision"] or decision.content != existing["content"]:
                raise ConflictError("이미 저장한 제안의 내용과 다릅니다.")
            return self.public(session, status="saved", event=existing, reply="이미 확정한 동일한 예약입니다. 중복 저장하지 않았습니다.")
        self._assert_pending(session, decision)
        pending, request = session["pending"], session["request"]
        if request["intent"] == "time_only":
            raise ValueError("시간 후보 조회는 회의실 예약을 확정하지 않습니다.")
        snapshot = await run_in_threadpool(self.store.snapshot_sources, request)
        changed = pending.get("source_contents") != source_contents(snapshot, request)
        latest = (await self._investigate(request, session["active_agent"]) if changed else deepcopy(session["result"]))
        latest["source_contents"] = source_contents(snapshot, request)
        latest["validation_issues"] = await self._validate(request, latest, snapshot)
        latest["source_changed"] = changed
        latest["issues"] = deepcopy(latest["validation_issues"])
        choice = policies.confirmation_decision(deepcopy(pending), deepcopy(request), deepcopy(latest))
        if not isinstance(choice, dict) or choice.get("action") not in {"save", "recheck", "reject"} or not isinstance(choice.get("reason"), str):
            raise ValueError("확정 판단은 action과 reason을 돌려줘야 합니다.")
        # 정책이 save를 반환해도 현재 근거와 조건이 맞아야 저장한다.
        eligible = (not changed and not latest["validation_issues"] and latest.get("status") == "verified"
                    and latest.get("proposal") == pending["content"])
        if choice["action"] == "save" and eligible:
            updated = {**session, "status": "saved", "pending": None, "reply": "확인한 회의 제안을 예약으로 저장했습니다."}
            saved, event = await run_in_threadpool(self.store.confirm_event, identity, actor, pending, updated,
                expected_version=session["version"], source_contents=latest["source_contents"])
            logger.info("schedule_id=%s stage=confirm status=saved revision=%s", request["request_id"], request["revision"])
            return self.public(saved, event=event)
        updated = (self._with_result(session, request, latest) if changed and not latest["validation_issues"] else deepcopy(session))
        updated.update(status="needs_recheck" if changed or latest["validation_issues"] or choice["action"] == "recheck" else "rejected",
                       reply=("근거나 제안이 바뀌었습니다. 현재 제안을 다시 확인한 뒤 확정해주세요." if changed else choice["reason"]))
        if latest.get("status") in {"no_time", "no_room"}:
            updated.update(status=latest["status"], reply=("현재 근거에서 가능한 공통 시간이 없습니다." if latest["status"] == "no_time" else "현재 조건에 맞는 회의실이 없습니다."))
        if latest["validation_issues"]:
            updated["pending"] = None
        return self.public(await self._save(session, actor, updated))

    @staticmethod
    def _assert_pending(session, decision):
        pending = session.get("pending")
        if not pending or not decision.proposal_id or decision.proposal_id != pending["proposal_id"]:
            raise ConflictError("현재 확인 대기 중인 제안을 지정하세요.")
        if decision.revision != session["request"]["revision"] or decision.revision != pending["revision"]:
            raise ConflictError("수정 전 제안은 확정할 수 없습니다.")
        if decision.content != pending["content"]:
            raise ConflictError("화면에서 확인한 제안과 같은 내용으로 요청하세요.")
