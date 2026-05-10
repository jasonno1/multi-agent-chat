# Multi-Agent Chat v2.0 升级总结

**日期**: 2026-05-10
**版本**: v1.0 → v2.0
**变更类型**: 架构级重构（Phase 1-3）

---

## 一、核心变更概述

### 原架构问题

| 问题 | 描述 |
|------|------|
| **临时进程** | 每次回复启动一个 hermes 子进程，获取响应后立即退出，无任何记忆 |
| **无真正 agent** | 每次调用是独立的"问答"，不是"持续运行的 agent 在群聊" |
| **统一记忆** | 所有记忆由 orchestrator 统一写入 GBrain，各 profile 无独立记忆 |
| **自由抢答** | 无发言控制，任何 profile 可随时输出，无法实现拟人协作 |
| **缺乏管理员** | 无管理员角色，无法实现任务分配和打断 |

### 新架构改进

| 改进 | 描述 |
|------|------|
| **常驻进程** | 每个 profile 是独立的 Python 进程，整个会话期间存活 |
| **Socket 总线** | 通过 Unix Domain Socket 实现进程间通信，支持 JOIN/MESSAGE/TASK/END_OF_SPEECH 等消息类型 |
| **持久记忆** | 每个 profile 使用 Hermes GBrain 持久化记忆（profile 级别），群聊日志由管理员写入 Obsidian |
| **结构化发言控制** | 状态机控制发言权，必须以"我的发言结束。"结尾才放行下一位 |
| **管理员角色** | 指定管理员，拥有打断、优先发言、任务分配权限 |
| **Goal 模式** | 用户设定目标 → 管理员拆解 → @分发任务 → 各 profile 执行 → 汇报 |
| **干净输出** | 群聊空间内禁止 think 内容，只输出最终结论 |

---

## 二、文件变更

### 新增文件

```
multi-agent-chat/
├── bus/                              # [NEW] Socket 通信层
│   ├── __init__.py
│   ├── protocol.py                   # 消息协议（10种消息类型，JSON序列化）
│   └── chat_bus.py                   # Unix Domain Socket 服务端
├── agents/                           # [NEW] Agent 进程层
│   ├── __init__.py
│   └── agent_runner.py               # 常驻 ProfileAgent wrapper 进程
├── rules/                            # [NEW] 规则引擎
│   ├── __init__.py
│   ├── speech_controller.py          # 发言状态机 (IDLE→SPEAKING→END)
│   ├── admin_role.py                 # 管理员权限与任务分配
│   └── goal_mode.py                  # Goal 拆解、进度追踪
├── core/
│   └── orchestrator.py               # [NEW] 主控器（替代原 main.py 的 MultiAgentChat）
├── tests/
│   └── test_core_modules.py          # [NEW] 核心模块集成测试
└── multi-agent-chat-rule.md          # [NEW] v2.0 架构设计文档
```

### 修改文件

| 文件 | 变更内容 |
|------|---------|
| `main.py` | 从 ~420 行 MultiAgentChat 类简化为 ~20 行，调用 Orchestrator |
| `ui/command_parser.py` | 新增 ADMIN、GOAL、INTERRUPT 命令及解析逻辑 |
| `ui/cli_renderer.py` | 更新 banner 为 v2.0，帮助信息增加新命令说明 |
| `config/defaults.yaml` | 新增 speech、goal、agent、memory 配置节 |
| `README.md` | 完全重写，涵盖 v2.0 所有新特性 |

### 删除/废弃文件

| 文件 | 原因 |
|------|------|
| 原 `core/orchestrator.py` | 原是 orchestrator 的一部分，现已完全重写 |
| `core/gbrain_bridge.py` | v1.x 记忆模块，已被 Hermes GBrain 取代 |
| `memory/` 目录 | v2.0 临时记忆层，已被 Hermes GBrain 取代 |

---

## 三、新模块详解

### 3.1 bus/ — Socket 通信层

**protocol.py**
- 定义 10 种消息类型：`JOIN` `WELCOME` `LEAVE` `SHUTDOWN` `MESSAGE` `TASK` `RESPONSE` `GRANT_SPEECH` `END_OF_SPEECH` `INTERRUPT`
- `Message` 数据类，包含 type/from/to/timestamp/payload
- `parse_message()` / `make_message()` 工具函数

