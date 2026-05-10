# Multi-Agent Chat v2.1

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)

基于 Hermes Agent 的 CLI 多智能体群聊系统。通过独立常驻进程、Socket 通信总线和结构化发言控制，实现真正的拟人群聊协作。

## 核心特性

- **真正独立的 Agent 进程** — 每个 profile 是独立的常驻进程，各自管理记忆和状态
- **严格发言控制** — 同一时间只有一人发言，以"我的发言结束。"结构化收尾
- **管理员权限** — 可指定群管理员，拥有打断、优先发言、任务分配权限
- **Goal 模式** — 设定目标后，管理员拆解任务并 @ 分发给各 profile 执行
- **Hermes GBrain 记忆** — 每个 profile 的记忆由 Hermes GBrain 自动管理（profile 级别，跨会话持久化）
- **干净输出** — 群聊空间内禁止 think/内部推理输出，只显示最终结论

## 前置要求

- **Hermes Agent** 已安装并配置好 profiles
  - 安装方式：https://github.com/nousplatform/hermes-agent
  - 确认 `hermes` 命令可用：`hermes --version`
- **Python 3.9+**
- **macOS / Linux**（依赖 Unix Domain Socket）

## 安装

```bash
# 克隆仓库
git clone https://github.com/jasonno1/multi-agent-chat.git ~/.hermes/tools/multi-agent-chat

# 进入目录
cd ~/.hermes/tools/multi-agent-chat
```

## 快速开始

```bash
python3 main.py
```

## 基础使用

```bash
# 1. 查看可用 profile
/profile list

# 2. 拉人入群
/profile -t product-manager
/profile -t engineer

# 3. 设置管理员
/admin product-manager

# 4. 设置发言顺序
/profile -t admin -1
/profile -t engineer -2

# 5. 开始对话
@product-manager 这个方案你怎么看？
```

## 完整命令参考

### Profile 管理

| 命令 | 说明 |
|------|------|
| `/profile list` | 列出所有可用 profile |
| `/profile -t <name>` | 邀请 profile 入群（启动独立常驻进程） |
| `/profile -m <name>` | 移出群聊（终止进程） |
| `/profile -t list` | 查看群成员、模式、发言顺序 |

### 发言控制

| 命令 | 说明 |
|------|------|
| `/profile mode free` | 自由模式：所有在线 profile 依次发言 |
| `/profile mode mention` | 点名模式：仅被 @ 的 profile 回复 |
| `/profile mode ordered` | 顺序模式：按预设序号依次发言 |
| `/profile -t <name> -<N>` | 设置发言顺序（从 1 开始） |
| `/profile -t <name> -<N> -f` | 强制覆盖已被占用的序号 |
| `/profile order off` | 清除发言顺序 |

### 管理与协作

| 命令 | 说明 |
|------|------|
| `/admin <name>` | 设置群管理员（可打断、优先发言、分配任务） |
| `/goal <描述>` | 设定群聊目标，触发管理员拆解并分发任务 |
| `/goal` | 查看当前目标进度 |
| `/interrupt` | 打断当前发言者（仅用户和管理员可用） |

### 系统

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/quit` | 退出（自动保存会话） |

## 三种对话模式

| 模式 | 命令 | 行为 |
|------|------|------|
| **FREE**（默认） | `/profile mode free` | 管理员优先 → @提及的 → 预设顺序 → 其余成员 |
| **MENTION** | `/profile mode mention` | 仅被 @ 点名的 profile 回复 |
| **ORDERED** | `/profile -t <name> -<N>` | 管理员优先 → @提及的 → 序号升序 |

## 发言规则

1. **禁止打断** — 当 profile 发言时，其他 profile 不可输出。用户和管理员可以打断。
2. **发言结束标记** — 每次发言必须以**"我的发言结束。"**结尾。看到此标记后，下一位才获得发言权。
3. **禁止 Think** — 群聊空间内不得输出内部推理、思考过程、工具调用中间状态。只输出最终结论。
4. **独立记忆** — 每个 profile 独立管理自己的短期记忆和上下文。

## Goal 模式流程

```
用户: /goal 实现用户注册功能
  ↓
