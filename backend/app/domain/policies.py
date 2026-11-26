"""조건 수정과 명시적 확정의 업무 판단. HTTP·DB·모델을 호출하지 않는다."""

from copy import deepcopy


def merge_correction(current_request, changes):
    """바뀐 조건만 반영하고 나머지를 유지한 새 수정본을 만든다."""
    revised = deepcopy(current_request)
    for key, value in changes.items():
        if key not in {"request_id", "revision"}:
            if key == "preference":
                revised[key] = {**revised.get(key, {}), **value}
            else:
                revised[key] = deepcopy(value)
    revised["revision"] = current_request["revision"] + 1
    return revised


def confirmation_decision(pending, current_request, latest_result):
    """TODO 4 · 현재 제안의 등록/재확인/거절을 업무 규칙으로 구별한다.

    입력: 확인 대기 제안/현재 문의/최신 검증 결과. 반환: action과 reason.
    읽기: 서비스 decision의 latest 구성 → 이 함수 → 서비스 eligible/DB 독립 검사.
    """
    if pending["revision"] != current_request["revision"]:
        return {"action": "reject", "reason": "제안과 현재 요청의 수정본이 다릅니다."}
    if latest_result.get("source_changed"):
        return {"action": "recheck", "reason": "제안 이후 근거가 바뀌어 다시 확인해야 합니다."}
    if latest_result.get("validation_issues"):
        return {"action": "recheck", "reason": "원본이나 제안이 달라져 다시 확인해야 합니다."}
    if latest_result.get("status") != "verified" or not latest_result.get("proposal"):
        return {"action": "reject", "reason": "확정할 수 있는 회의 제안이 없습니다."}
    if latest_result["proposal"] != pending["content"]:
        return {"action": "recheck", "reason": "현재 조건에서 제안이 바뀌었습니다."}
    return {"action": "save", "reason": "현재 요청과 원본으로 확인한 제안입니다."}
