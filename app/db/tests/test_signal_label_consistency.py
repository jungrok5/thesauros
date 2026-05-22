"""Signal label spelling consistency guard (회고 #55).

ALERT_RULES (telegram_worker.py) 의 prefix 와 _SIGNAL_LABELS 의 key 가
일관해야 한다. spelling drift 가 발생하면:
  - ALERT_RULES 에 `pattern_cup_and_handle` 있는데 _SIGNAL_LABELS 에
    `pattern_cup_with_handle` 만 있으면 → classify() 가 enter/pyramid
    분류는 OK 하나 메시지 label 은 fallback ("Unknown") 으로 빠짐.

이 테스트는 두 list 가 sync 인지 정적으로 검사.
"""
from __future__ import annotations

from app.db.telegram_worker import ALERT_RULES, _SIGNAL_LABELS


def test_alert_rules_prefixes_have_matching_labels():
    """ALERT_RULES 의 prefix 가 _SIGNAL_LABELS 에 정확히 또는 prefix
    매치로 존재. 예: `pattern_double_bottom` → _SIGNAL_LABELS 에 그 키
    있어야 함. exact 일치 우선, 아니면 prefix 로 시작하는 키 검색."""
    missing: list[str] = []
    for prefix, _atype, _sev in ALERT_RULES:
        # _signal_label() 의 lookup 패턴 — exact 또는 prefix.
        exact = prefix in _SIGNAL_LABELS
        prefix_hit = any(
            k == prefix or k.startswith(prefix + "_")
            for k in _SIGNAL_LABELS
        )
        if not (exact or prefix_hit):
            missing.append(prefix)
    assert not missing, (
        f"ALERT_RULES 의 다음 prefix 가 _SIGNAL_LABELS 와 매치 안 됨: "
        f"{missing}. spelling drift 일 가능성 — telegram alert 가 한글 "
        "label 없이 raw snake_case 로 나감."
    )


def test_signal_labels_all_have_required_fields():
    """_SIGNAL_LABELS 의 각 entry 는 name / dir / phrase 모두 가짐.
    한 곳 누락되면 format_message 가 KeyError 또는 None 출력."""
    for key, entry in _SIGNAL_LABELS.items():
        assert "name" in entry, f"{key} missing 'name'"
        assert "dir" in entry, f"{key} missing 'dir'"
        assert "phrase" in entry, f"{key} missing 'phrase'"
        assert entry["dir"] in ("bull", "bear", "neutral"), (
            f"{key}.dir invalid: {entry['dir']!r}"
        )


def test_no_snake_case_labels_leak_to_users():
    """name / phrase 값에 snake_case 토큰이 leak 됐는지 검사 — 사용자
    노출 시 책 정신 위배 (한글 라벨 원칙). 모두 한글 또는 영어 단어로
    풀어 써야 함."""
    import re
    snake_case_re = re.compile(r"\b[a-z]+_[a-z_]+\b")
    leaks: list[str] = []
    for key, entry in _SIGNAL_LABELS.items():
        for field in ("name", "phrase"):
            if snake_case_re.search(entry[field]):
                leaks.append(f"{key}.{field} = {entry[field]!r}")
    assert not leaks, (
        f"snake_case 토큰이 user-facing label 에 leak: {leaks}"
    )
