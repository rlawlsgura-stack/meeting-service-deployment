"""단계별 입력과 짧은 표시, 담당 결과의 세부 기록을 제공한다. 실행 기록 파일은 만들지 않는다."""



def missing_receipt(source_id, request, cycle, error):
    return {"source_id": source_id, "origin": None,
            "request_id": request["request_id"], "revision": request["revision"], "collection_cycle": cycle,
            "scope": None, "meeting_date": request["meeting_date"], "timezone": request["timezone"],
            "observed_at": None, "status": "error", "records": [], "error": error}


def receive_results(runs, calendar_targets, receipts, counters, agents, request, cycle, model):
    """담당별 실제 원본·오류·메시지·호출 수를 결과 객체에 연결한다."""
    errors, room_result = [], None
    for role, run in runs.items():
        agents.append({"cycle": cycle, **run})
        counters[f"{role}_agent_calls"] += int(model is not None)
        counters[f"{role}_tool_calls"] += run["tool_calls"]
        if run["error"]:
            errors.append(run["error"])
        if role == "time":
            readings = run["result"]
            if readings is None:
                readings = [missing_receipt(key, request, cycle, run["error"] or "시간 도구 결과 미수신") for key in calendar_targets]
            else:
                counters["calendar_reads"] += len(readings)
                for key in calendar_targets:
                    counters["source_reads"][key] = counters["source_reads"].get(key, 0)+1
            for key, receipt in zip(calendar_targets, readings):
                receipts[key] = receipt
        else:
            room_result = run["result"]
            receipts["rooms"] = (room_result["receipt"] if room_result else None) or missing_receipt(
                "rooms", request, cycle, run["error"] or "회의실 원본 미수신")
            if room_result:
                counters["mcp_calls"] += int(room_result["mcp"]["call_attempted"])
                count = room_result["room_lookups"]
                counters["room_lookups"] = None if count is None or counters["room_lookups"] is None else counters["room_lookups"]+count
                if count:
                    counters["source_reads"]["rooms"] = counters["source_reads"].get("rooms", 0)+count
                if room_result["error"]:
                    errors.append(room_result["error"])
    # 원본의 수신 오류도 보존하고 정상 빈 결과로 바꾸지 않는다.
    errors += [{"source_id": key, "error": receipt["error"]} for key, receipt in receipts.items() if receipt.get("error")]
    return errors, room_result


def investigation_trace(request, result):
    """원래 실행 이벤트만 화면 관측값으로 옮긴다. 순차·병렬·중앙 조정이 이 투영을 공유한다."""
    trace = []
    for row in result["rounds"]:
        trace += [{"stage": "workers", "role": event["role"], "status": event["phase"],
                   "cycle": row["cycle"], "at_ms": round(event["at_ms"], 1),
                   "tool": "find_times" if event["role"] == "time" else "find_rooms",
                   "sources": [key for key in row["refresh_sources"]
                               if key.startswith("calendar:") == (event["role"] == "time")],
                   "scope": {key: request[key] for key in ("meeting_date", "window_start", "window_end")}}
                  for event in row["role_events"]]
        room = row.get("room_result")
        if room and room.get("mcp"):
            mcp = room["mcp"]
            trace.append({"stage": "mcp", "role": "room", "tool": "find_rooms", "cycle": row["cycle"],
                          "status": "completed" if mcp["call_attempted"] and not mcp["is_error"] and not room.get("error") else "error",
                          "transport": mcp["transport"], "connected": mcp["connected"],
                          "server_pid": room.get("server_pid"),
                          "request_fields": sorted(row["handoff"] or {})})
        trace.append({"stage": "verification", "role": "policy", "status": row["decision"]["action"],
                      "cycle": row["cycle"], "sources": row["decision"]["sources"],
                      "reason": row["decision"]["reason"], "issues": row["receipt_issues"],
                      "invalidated": row["invalidated"], "recomputed": row["recomputed"],
                      "retained_sources": row["retained_sources"]})
    return trace
