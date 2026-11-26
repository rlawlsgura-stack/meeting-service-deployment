"""사용자가 따로 말하지 않은 기본 추천 정책. 명시한 사용자 선호는 항상 우선한다."""

DEFAULT_PREFERENCE = {"prefer_early": True, "allow_later_for_less_setup": True}


def default_preference():
    return dict(DEFAULT_PREFERENCE)
