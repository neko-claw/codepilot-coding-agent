# Sprint 1 Implementation Plan

> **For Hermes:** Implement this sprint in strict TDD order. Write failing tests first, run them to confirm failure, then add the minimal code to pass.

**Goal:** Deliver the first usable Coding Agent iteration: plan-mode interaction, repository search/reading, safe file editing with diff + syntax checks, shell execution, and Python code interpretation.

**Architecture:** Extend the current lightweight prototype into a minimal but coherent agent core. Keep interfaces small and deterministic so they are easy to test. Prefer plain dataclasses and stdlib over premature abstractions.

**Tech Stack:** Python 3.11, pathlib, subprocess, difflib, re, glob, py_compile, pytest, pytest-cov.

---

## Scope for Sprint 1
This sprint implements the Iteration 1 backbone from the project docs:
1. richer Plan mode output structure
2. glob / grep repository search
3. line-numbered file reading with ranged reads
4. old-string-to-new-string editing with diff and syntax validation
5. controlled shell command execution with output truncation
6. minimal Python code interpreter with timeout and output capture

---

## Task 1: Expand Plan mode response
**Objective:** Make the planner return actionable plan data instead of only a summary string.

**Files:**
- Modify: `src/codepilot/planner/workflow.py`
- Test: `tests/unit/test_plan_execute.py`

**Expected behaviors:**
- include plan steps
- include candidate files
- include candidate commands
- include risk assessment
- include discussion actions for plan mode

## Task 2: Add repository search tools
**Objective:** Support file discovery and content search for Sprint 1 exploration workflows.

**Files:**
- Create: `src/codepilot/tools/search.py`
- Modify: `src/codepilot/tools/__init__.py`
- Test: `tests/unit/test_search_tools.py`

**Expected behaviors:**
- glob search under a root directory
- grep search with file filtering
- stable, sorted results
- bounded result counts

## Task 3: Add line-numbered file reading
**Objective:** Read full or partial file content with original line numbers preserved.

**Files:**
- Create: `src/codepilot/tools/filesystem.py`
- Modify: `src/codepilot/tools/__init__.py`
- Test: `tests/unit/test_filesystem_tools.py`

**Expected behaviors:**
- read full file with `LINE|content` format
- read line ranges only
- report total lines
- reject invalid ranges

## Task 4: Add safe file editing with diff and syntax checks
**Objective:** Implement old-string-to-new-string replacement with deterministic failure modes.

**Files:**
- Modify: `src/codepilot/tools/filesystem.py`
- Test: `tests/unit/test_filesystem_tools.py`

**Expected behaviors:**
- replace exactly one match by default
- fail on missing match
- fail on ambiguous match unless replace_all requested
- return unified diff
- run Python syntax validation when editing `.py` files

## Task 5: Add command execution module
**Objective:** Execute shell commands in a controlled, stateful session.

**Files:**
- Create: `src/codepilot/executor/shell.py`
- Modify: `src/codepilot/executor/__init__.py`
- Test: `tests/unit/test_shell_executor.py`

**Expected behaviors:**
- persistent working directory and environment support
- timeout handling
- exit code capture
- stdout/stderr capture
- head/tail output truncation with notice

## Task 6: Add Python code interpreter
**Objective:** Execute small Python snippets safely with timeout and truncated output.

**Files:**
- Create: `src/codepilot/executor/interpreter.py`
- Modify: `src/codepilot/executor/__init__.py`
- Test: `tests/unit/test_python_interpreter.py`

**Expected behaviors:**
- execute Python code in subprocess
- respect timeout
- capture stdout/stderr
- report success/failure cleanly

## Task 7: Export the new Sprint 1 interfaces
**Objective:** Make the package surface the new Sprint 1 modules cleanly.

**Files:**
- Modify: `src/codepilot/__init__.py`
- Test: use existing and new tests

## Task 8: Sync docs after implementation
**Objective:** Keep docs aligned with the implemented Sprint 1 surface.

**Files:**
- Modify as needed: `README.md`, `docs/03-iteration-plan.md`, `docs/04-testing-strategy.md`

## Verification commands
```bash
ruff check .
pylint src/codepilot
pytest --cov=src/codepilot --cov-report=term-missing
```