管理员: 分析目标 → 拆解为子任务
管理员: @engineer 请实现后端注册 API (task_001)
管理员: @designer 请设计注册页面 UI (task_002)
  ↓
[engineer]: 已完成。接口: POST /api/register ... 我的发言结束。
[designer]: 设计稿已完成。含邮箱验证、密码强度提示 ... 我的发言结束。
  ↓
管理员: 综合汇报 → 全部完成 ✅
```

## Profile 间互相 @

Profile 可以在回复中 @ 其他 profile：

```
[Admin]: 需要技术评估。@engineer 分析一下可行性。我的发言结束。
→ orchestrator 自动将 engineer 加入发言队列
[Engineer]: 可行但有风险。@designer 需要修改交互流程。我的发言结束。
→ designer 获得发言权
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│              Orchestrator (主控进程)                  │
│  ChatBus · SpeechController · AdminRole · GoalMode   │
└──────┬──────────┬──────────┬───────────────┬────────┘
       │          │          │               │
   ┌───┴───┐ ┌───┴───┐ ┌───┴───┐     ┌─────┴─────┐
   │Profile │ │Profile │ │Profile │     │  Admin    │
   │ Agent  │ │ Agent  │ │ Agent  │     │  Agent    │
   │(hermes)│ │(hermes)│ │(hermes)│     │ (hermes)  │
   │ 常驻进程│ │ 常驻进程│ │ 常驻进程│     │  常驻进程  │
   └───┬───┘ └───┬───┘ └───┬───┘     └─────┬─────┘
       └──────────┴─────┬─────┴──────────────┘
                        │
           Unix Domain Socket (/tmp/mac-bus/{session}/chat-bus.sock)
```

## 项目结构

```
multi-agent-chat/
├── main.py                     # CLI 入口
├── core/
│   ├── orchestrator.py         # 主控器：REPL、进程管理、消息路由
│   ├── profile_manager.py      # Profile 发现、SOUL.md 解析
│   ├── context_builder.py      # 上下文构建
│   └── state_manager.py        # 会话持久化 (JSON)
├── bus/                         # Socket 通信层
│   ├── protocol.py              # 消息协议（10种消息类型，JSON 序列化）
│   └── chat_bus.py             # Unix Domain Socket 服务端
├── agents/                      # Agent 进程层
│   └── agent_runner.py          # 常驻 Agent wrapper 进程
├── rules/                       # 规则引擎
│   ├── speech_controller.py     # 发言状态机 (IDLE→SPEAKING→END)
│   ├── admin_role.py            # 管理员权限与任务分配
│   └── goal_mode.py             # Goal 拆解、进度追踪
├── bridge/
│   └── hermes_bridge.py        # Hermes 子进程调用（hermes chat -q）
├── ui/
│   ├── command_parser.py        # 命令解析与 @mention 提取
│   └── cli_renderer.py          # ANSI 终端渲染
├── config/
│   ├── settings.py
│   └── defaults.yaml
├── state/
│   └── session.json
└── tests/
    └── test_core_modules.py      # 核心模块测试
```

## 技术说明

- 依赖 Hermes Agent（`hermes` 命令可用）
- 每个 profile 是独立的 Python 子进程，通过 Unix Domain Socket 与主控通信
- AI 响应通过 `hermes chat -q -p <profile> -s <skill>` 子进程调用
- 各 profile 记忆由 Hermes GBrain 管理（profile 级别，跨会话持久化）
- 会话状态保存在 `state/session.json`（24h 过期）

## 会话恢复

退出时自动保存会话（成员列表、模式、发言顺序、最近 50 条历史）。下次启动时检测 24h 内会话，提示恢复。
