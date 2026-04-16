from pathlib import Path

import pytest

from codepilot.tools.filesystem import edit_file_by_replacement, read_file_with_line_numbers


def test_read_file_with_line_numbers_returns_all_lines(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = read_file_with_line_numbers(target)

    assert result.total_lines == 3
    assert result.content == ["1|alpha", "2|beta", "3|gamma"]


def test_read_file_with_line_numbers_supports_ranges(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    result = read_file_with_line_numbers(target, start_line=2, end_line=3)

    assert result.total_lines == 4
    assert result.content == ["2|beta", "3|gamma"]


def test_read_file_with_line_numbers_rejects_invalid_range(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("alpha\n", encoding="utf-8")

    with pytest.raises(ValueError, match="start_line"):
        read_file_with_line_numbers(target, start_line=3, end_line=1)


def test_edit_file_by_replacement_returns_diff_and_updates_file(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    result = edit_file_by_replacement(target, "hello", "world")

    assert result.updated_text == "print('world')\n"
    assert any("-print('hello')" in line for line in result.diff)
    assert any("+print('world')" in line for line in result.diff)
    assert result.syntax_check == "ok"
    assert target.read_text(encoding="utf-8") == "print('world')\n"


def test_edit_file_by_replacement_fails_when_old_text_missing(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("print('hello')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not found"):
        edit_file_by_replacement(target, "missing", "world")


def test_edit_file_by_replacement_fails_when_match_is_ambiguous(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("token\ntoken\n", encoding="utf-8")

    with pytest.raises(ValueError, match="multiple times"):
        edit_file_by_replacement(target, "token", "value")


def test_edit_file_by_replacement_reports_python_syntax_errors(tmp_path: Path) -> None:
    target = tmp_path / "broken.py"
    target.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    result = edit_file_by_replacement(target, "return 'hi'", "return (")

    assert result.syntax_check.startswith("error:")
