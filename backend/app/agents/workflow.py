"""담당 조사 → 근거·제안 검증 → 채택·부분 갱신·중단의 흐름을 실행한다."""

from copy import deepcopy
from functools import partial

from . import runtime
from ..tools.room_client import lookup_rooms
from ..domain.scheduling import (choose_room, room_request_for,
    route_request, time_candidates, user_time_candidates, validate_request)
from ..tools.source_io import read_calendars
from ..domain.time_rules import utc_now
from .workers import run_worker, run_workers
from ..domain.verification import bound_receipt_issues, feedback_decision, proposal_issues, receipt_issues


def worker_jobs(request, store, refresh_sources, cycle, *, model=None, now=None):
    """이번에 필요한 담당 작업을 만든다. partial은 인수를 묶고 실제 호출은 실행기까지 미룬다."""
    calendars = {f"calendar:{p}" for p in request["participants"]} if request["intent"] != "room_only" else set()
    calendar_targets = [key for key in refresh_sources if key in calendars]
    jobs = {}
    if calendar_targets:
        jobs["time"] = partial(run_worker, "time", model, request,
                               partial(read_calendars, request, store, calendar_targets, cycle, now))
    if "rooms" in refresh_sources and request["intent"] != "time_only":
        jobs["room"] = partial(run_worker, "room", model, room_request_for(request),
                               partial(lookup_rooms, request, store, cycle, now))
    return calendar_targets, jobs


def received_workers(runs, role_events, calendar_targets, jobs, receipts, counters, agents, request, cycle, model):
    """두 실행 방식에서 받은 원본·오류·관측값을 동일한 형태로 통합한다."""
    errors, room_result = runtime.receive_results(runs, calendar_targets, receipts, counters, agents, request, cycle, model)
    return {"calendar_targets": calendar_targets, "role_events": role_events, "errors": errors,
            "room_result": room_result, "roles": list(jobs)}


async def collect_sequential(request, store, refresh_sources, receipts, counters, agents, cycle, *, model=None, now=None):
    """제공된 기본 실행: 같은 작업을 하나씩 기다린다. 병렬 연결을 완성하기 전에도 방 담당을 실행한다."""
    calendar_targets, jobs = worker_jobs(request, store, refresh_sources, cycle, model=model, now=now)
    runs, role_events = await run_workers(jobs, parallel=False)
    return received_workers(runs, role_events, calendar_targets, jobs, receipts, counters, agents, request, cycle, model)


async def collect_workers(request, store, refresh_sources, receipts, counters, agents, cycle, *, model=None, now=None):
    """TODO 2 · 필요한 담당 작업을 함께 실행하고 실제 결과를 누적 근거에 받는다.

    입력: 요청/이번 조회 출처/누적 근거와 관측값. 반환: 담당·이벤트·오류·방 응답.
    읽기: worker_jobs → run_workers → received_workers. 같은 작업의 실행과 수신 방식만 연결한다.
    jobs는 결과가 아니라 실행할 함수다. run_workers가 실제로 시작하고 모두 끝날 때까지 기다린다.
    """
    calendar_targets, jobs = worker_jobs(request, store, refresh_sources, cycle, model=model, now=now)
    runs, role_events = await run_workers(jobs)
    return received_workers(runs, role_events, calendar_targets, jobs, receipts, counters, agents, request, cycle, model)


