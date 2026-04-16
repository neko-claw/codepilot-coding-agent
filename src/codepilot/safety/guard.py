"""Safety guard rules for risky operations."""

from dataclasses import dataclass

HIGH_RISK_KEYWORDS = (
    "rm -rf",
    "drop database",
    "delete",
    "truncate",
    "force push",
    "删除",
    "删库",
)
MEDIUM_RISK_KEYWORDS = ("migrate", "overwrite", "reset", "reinstall", "重置", "覆盖")
KEYWORD_ALIASES = {"删除": "delete", "删库": "drop database", "重置": "reset", "覆盖": "overwrite"}


@dataclass(slots=True)
class RiskAssessment:
    """Risk evaluation result for a planned operation."""

    level: str
    requires_confirmation: bool
    reason: str


def evaluate_operation_risk(plan_text: str) -> RiskAssessment:
    """Return a coarse-grained risk assessment based on dangerous keywords."""
    lowered = plan_text.strip().lower()
    if not lowered:
        return RiskAssessment("medium", True, "空计划默认需要人工确认")

    for keyword in HIGH_RISK_KEYWORDS:
        if keyword in lowered:
            display_keyword = KEYWORD_ALIASES.get(keyword, keyword)
            return RiskAssessment("high", True, f"检测到高风险关键词: {display_keyword}")

    for keyword in MEDIUM_RISK_KEYWORDS:
        if keyword in lowered:
            display_keyword = KEYWORD_ALIASES.get(keyword, keyword)
            return RiskAssessment("medium", True, f"检测到中风险关键词: {display_keyword}")

    return RiskAssessment("low", False, "未检测到显著风险关键词")
