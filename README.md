# CodePilot：从零实现的智能 Coding Agent 开发平台

## 1. 项目概述
CodePilot 是一个面向开发任务执行的智能编程代理原型系统。它聚焦于“需求输入 → 仓库理解 → 任务规划 → 代码修改 → 命令执行 → 结果验证 → 风险控制”的闭环，目标是在课程实验场景下构建一个可运行、可演示、可验证的 Coding Agent。

本仓库当前提供：
- Lab2 报告可直接复用的开发文档与技术路线
- 两轮迭代计划与人员分工建议
- Pylint / Ruff / Pytest / Coverage 的测试思路与落地配置
- 黑盒测试、等价类、边界值、白盒测试与覆盖度说明
- 一个最小 Python 原型骨架，用于支撑后续开发与测试演示

## 2. 仓库结构
```text
codepilot-coding-agent/
├── docs/
│   ├── 01-project-development.md
│   ├── 02-technical-route.md
│   ├── 03-iteration-plan.md
│   └── 04-testing-strategy.md
├── src/codepilot/
│   ├── core/models.py
│   └── safety/guard.py
├── tests/
│   ├── blackbox/
│   ├── unit/
│   └── whitebox/
├── pyproject.toml
└── README.md
```

## 3. 当前技术栈选择
- 语言：Python 3.11+
- 代码风格检查：Ruff
- 静态质量分析：Pylint
- 单元测试：Pytest
- 覆盖率：pytest-cov
- 原型界面：后续可扩展为 Web（React/Next.js）或桌面端（Tauri/Electron）

## 4. 核心模块规划
1. 任务交互模块
2. 仓库理解模块
3. 任务规划模块
4. 代码编辑模块
5. 命令执行模块
6. 验证与回退模块
7. 会话记忆与历史模块

## 5. 快速开始
### 创建虚拟环境
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .[dev]
```

### 运行检查
```bash
ruff check .
pylint src/codepilot
pytest --cov=src/codepilot --cov-report=term-missing
```

## 6. 文档索引
- 项目开发文档：`docs/01-project-development.md`
- 技术路线选择：`docs/02-technical-route.md`
- 两轮迭代计划：`docs/03-iteration-plan.md`
- 测试方案与覆盖度：`docs/04-testing-strategy.md`

## 7. 说明
本仓库优先服务于课程实验交付，因此文档组织按“可提交、可实现、可验证”原则编排。后续若继续开发，可在此基础上扩展 Agent 核心能力与界面原型。