# CodePilot：从零实现的智能 Coding Agent 开发平台

## 1. 项目概述
CodePilot 是一个面向开发任务执行的智能编程代理原型系统。它聚焦于“需求输入 → 仓库理解 → 任务规划 → 代码修改 → 命令执行 → 结果验证 → 风险控制”的闭环，目标是在课程实验场景下构建一个可运行、可演示、可验证的 Coding Agent。

本仓库当前提供：
- Lab2 报告可直接复用的开发文档与技术路线
- 两轮迭代计划与人员分工建议
- Pylint / Ruff / Pytest / Coverage 的测试思路与落地配置
- 黑盒测试、等价类、边界值、白盒测试与覆盖度说明
- Plan-Execute 流程骨架与工具能力抽象
- GitHub API 仓库上下文接入与本地运行时会话封装
- DeepSeek API 规划接入、CLI 入口、历史记录、日志与回退能力
- 一个最小 Python 原型，用于支撑后续开发、真实 API 调用与测试演示

## 2. Coding Agent 的核心能力要求
本项目将真正的 Coding Agent 定义为“具备工具执行闭环的系统”，而不是只会给建议的聊天模型。因此技术路线明确要求以下 7 项能力：
1. Code Interpreter（隔离执行 Python 代码）
2. Bash Shell（执行测试、构建、命令处理）
3. 读文件工具
4. 写文件工具
5. 编辑文件工具
6. Glob 文件名搜索
7. Grep 文件内容搜索

同时，系统主流程采用 **Plan-Execute** 模式：
- **Plan**：先输出执行计划、目标文件、待执行命令和风险提示
- **Execute**：得到用户确认后再真正执行

代码实现与测试遵循 **TDD 原则**：先写失败测试，再写最小实现，再同步更新文档。

## 3. 仓库结构
```text
codepilot-coding-agent/
├── docs/
│   ├── 01-project-development.md
│   ├── 02-technical-route.md
│   ├── 03-iteration-plan.md
│   ├── 04-testing-strategy.md
│   └── 05-development-playbook.md
├── src/codepilot/
│   ├── core/models.py
│   ├── planner/workflow.py
│   ├── safety/guard.py
│   └── tools/capabilities.py
├── tests/
│   ├── blackbox/
│   ├── unit/
│   └── whitebox/
├── pyproject.toml
└── README.md
```

## 4. 当前技术栈选择
- 语言：Python 3.11+
- 代码风格检查：Ruff
- 静态质量分析：Pylint
- 单元测试：Pytest
- 覆盖率：pytest-cov
- 主流程控制：Plan-Execute
- 开发方法：TDD

## 5. 核心模块规划
1. 任务交互模块
2. 仓库理解模块
3. 任务规划模块
4. 工具能力模块
5. 代码编辑模块
6. 命令执行模块
7. 验证与回退模块
8. 会话记忆与历史模块

## 6. 快速开始
### 创建虚拟环境
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
cp .env.example .env
# 然后在 .env 中填入 DEEPSEEK_API_KEY
```

### 运行检查
```bash
ruff check .
pylint src/codepilot
pytest --cov=src/codepilot --cov-report=term-missing
```

### CLI 运行示例
```bash
codepilot run --workdir /path/to/repo --mode plan "为当前仓库生成 Sprint 2 开发计划"
codepilot run --workdir /path/to/repo --mode auto "验证当前仓库测试是否通过"
codepilot history --workdir /path/to/repo
codepilot restore <snapshot_id> --workdir /path/to/repo
```

## 7. 文档索引
- 项目开发文档：`docs/01-project-development.md`
- 技术路线选择：`docs/02-technical-route.md`
- 两轮迭代计划：`docs/03-iteration-plan.md`
- 测试方案与覆盖度：`docs/04-testing-strategy.md`
- 开发实施手册：`docs/05-development-playbook.md`

## 8. 当前代码骨架说明
当前仓库已经包含以下可验证骨架：
- 输入校验：`validate_task_request()`
- 风险识别：`evaluate_operation_risk()`
- Plan/Execute 控制：`PlanExecutionController`
- 工具能力集合：`default_capability_set()`
- GitHub 仓库 API 接入：`GitHubRepoClient`
- DeepSeek 规划接入：`DeepSeekPlannerClient`
- 本地运行时会话：`run_task_session()`
- 历史记录与日志：`SessionStore`
- 工作区回退快照：`WorkspaceSnapshotManager`

这些代码并非完整 Agent，但已经把技术路线中的关键约束固化为可测试对象，便于后续继续扩展。

## 9. 真实运行示例
```bash
cd /home/hermes/codepilot-coding-agent
source .venv/bin/activate
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from codepilot.runtime.session import run_task_session

result = run_task_session(
    description='审查当前 CodePilot 仓库的测试质量门禁并验证关键命令是否通过',
    workdir=Path('/home/hermes/codepilot-coding-agent'),
    mode='auto',
)

print(result.plan.status)
print(result.github_snapshot.full_name if result.github_snapshot else 'no-github')
for item in result.command_results:
    print(item.command, item.exit_code)
PY
```

该示例会：
- 读取本地仓库上下文
- 从 GitHub API 拉取远程仓库摘要与 README 片段
- 在 `auto` 模式下执行候选命令（默认 `pytest -q`、`ruff check .`）
- 返回计划状态、远程上下文与命令结果

## 10. 说明
本仓库优先服务于课程实验交付，因此文档组织按“可提交、可实现、可验证”原则编排。后续若继续开发，可在此基础上扩展沙盒执行器、文件编辑器、命令调度器与 Web 原型界面。与此同时，所有新增功能都应继续遵循 Plan-Execute 与 TDD 两项基本原则。 