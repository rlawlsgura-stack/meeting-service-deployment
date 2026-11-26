"""근거 사용 여부·제안 조건·부분 갱신 정책. 이전에 확인한 판단을 그대로 재사용한다."""

from .conditions import receipt_facts, proposal_facts


def receipt_issues(receipt, request, manifest, now=None):
    """현재 문의·원천과 맞지 않는 근거의 사유를 반환한다."""
    facts = receipt_facts(receipt, request, manifest, now)
    return [{"source_id": receipt.get("source_id"), "reason": reason}
            for reason, passed in facts.items() if not passed]


def proposal_issues(proposal, request, receipts):
    """제안에서 원본으로 확인되지 않은 조건을 반환한다. 준비할 실제 구간도 검사한다."""
    facts = proposal_facts(proposal, request, receipts)
    return [reason for reason, passed in facts.items() if not passed]


def feedback_decision(issues, proposal_errors, terminal_status, refreshes, max_refreshes):
    """실패 사유와 한도로 채택·선택 갱신·중단을 정한다. 재조회 대상과 재계산 대상을 구별한다."""
    if proposal_errors:
        return {"action": "stop", "status": "invalid", "reason": "원본과 맞지 않는 제안", "sources": [], "invalidated": ["proposal"]}
    if not issues:
        return {"action": "accept", "status": terminal_status, "reason": "현재 문의와 원본으로 확인", "sources": [], "invalidated": []}
    if any(not isinstance(row.get("source_id"), str) or not row["source_id"] for row in issues):
        return {"action": "stop", "status": "invalid", "reason": "갱신할 원천을 식별할 수 없음", "sources": [], "invalidated": ["proposal"]}
    if refreshes >= max_refreshes:
        status = "lookup_unavailable" if any(row["reason"] == "lookup_error" for row in issues) else "stopped"
        return {"action": "stop", "status": status, "reason": "재조회 한도 소진", "sources": [], "invalidated": ["proposal"]}
    sources = sorted({row["source_id"] for row in issues})
    invalidated = (["time_candidates", "proposal"]
                   if any(source.startswith("calendar:") for source in sources) else ["proposal"])
    return {"action": "refresh", "status": None, "reason": "맞지 않는 원천만 갱신", "sources": sources, "invalidated": invalidated}


def bound_receipt_issues(source_id, receipt, request, manifest, now=None):
    """갱신 대상은 호출자가 요청한 원천이다. 손상된 영수증의 source_id를 실행에 쓰지 않는다."""
    issues = receipt_issues(receipt, request, manifest, now)
    if receipt.get("source_id") != source_id:
        issues.append({"reason": "source_identity"})
    return [{**issue, "source_id": source_id, "reported_source_id": receipt.get("source_id")} for issue in issues]