**chat_bus.py**
- Unix Domain Socket 服务端（`/tmp/mac-bus/{session}/chat-bus.sock`）
- 支持多 client 接入（pending → registered）
- `broadcast()` 向所有 agent 广播消息
- `send_to()` 向指定 agent 发送消息
- 回调钩子：`on_message` `on_join` `on_leave`

### 3.2 agents/ — Agent 进程层

**agent_runner.py**
- `ProfileAgent` 类：每个 profile 的常驻 wrapper
- 连接 ChatBus，发送 JOIN，等待 WELCOME
- 收到 `GRANT_SPEECH` 时调用 hermes 生成响应
- 响应必须以"我的发言结束。"结尾
- 独立维护 `_conversation_history`
- 自动清理 think 块（如 `<thinking>` `<think>` 等）

**进程启动方式**：
```bash
python3 -m agents.agent_runner <profile_name> <session_id> <socket_path> [--admin] [--order N]
```

### 3.3 rules/ — 规则引擎

**speech_controller.py**
- 状态机：`IDLE` → `SPEAKING` → `END_OF_SPEECH` → `IDLE`
- 发言队列管理：`enqueue()` `dequeue()`
- `resolve_speakers()` 根据模式（free/mention/ordered）和 @mention 确定发言顺序
- `END_MARKER = "我的发言结束。"`
- 回调：`on_grant` `on_speech_end` `on_interrupt`

**admin_role.py**
- `AdminRole` 类：管理管理员身份和任务分配
- `assign_task()` 分配任务并记录
- `complete_task()` 标记完成并记录结果
- `summary()` 生成任务状态报告

**goal_mode.py**
- `GoalMode` 类：管理目标模式
- `set_goal()` 激活目标
- `add_task()` 添加子任务
- `complete_task()` 完成子任务
- `get_progress()` 生成进度字符串
- `is_complete()` 检查所有任务是否完成

---

## 四、架构图

### 新架构

```
┌─────────────────────────────────────────────────────┐
│                   mac Orchestrator                   │
│  (REPL + ChatBus + SpeechController + AdminRole    │
│   + GoalMode + StateManager)                         │
│                                                       │
│  socket_path: /tmp/mac-bus/{session}/chat-bus.sock  │
└──────┬──────────┬──────────┬───────────────┬────────┘
       │          │          │               │
   ┌───┴───┐ ┌───┴───┐ ┌───┴───┐     ┌─────┴─────┐
   │Profile│ │Profile│ │Profile│     │   Admin   │
   │Agent  │ │Agent  │ │Agent  │     │   Agent   │
   │(常驻) │ │(常驻) │ │(常驻) │     │  (常驻)   │
   └───┬───┘ └───┬───┘ └───┬───┘     └─────┬─────┘
       │          │          │              │
       └──────────┴─────┬─────┴──────────────┘
                        │
           Unix Domain Socket (UDS)
           消息类型: JOIN/WELCOME/MESSAGE/TASK/
                    RESPONSE/END_OF_SPEECH/INTERRUPT
```

### 消息流

```
用户输入消息
    ↓
Orchestrator 路由：确定发言顺序
    ↓
broadcast(MESSAGE) 给所有在线 agent
    ↓
grant_speech(第一个发言者)
    ↓
ProfileAgent 调用 hermes chat -q 获取响应
    ↓
ProfileAgent 发送 RESPONSE 消息
    ↓
Orchestrator 显示响应，检查 @mentions
    ↓
ProfileAgent 发送 END_OF_SPEECH
    ↓
Orchestrator 授予下一位发言权
    ↓
重复直到发言队列为空
```

---

## 五、命令对照表

### 新增命令

| 命令 | 说明 | 对应功能 |
|------|------|----------|
| `/admin <name>` | 设置群管理员 | AdminRole.set_admin() |
| `/goal <描述>` | 设定群聊目标 | GoalMode.set_goal() |
| `/goal` | 查看目标进度 | GoalMode.get_progress() |
| `/interrupt` | 打断当前发言者 | SpeechController.interrupt() |

### 修改命令

