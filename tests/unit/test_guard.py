from codepilot.safety.guard import evaluate_operation_risk


def test_evaluate_operation_risk_high() -> None:
    result = evaluate_operation_risk("Please rm -rf /tmp/demo")
    assert result.level == "high"
    assert result.requires_confirmation is True
    assert "高风险关键词" in result.reason


def test_evaluate_operation_risk_medium() -> None:
    result = evaluate_operation_risk("overwrite config and migrate db")
    assert result.level == "medium"
    assert result.requires_confirmation is True


def test_evaluate_operation_risk_low() -> None:
    result = evaluate_operation_risk("update tests and docs")
    assert result.level == "low"
    assert result.requires_confirmation is False


def test_evaluate_operation_risk_empty_plan() -> None:
    result = evaluate_operation_risk("   ")
    assert result.level == "medium"
    assert result.requires_confirmation is True
