# CodePilot 使用说明

本文档面向实际使用者，按“安装 → 配置 → 交互 → 执行 → 评估 → 排障”的顺序说明 CodePilot 的主要用法。

---

## 1. CodePilot 是什么

CodePilot 是一个面向仓库级任务的 Coding Agent 原型。它不是纯聊天机器人，而是一个具备以下能力的交互式执行器：

- 先规划，再执行
- 读取仓库上下文
- 搜索、编辑和写入文件
- 执行验证命令
- 记录会话、日志和回退快照
- 在规划器不可用时自动降级到本地规划
- 在验证失败时把失败上下文回灌到下一轮修复

适合的任务包括：

- 修复测试失败
- 补充单元测试
- 重构局部实现
- 生成脚手架
- 评估 benchmark / SWE-bench 数据集

不适合的场景：

- 需要强隔离的高风险破坏性命令
- 需要长期守护进程的生产部署
- 不愿意提供仓库上下文的模糊任务

---

## 2. 安装与启动

### 2.1 基本依赖

项目使用 Python 3.11+

推荐先安装开发环境：

```bash
python scripts/bootstrap.py --profile dev
```

如果你想手动安装：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements/dev.txt
```

### 2.2 运行测试

```bash
ruff check .
pylint src/codepilot
python -m pytest -q
```

---

## 3. 配置

CodePilot 会从项目根目录的 `.env` 和当前进程环境变量中读取配置。

### 3.1 DeepSeek 规划器相关配置

| 变量 | 含义 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 无，未设置则禁用规划器 |
| `DEEPSEEK_BASE_URL` | 兼容 OpenAI 的接口地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 规划使用的模型 | `deepseek-chat` |
| `DEEPSEEK_TIMEOUT` | 单次请求超时秒数 | `15.0` |
| `DEEPSEEK_RETRIES` | 规划器在超时/网络错误/非法 JSON 下的重试次数 | `2` |

### 3.2 存储目录

| 变量 | 含义 | 默认值 |
|------|------|--------|
| `CODEPILOT_STORAGE_DIR` | 会话、日志、快照的存储目录 | `.codepilot` |

### 3.3 最小 `.env` 示例

```env
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT=15
DEEPSEEK_RETRIES=2
CODEPILOT_STORAGE_DIR=.codepilot
```

### 3.4 配置建议

- 如果规划器经常超时，先把 `DEEPSEEK_TIMEOUT` 调大到 `20~30`
- 如果网络偶发不稳定，保留 `DEEPSEEK_RETRIES=2` 或更高
- 如果你想隔离不同仓库的历史与快照，不要共用存储目录

---

## 4. 最常用的交互方式

### 4.1 启动交互式 shell

```bash
codepilot
```

进入后可以直接输入自然语言任务。

典型流程：

1. 输入任务描述
2. 先得到计划
3. 检查候选文件、风险和建议命令
4. 使用 `/approve` 进入执行
5. 查看结果、日志和回退信息

### 4.2 常见命令

#### 规划与执行

- `/plan <任务>`：生成计划
- `/approve`：确认执行当前计划
- `/cancel`：取消当前任务
- `/mode plan`：仅规划
- `/mode auto`：自动执行
- `/run <任务>`：直接运行任务

#### 仓库上下文

- `/files <pattern>`：列出匹配文件
- `/grep <pattern> <glob>`：搜索文件内容
- `/read <path> <range>`：读取文件片段
- `/replace <path> <old> <new>`：替换文本

#### 状态与复盘

- `/status`：查看当前 shell 状态
- `/dashboard`：查看面板式汇总
- `/history`：查看历史会话
- `/logs <session_id>`：查看指定会话日志
- `/restore <snapshot_id>`：恢复快照

#### 结束与帮助

- `/help`：查看帮助
- `/exit`：退出

### 4.3 状态查看建议

当任务失败时，优先看这几个地方：

- `planner trace`
- `failure hints`
- `failure targets`
- `retry trace`
- `candidate files`
- `edit_results`

这几个字段通常足以判断下一步该看哪里。

---

## 5. Plan / Auto 工作流

CodePilot 设计上默认是 **Plan-first**。

### 5.1 Plan 模式

适合你还不确定要改哪里的时候。

```bash
codepilot run --workdir /path/to/repo --mode plan "为当前仓库生成修复计划"
```

Plan 模式会：

- 读取仓库上下文
- 推断候选文件
- 生成步骤和建议命令
- 不直接修改代码

### 5.2 Auto 模式

适合你已经确认方向，希望它自动执行并验证的时候。

```bash
codepilot run --workdir /path/to/repo --mode auto "修复失败测试并补充回归用例"
```

Auto 模式会：

- 读取候选文件
- 应用确定性编辑或文件写入
- 执行验证命令
- 在失败时构造失败上下文
- 在允许重试的情况下进入下一轮修复

### 5.3 什么时候使用 `/approve`

如果你在交互式 shell 中先得到计划，确认无误后再执行：

```text
/approve
```

如果任务涉及较大改动，建议先看计划再批准。

---

## 6. TUI 使用说明

`codepilot --tui` 会进入 curses TUI；在非 TTY 环境下则退化为可测试的字符串快照。

```bash
codepilot --tui --workdir /path/to/repo
```

### 6.1 界面结构

当前 TUI 主要有三块：

- 左侧：会话 / 日志导航
- 右侧：详情面板
- 底部：任务输入区

### 6.2 常用按键

- `Tab`：切换焦点
- `s`：会话列表
- `g`：日志列表
- `d`：查看 diff
- `p`：查看 planner trace
- `f`：查看 failure hints
- `t`：查看 failure targets / target files
- `j` / `k`：上下移动或滚动
- `Enter`：提交输入区内容
- `q`：退出

### 6.3 TUI 的使用重点

如果你只想快速定位问题，优先看：

- `planner trace`：规划器是否回退、是否使用 DeepSeek
- `failure hints`：失败的原因摘要
- `target files`：最值得优先查看的文件
- `diff`：当前修改内容

TUI 的目标不是“好看”，而是把最关键的调试信息尽快暴露出来。

---

## 7. Harness：单次运行、恢复、循环修复

Harness 是面向开发者日常使用和回归验证的命令组。

### 7.1 单次任务运行

```bash
codepilot harness run --workdir /path/to/repo --mode auto --format markdown "修复登录失败并补充测试"
```

支持格式：

- `text`
- `markdown`
- `json`

### 7.2 恢复会话

```bash
codepilot harness resume session-42 --format text
```

适合查看旧会话的结构化结果或报告。

### 7.3 循环闭环修复

```bash
codepilot harness loop --workdir /path/to/repo --max-rounds 3 "修复登录失败并补充测试"
```

适合：

- 需要多轮试错的修复任务
- 验证命令失败后继续修复
- 想观察 planner trace / retry trace 的场景

### 7.4 数据集评估

```bash
codepilot harness eval --dataset-format swebench --source-repo /path/to/repo suite.json
```

这会把 benchmark / SWE-bench 类任务跑成可汇总的评估结果。

### 7.5 交互式 shell 子命令

```bash
codepilot harness shell --workdir /path/to/repo
```

适合喜欢命令式工作流的人。

---

## 8. 推荐的日常工作方式

### 8.1 修测试

1. 启动 shell
2. 输入失败说明
3. 看计划
4. 确认候选文件
5. 执行
6. 看 `failure hints` 和 `target files`
7. 必要时恢复快照

### 8.2 新增功能

1. 先用 `/files` 和 `/grep` 看仓库结构
2. 用 `/plan` 生成执行计划
3. 先写测试，再改实现
4. 用 `/approve` 进入执行
5. 用 `pytest` 或项目自带验证命令确认结果

### 8.3 从零生成脚手架

如果任务描述包含“agent / coding agent / assistant”，规划器会优先建议：

- `README.md`
- `pyproject.toml`
- `src/agent.py`
- `src/cli.py`
- `tests/test_agent.py`
- `src/__init__.py`

这是为了避免生成只有空壳、不能运行的原型。

---

## 9. 典型示例

### 示例 1：修复失败测试

```bash
codepilot run --workdir /home/hermes/codepilot-coding-agent --mode auto "修复 pytest 中的失败用例并补充回归测试"
```

### 示例 2：先看计划再执行

```bash
codepilot run --workdir /home/hermes/codepilot-coding-agent --mode plan "为 CLI 增加 planner retry 配置"
```

### 示例 3：查看历史会话

```bash
codepilot history --workdir /home/hermes/codepilot-coding-agent
codepilot logs <session_id> --workdir /home/hermes/codepilot-coding-agent
```

### 示例 4：恢复快照

```bash
codepilot restore <snapshot_id> --workdir /home/hermes/codepilot-coding-agent
```

---

## 10. 调试与排障

### 10.1 规划器不可用

如果看到类似提示：

- `DeepSeek planner is disabled`
- `Planner fallback activated`

说明规划器没有可用的 API Key，或者请求失败后已回退到本地规划。

处理方式：

1. 检查 `.env` 是否有 `DEEPSEEK_API_KEY`
2. 检查 `DEEPSEEK_BASE_URL` 是否正确
3. 检查 `DEEPSEEK_TIMEOUT` 和 `DEEPSEEK_RETRIES`
4. 看 `planner trace` 中的 note

### 10.2 自动执行没有继续重试

可能原因：

- 已达到 `max_auto_retries`
- 验证命令属于不允许自动重试的失败类型
- 执行预算已耗尽
- 规划器没有返回足够的修复信息

处理方式：

- 看 `retry trace`
- 看 `failure hints`
- 看 `execution budget`
- 增加 `--max-auto-retries` 或命令/编辑预算

### 10.3 找不到修改目标

优先看：

- `candidate_files`
- `inspected_files`
- `Failure Targets`
- `target files`

如果还是不明确，先手动 `/files`、`/grep` 一轮，再继续。

### 10.4 任务执行结果不符合预期

建议按顺序检查：

1. 计划是否合理
2. 修改是否命中正确文件
3. 测试是否覆盖了修改
4. 是否有快照可回退
5. 是否有失败上下文被传回 planner

---

## 11. 验证清单

在你认为任务完成前，至少确认：

- [ ] 计划正确
- [ ] 修改文件正确
- [ ] 验证命令运行过
- [ ] 失败提示看过
- [ ] 目标文件看过
- [ ] 需要时已回退或重新执行
- [ ] `python -m pytest -q` 通过

---

## 12. 一句话总结

如果你希望 CodePilot 像 Codex 一样工作，正确姿势不是“直接让它全自动改代码”，而是：

**先看上下文，先出计划，先确认风险，再执行，失败后继续把失败上下文回灌进去。**