async def run_collaboration(request, store, *, model=None, max_refreshes=2, now=None, parallel=True):
    """같은 문의 안의 유효 근거를 유지한다. 이전 응답에 새 요청의 식별자를 덮어쓰지 않는다."""
    request = validate_request(request)
    if type(max_refreshes) is not int or max_refreshes < 0:
        raise ValueError("재조회 한도는 0 이상의 정수입니다.")
    utc_now(now)
    route = route_request(request)
    calendars = [f"calendar:{p}" for p in request["participants"]] if route["intent"] != "room_only" else []
    required = calendars + (["rooms"] if route["intent"] != "time_only" else [])
    receipts, rounds, agents, visited = {}, [], [], ["Router"]
    refresh_sources, candidates = list(required), None
    counters = {"calendar_reads": 0, "source_reads": {}, "time_agent_calls": 0, "time_tool_calls": 0,
                "room_agent_calls": 0, "room_tool_calls": 0, "mcp_calls": 0, "room_lookups": 0, "refreshes": 0}
    for cycle in range(max_refreshes + 1):
        before, manifest_before = deepcopy(receipts), store.manifest()
        previous_decision = rounds[-1]["decision"] if rounds else {}
        invalidated = previous_decision.get("invalidated", [])
        collector = collect_workers if parallel else collect_sequential
        received = await collector(request, store, refresh_sources, receipts, counters, agents, cycle, model=model, now=now)
        calendar_targets, role_events = received["calendar_targets"], received["role_events"]
        errors, room_result = received["errors"], received["room_result"]
        visited += [("담당 병렬 조사" if parallel else "담당 순차 조사") if len(received["roles"]) > 1 else "필요 담당 갱신"]
        # 근거를 먼저 검사하고, 영향을 받은 계산만 다시 수행한다.
        preissues = [issue for key in required for issue in bound_receipt_issues(key,
            receipts.get(key, runtime.missing_receipt(key, request, cycle, "미수신")), request, manifest_before, now)]
        recomputed, proposal, terminal = [], None, "lookup_unavailable"
        if not preissues:
            # 캘린더를 다시 읽으면 공통 후보를 재계산하고, 방만 바뀌면 후보를 유지한다.
            if candidates is None or calendar_targets:
                candidates = user_time_candidates(request) if route["intent"] == "room_only" else time_candidates(request, receipts)
                recomputed.append("time_candidates")
            if not candidates:
                terminal = "no_time"
            elif route["intent"] == "time_only":
                terminal = "time_ready"
            else:
                proposal = choose_room(request, candidates, receipts["rooms"]["records"])
                terminal = "verified" if proposal else "no_room"
                recomputed.append("proposal")
        visited += ["결과 통합"]
        # 채택 직전 실제 제공 원천의 현재 내용을 다시 확인한다.
        await store.advance(request, cycle)
        manifest_after = store.manifest()
        issues = [issue for key in required for issue in bound_receipt_issues(key,
            receipts.get(key, runtime.missing_receipt(key, request, cycle, "미수신")), request, manifest_after, now)]
        proposal_errors = proposal_issues(proposal, request, receipts) if proposal is not None and not issues else []
        if route["intent"] == "time_only" and candidates and not issues:
            proposal_errors = [reason for slot in candidates for reason in proposal_issues(slot, request, receipts)]
        decision = feedback_decision(issues, proposal_errors, terminal, cycle, max_refreshes)
        rounds.append({"cycle": cycle, "before": before, "after": deepcopy(receipts),
            "manifest_before": manifest_before, "manifest_after": manifest_after, "time_candidates": deepcopy(candidates),
            "handoff": room_request_for(request) if route["intent"] != "time_only" else None,
            "observed_proposal": deepcopy(proposal), "receipt_issues": issues, "proposal_issues": proposal_errors,
            "decision": decision, "refresh_sources": list(refresh_sources), "invalidated": invalidated,
            "recomputed": recomputed, "retained_sources": sorted(set(before)-set(refresh_sources)),
            "role_events": role_events, "execution": "parallel" if parallel else "sequential",
            "errors": errors, "room_result": deepcopy(room_result)})
        visited += ["근거 검증", "피드백 판단"]
        if decision["action"] != "refresh":
            return {"status": decision["status"], "proposal": proposal if decision["status"] == "verified" else None,
                "request": request, "mode": "direct_tools" if model is None else "agents", "receipts": receipts,
                "rounds": rounds, "counters": counters, "agents": agents, "source_snapshot": store.snapshot(),
                "route": route, "time_basis": route["time_basis"], "calendar_checked": bool(calendars) and
                all(receipts.get(key, {}).get("status") in ("ok", "empty") for key in calendars),
                "time_candidates": candidates, "visited": visited}
        # 결정한 출처만 다음 회차의 담당 선택과 실제 조회에 전달한다.
        refresh_sources = decision["sources"]
        counters["refreshes"] += 1
    raise AssertionError("갱신 한도에서 반드시 종료합니다.")
