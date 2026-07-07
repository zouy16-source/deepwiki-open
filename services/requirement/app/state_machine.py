"""需求全生命周期状态机（admin.md FR-REQ-02）。

表驱动：状态与动作的合法组合唯一确定下一状态；
每次流转必须写 FlowEvent 留痕，并可绑定 AI 产物（artifact_type/artifact_ref）。
"""

STATUSES = {
    "draft": "草稿",
    "pending_analysis": "待分析",
    "analyzed": "分析完成",
    "in_review": "评审中",
    "scheduled": "已排期",
    "in_dev": "开发中",
    "in_test": "测试中",
    "pending_acceptance": "待验收",
    "released": "已上线",
    "closed": "已关闭",
    "rejected": "已打回",
}

# (当前状态, 动作) -> 下一状态
TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "submit"): "pending_analysis",
    ("pending_analysis", "analysis_done"): "analyzed",
    ("analyzed", "reanalyze"): "pending_analysis",
    ("analyzed", "start_review"): "in_review",
    ("in_review", "approve"): "scheduled",
    ("in_review", "reject"): "rejected",
    ("rejected", "resubmit"): "pending_analysis",
    ("rejected", "close"): "closed",
    ("scheduled", "start_dev"): "in_dev",
    ("in_dev", "submit_test"): "in_test",
    ("in_test", "test_passed"): "pending_acceptance",
    ("in_test", "test_failed"): "in_dev",
    ("pending_acceptance", "accept"): "released",
    ("pending_acceptance", "acceptance_failed"): "in_test",
    ("released", "close"): "closed",
}


class InvalidTransition(Exception):
    def __init__(self, current: str, action: str):
        self.current = current
        self.action = action
        allowed = sorted(a for (s, a) in TRANSITIONS if s == current)
        super().__init__(
            f"action '{action}' not allowed in status '{current}'; allowed: {allowed}"
        )


def next_status(current: str, action: str) -> str:
    key = (current, action)
    if key not in TRANSITIONS:
        raise InvalidTransition(current, action)
    return TRANSITIONS[key]
