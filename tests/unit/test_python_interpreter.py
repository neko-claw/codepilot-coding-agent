from codepilot.executor.interpreter import execute_python


def test_execute_python_returns_stdout() -> None:
    result = execute_python("print('hello sprint1')")

    assert result.success is True
    assert result.stdout.strip() == "hello sprint1"
    assert result.stderr == ""


def test_execute_python_reports_timeout() -> None:
    result = execute_python("import time; time.sleep(2)", timeout=0.1)

    assert result.success is False
    assert result.timed_out is True
    assert "timed out" in result.stderr.lower()
