from pathlib import Path

from codepilot.tools.search import glob_search, grep_search


def test_glob_search_finds_matching_files(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (src_dir / "util.py").write_text("pass\n", encoding="utf-8")
    (src_dir / "README.md").write_text("docs\n", encoding="utf-8")

    result = glob_search(tmp_path, "src/*.py")

    assert result == [str(src_dir / "app.py"), str(src_dir / "util.py")]


def test_grep_search_returns_matching_lines_with_line_numbers(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("def create_user():\n    return True\n", encoding="utf-8")

    result = grep_search(tmp_path, r"create_user", file_glob="*.py")

    assert result == [{"path": str(target), "line": 1, "content": "def create_user():"}]


def test_grep_search_honors_result_limit(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("token\ntoken\ntoken\n", encoding="utf-8")

    result = grep_search(tmp_path, r"token", file_glob="*.py", limit=2)

    assert len(result) == 2