| 原命令 | 新命令 | 变更 |
|--------|--------|------|
| `/profile -t <name>` | `/profile -t <name>` | 行为变更：启动常驻进程而非临时调用 |
| `/profile -m <name>` | `/profile -m <name>` | 行为变更：终止进程而非从成员列表移除 |

---

## 六、配置变更

### 新增配置项 (defaults.yaml)

```yaml
# 发言控制
speech:
  end_marker: "我的发言结束。"      # 结构化发言结束标记
  max_response_time: 120            # 最大响应时间（秒）

# Goal 模式
goal:
  max_tasks: 10                     # 每个目标最大子任务数

# Agent 进程
agent:
  start_timeout: 30                 # Agent 连接超时（秒）
  process_grace_period: 3           # 进程终止宽限期（秒）
```

---

## 七、测试覆盖

### test_core_modules.py (6 项测试)

- Protocol 序列化/反序列化
- SpeechController 状态机/发言控制/队列
- AdminRole 任务分配/完成/汇总
- GoalMode 目标设置/任务管理/完成
- ChatBus 多 client 连接/消息路由
- End-to-end 发言流程

---

## 八、已知限制

| 限制 | 说明 |
|------|------|
| Python 3.9 兼容 | 使用 `from __future__ import annotations` 支持类型注解语法 |
| Hermes 依赖 | 仍依赖 `hermes chat -q` 子进程调用 |
| Socket 路径限制 | UDS socket 路径最长 ~108 字符，受文件系统限制 |
| 心跳检测 | Agent 崩溃后自动重启，但重启期间消息可能丢失 |

---

## 九、v2.1 修复记录

### 已修复问题

| 问题 | 修复方式 | 文件 |
|------|----------|------|
| _clean_response 误杀正常口语 | 只删 XML 标签，保留 "我认为" 等口语 | agents/agent_runner.py |
| END_MARKER 单点故障 | 120s 超时强制跳过 + 回调激活下一发言者 | core/orchestrator.py |
| Agent 崩溃无自愈 | 心跳检测（30s间隔，90s超时）+ 自动重启 | core/orchestrator.py |
| Shutdown 等待不充分 | 10s 优雅终止 + 2s force kill，无重复 terminate | core/orchestrator.py |
| Agent 收到 SHUTDOWN 不退出 | SHUTDOWN 消息触发 socket 关闭 | agents/agent_runner.py |
| 冗余 memory 模块 | 删除 ProfileMemory + GBrainSync，改用 Hermes GBrain | memory/ 目录删除 |

### 修复详情

**1. _clean_response 修复**
- 原问题：正则误删 "让我想想"、"我认为" 等正常口语
- 修复：仅删除 `<thinking>` `<think>` `</thinking>` `</plan>` 等 XML 标签块
- 不再过滤包含 "我认为" 的完整句子

**2. END_MARKER 超时兜底**
- 添加 `_speech_timers` 字典追踪每个发言者计时器
- `_start_speech_timer()` 在 GRANT_SPEECH 后启动 120s 定时器
- 超时触发 `_handle_speech_timeout()`：强制 interrupt → 重置状态 → 激活下一发言者
- `_cancel_speech_timer()` 在收到 END_OF_SPEECH 时取消

**3. Agent 心跳健康检查**
- `_start_heartbeat_check()` 每 30 秒检查一次
- 90 秒无心跳 → `_respawn_agent()` 终止旧进程并重启
- 保留原 admin/speaking_order 设置

**4. Shutdown 流程优化**
- 删除重复的 terminate/wait 代码块
- 优雅终止：10 秒 timeout（足够进程清理资源）
- Force kill：2 秒 timeout（仅对未响应进程）
- Agent 收到 SHUTDOWN 后立即关闭 socket

**5. 记忆模块清理**
- 删除 `memory/profile_memory.py`：不再需要 JSON 文件缓存
- 删除 `memory/gbrain_sync.py`：不再需要手动同步到 Obsidian
- 删除 `tests/test_memory.py`：对应测试已移除
- Agent 端不再导入 ProfileMemory，内存操作全部依赖 Hermes GBrain
- orchestrator 不再导入 GBrainSync

---

## 十、后续计划（Phase 4 取消）

~~Phase 4: Hermes Plugin 化~~

原计划的 plugin 化已取消，v2.0 将作为独立 CLI 工具运行。