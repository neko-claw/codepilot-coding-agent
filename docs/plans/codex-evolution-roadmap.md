# CodePilot 向 Codex 级 Agent 演进路线图

> **For Hermes:** 先按本文拆分任务逐项落地，不要口头承诺“直接做到 Codex 级别”。每一阶段都必须有代码、测试、真实交互验证。

**Goal:** 将 CodePilot 从课程原型逐步推进到日常可用、可控、可验证的交互式 Coding Agent。

**Architecture:** 采用“可靠性优先、交互优先、执行闭环优先”的路线。先补足 planner 降级、会话可观测性、可恢复执行，再继续扩展多步工具调用、真正的 TUI、多缓冲区终端与更强沙盒。

**Tech Stack:** Python、pytest、Ruff、Pylint、readline/curses、DeepSeek/OpenAI-compatible planner、本地持久 shell、工作区快照。

---

## 0. 现实约束

“Codex 级别”不是单一功能点，而是下列能力的组合：

1. **高可靠规划**：在线 planner 失败时仍可继续工作
2. **真实工具闭环**：读、搜、改、跑、验、回退
3. **可观测交互**：用户能看见计划、风险、改动、失败类型、恢复路径
4. **长期会话能力**：持久 shell、历史、日志、快照、恢复
5. **可控执行**：白名单、确认、预算、重试、失败分流
6. **工程效果**：测试通过、静态检查通过、真实仓库烟雾验证通过

因此，正确目标不是“一步宣称对齐 Codex”，而是**按阶段逼近 Codex 的关键工程特征**。

---

## 1. 已完成基线

当前 CodePilot 已具备：

- Plan-first shell
- `/plan`、`/approve`、`/cancel`、`/status`、`/dashboard`
- `/files`、`/grep`、`/read`、`/replace`
- 工作区检查与候选命令推断
- 自动重试与失败类型分流
- 会话历史、日志、回退快照
- Planner timeout / invalid response fallback 到本地工作区规划
- dashboard 中展示 planner/retry trace

这说明项目已脱离“只会输出建议的原型”。

---

## 2. 下一阶段必须完成的能力

### 阶段 A：Planner 与执行可靠性

**目标：** 让 agent 在真实仓库中“尽量不中断”。

任务：
1. 增加 planner 超时、重试、fallback 策略配置
2. 为 planner fallback 增加更强的本地启发式计划生成
3. 给 auto 模式增加执行预算（最大命令数、最大编辑数、最大重试轮数）
4. 在日志和 dashboard 中展示预算消耗与降级原因

验收：
- 在线 planner 超时后 shell 不崩溃
- fallback 计划仍能输出候选文件、候选命令、风险提示
- 相关 pytest + smoke test 全通过

### 阶段 B：真正更像 Codex 的 TUI

**目标：** 从纯文本串行输出升级为多面板 TUI。

任务：
1. 引入 curses TUI 骨架
2. 左侧显示会话/计划/日志，右侧显示文件内容或 diff
3. 底部显示任务输入与状态栏，输入面板支持 draft / submit / history 提示
4. 支持查看 latest diff、planner trace、retry trace
5. 保留非 TUI shell 作为回退模式

验收：
- `codepilot` 默认可进入交互 shell
- `codepilot --tui` 可进入 curses 版本
- TUI 可查看计划、日志、diff、失败提示，并直接输入任务草案

### 阶段 C：多步代理循环

**目标：** 不再只依赖“一次 planner 输出 + 一次执行”，而是进入真正的 agent loop。

任务：
1. 定义中间动作模型：read/search/edit/run/finish
2. 让 planner 返回下一步动作而非只返回计划摘要
3. 每步执行后把结果回灌下一轮规划
4. 加入停止条件、预算条件与失败熔断条件
5. 为多步循环补测试与会话可观测性

验收：
- 一个任务可跨多轮 read/edit/run 完成
- 中间状态可被 dashboard 与日志复盘
- 回退与失败类型仍可追踪

### 阶段 D：更强执行隔离

**目标：** 接近 Codex 的“敢跑但可控”。

任务：
1. 区分主会话与隔离会话
2. 高风险命令默认在隔离目录/隔离 shell 中运行
3. 加入明确的 approval gate
4. 对文件改动做 checkpoint + selective restore

验收：
- 高风险命令不会默认污染主工作区
- 用户能看清楚哪些操作需要批准

---

## 3. 推荐执行顺序

1. **先做阶段 A**：这是阻塞真实体验的基础可靠性
2. **再做阶段 B**：让交互体验真正靠近 Codex
3. **再做阶段 C**：把“壳层”升级成真正多步代理
4. **最后做阶段 D**：强化安全与隔离

---

## 4. 当前最优先的近期任务

### Task 1: 完成 planner fallback 基础版
- 文件：`src/codepilot/runtime/session.py`
- 文件：`src/codepilot/ui/dashboard.py`
- 文件：`tests/unit/test_runtime_sprint2.py`
- 文件：`tests/unit/test_cli.py`
- 验证：`pytest -q tests/unit/test_runtime_sprint2.py tests/unit/test_cli.py`

### Task 2: 加入配置化 planner timeout
- 文件：`src/codepilot/core/config.py`
- 文件：`src/codepilot/cli.py`
- 文件：`tests/unit/test_config.py`
- 验证：`pytest -q tests/unit/test_config.py tests/unit/test_cli.py`

### Task 3: 设计 curses TUI 骨架
- 文件：`src/codepilot/ui/`
- 文件：`tests/unit/`
- 验证：最小 smoke test + 截图式字符串快照测试

---

## 5. 验证标准

每一阶段必须同时满足：

- pytest 通过
- Ruff / Pylint 通过
- 真实交互 smoke test 通过
- README / 技术路线文档同步更新

---

## 6. 结论

CodePilot 可以逐步逼近 Codex 的工程效果，但前提是：

- 不夸大“已经对齐”
- 不跳过可靠性建设
- 不只做 UI 外观
- 必须持续把交互、执行、验证、回退与观测能力一起推进

当前建议：**继续优先做阶段 A 与阶段 B。**
