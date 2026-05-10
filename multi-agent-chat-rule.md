# Multi-Agent Chat 群聊规则与架构设计

**状态**: Draft v1.0
**日期**: 2026-05-09
**目标**: 将 mac 从"临时进程召唤"升级为"真正常驻多智能体协作系统"

---

## 一、核心设计原则

1. **真正独立的 Agent 进程** — 每个 profile 在群聊期间是常驻进程，不是每次召唤
2. **各自独立的会话空间** — 每个 profile 看到的是完整、一致的群聊上下文
3. **严格发言控制** — 非发言状态的 profile 不可输出任何内容
4. **结构化通信协议** — 所有进程间通信使用 JSON 标准化消息
5. **干净输出** — 群聊空间内禁止输出 think/内部推理内容

---

## 二、进程架构

### 2.1 进程模型

```
┌─────────────────────────────────────────────────────┐
│                   mac Orchestrator                   │
│              (主控进程，Python REPL)                  │
│                                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │Profile A│  │Profile B│  │Profile C│  │Admin    │ │
│  │(hermes) │  │(hermes) │  │(hermes) │  │(hermes) │ │
│  │常驻进程 │  │常驻进程 │  │常驻进程 │  │常驻进程 │ │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘ │
│       │            │            │            │        │
│       └────────────┴─────┬──────┴────────────┘        │
│                         │                             │
│              Unix Domain Socket                       │
│              (群聊总线 /chat-bus)                      │
└─────────────────────────┬───────────────────────────┘
                          │
            各 profile 进程通过 socket 收发消息
```

### 2.2 各进程职责

| 进程 | 职责 |
|------|------|
| **Orchestrator** (mac 主进程) | 维护群聊状态、发言权控制、消息路由、规则执行 |
| **Profile Agent** (hermes 子进程) | 独立思考、独立记忆、响应任务、控制输出 |
| **Chat Bus** (UDS socket) | 所有进程间通信的中央总线 |

---

## 三、Socket 通信协议

### 3.1 协议格式

所有消息为单行 JSON，带有 `type` 字段标识消息类型。

```json
// 通用消息结构
{
  "type": "message_type",
  "from": "profile_name",
  "to": "profile_name | *",
  "timestamp": "2026-05-09T15:00:00.123",
  "payload": { ... }
}
```

### 3.2 消息类型

| type | 方向 | 说明 |
|------|------|------|
| `join` | Profile → Orchestrator | profile 申请加入群聊 |
| `welcome` | Orchestrator → Profile | 欢迎消息，包含 profile 列表、规则、自己的身份 |
| `message` | Any → Any | 聊天消息 |
| `task` | Admin/User → Profile | 任务下发消息 |
| `response` | Profile → Any | 对 `task` 的响应 |
| `end_of_speech` | Profile → Orchestrator | 发言结束信号 |
| `interrupt` | Admin/User → Profile | 打断信号 |
| `rule_violation` | Orchestrator → Profile | 规则违规警告 |
| `shutdown` | Orchestrator → All | 关闭群聊 |

### 3.3 Socket 命名约定

```
/tmp/mac-{session_id}/chat-bus.sock
```

每个会话独立目录，防止多实例冲突。

### 3.4 Profile 加入流程

```
Profile 进程启动
    │
    ▼
连接 /tmp/mac-{session_id}/chat-bus.sock
    │
    ▼
发送 { "type": "join", "from": "profile_name" }
    │
    ▼
等待 welcome 消息（含群聊规则 + 成员列表 + 发言顺序）
    │
    ▼
进入"等待发言权"状态
```

### 3.5 完整消息流程

```
[用户] 发送普通消息
    ↓
Orchestrator 路由：谁该发言
    ↓
给目标 Profile 发 task 消息
    ↓
Profile 独立处理（可查资料、用工具）
    ↓
Profile 通过 socket 返回 response
    ↓
Orchestrator 检查是否还有后续发言者
    ↓
无 → 用户输入"我的发言结束"
    ↓
Orchestrator 放行下一个 Profile
```

---

## 四、群聊规则 (Group Chat Protocol)

### 4.1 基础规则

当 Profile 被拉入群聊时，Orchestrator 发送完整的群聊规则文本（SOUL.md 中体现）：

```markdown
# 群聊规则

你是 {display_name}，正在参与一个多智能体群聊。

## 身份与职责
- 你的 profile: {profile_name}
- 你的角色: {role}
- 你的权限: {admin | member}

## 群聊空间规则
1. **发言控制**: 你只能在获得发言权时输出内容。未获得发言权时，无论收到什么消息，都不得输出任何内容。
2. **发言结束**: 你在完成每次发言后，必须以"我的发言结束。"作为结尾。
3. **禁止打断**: 在其他 Profile 发言期间（未说"我的发言结束"前），你不得输出任何内容。
4. **禁止 Think**: 群聊空间内，你不得输出任何包含"思考"、"分析"、"我觉得"等内部推理内容，只输出最终结论。
5. **记忆管理**: 你的个人记忆存储在 Hermes GBrain 中（profile 级别，跨会话持久化）。
6. **任务处理**: 收到 @ 你的任务消息时，独立处理并返回结果。

## 权限说明
- **管理员 (admin)**: 可以 @ 任何人，发言权优先于普通 profile，可以打断任何人的发言。
- **普通成员 (member)**: 按发言顺序或被 @ 顺序发言。

## 发言权获取规则
- 用户输入后，获得发言权的 Profile 依次发言
- 发言顺序: 管理员 > 被 @ 的 Profile > 预设顺序中的其他 Profile
- 上一位 Profile 说"我的发言结束"后，下一位才获得发言权
```

### 4.2 发言状态机

```
                    ┌─────────────────┐
                    │   IDLE          │  ← 初始/发言结束后
                    └────────┬────────┘
                             │
              Orchestrator 授予发言权
                             │
                             ▼
                    ┌─────────────────┐
         ┌─────────│   SPEAKING      │  Profile 可以输出
         │         └────────┬────────┘
         │                  │
         │    Profile 输出 "我的发言结束。"
         │                  │
         │                  ▼
         │         ┌─────────────────┐
         │         │  END_OF_SPEECH  │  发送 end_of_speech 消息
         │         └────────┬────────┘
         │                  │
    Admin/User              │ Orchestrator 确认并放行下一位
    打断信号                 │
         │                  ▼
         │         返回 IDLE
         │
         └──────→ (被打断) 返回 IDLE
```

### 4.3 打断规则

- **管理员** 和 **用户** 可以随时打断任何 Profile 的发言
- 普通 Profile 之间不可互相打断
- 打断时 Orchestrator 向被断 Profile 发送 `interrupt` 消息
- 被断 Profile 必须立即停止输出，回归 IDLE 状态

---

## 五、Goal 模式

### 5.1 激活方式

```
/goal <最终目标描述>
```

### 5.2 运作流程

```
用户设置 Goal
    ↓
Orchestrator 将 Goal 发送给管理员 Profile
    ↓
管理员 分析目标 → 拆解任务
    ↓
管理员 @ 各 Profile 下发任务 (使用 task 消息)
    ↓
各 Profile 独立执行任务
    ↓
Profile 完成任务后向管理员汇报
    ↓
管理员 综合后向用户汇报
```

### 5.3 任务下发格式

管理员通过 `task` 消息 @ 某 Profile：

```json
{
  "type": "task",
  "from": "admin",
  "to": "engineer",
  "payload": {
    "task_id": "task_001",
    "goal": "实现用户注册功能",
    "requirements": ["邮箱验证", "密码加密", "验证码防刷"],
    "deadline": "尽快"
  }
}
```

Profile 完成任务后返回：

```json
{
  "type": "response",
  "from": "engineer",
  "to": "admin",
  "payload": {
    "task_id": "task_001",
    "result": "已完成注册功能开发，包括...",
    "status": "completed"
  }
}
```

---

## 六、记忆管理

### 6.1 各 Profile 独立管理记忆

每个 Profile 的记忆由 Hermes GBrain 管理（profile 级别，跨会话持久化）。

### 6.2 记忆文件格式

```json
{
  "profile": "product-manager",
  "session_id": "20260509_abc123",
  "short_term": [
    {
      "timestamp": "2026-05-09T15:00:00",
      "content": "讨论了用户注册流程",
      "related_to": "task_001"
    }
  ],
  "gbrain_synced": false
}
```

### 6.3 记忆同步

- 每个 Profile 的记忆由 Hermes GBrain 自动管理（profile 级别，跨会话持久化）
- 管理员可将群聊日志写入 Obsidian vault 的 `admin/{session}.md`

---

## 七、输出规范

### 7.1 禁止输出内容

群聊空间内，所有 Profile **禁止**输出：

- Think / 内部推理过程
- 包含"我认为"、"我觉得"、"让我想想"的中间态内容
- 工具调用中间过程（如"正在搜索..."、"正在调用 API..."）
- 任何非结论性的中间输出

### 7.2 允许输出内容

- 直接的结论和观点
- 对问题的回答
- 对其他 Profile 的回复
- 任务执行结果
- **必须以"我的发言结束。"结尾**

### 7.3 示例

**错误**:
```
我觉得这个方案不太合适...（思考中）让我查一下相关资料...
正在搜索"最佳实践"...
我的发言结束。
```

**正确**:
```
方案A在可扩展性上更优，建议采用。我的发言结束。
```

---

## 八、与 Hermes 集成

### 8.1 最终目标

mac 作为 Hermes 内部 plugin 运行，通过 `hermes mac` 命令激活。

### 8.2 集成路径

Phase 1: Standalone CLI（当前状态）
↓ 使用 UDS socket 常驻进程方案
Phase 2: Hermes plugin（`hermes mac` 命令）
↓ 利用 Hermes plugin API
Phase 3: Core 集成（成为 Hermes 内置功能）

### 8.3 Plugin 化后的命令

```
/mac start              启动群聊会话
/mac invite <profile>   邀请 profile 入群
/mac goal <目标>         设置群聊目标
/mac status             查看当前状态
/mac end                结束群聊
```

---

## 九、实现优先级

| 阶段 | 内容 | 产出 |
|------|------|------|
| **Phase 1** | 常驻进程架构 + UDS socket 协议 + 发言控制 | 真正的多 Agent 群聊基础 |
| **Phase 2** | Goal 模式 + Admin 权限 + 任务分发 | 可用的任务协作系统 |
| **Phase 3** | 各自记忆管理 + GBrain 同步 | 跨会话持久记忆 |
| **Phase 4** | Hermes plugin 化 | 成为 Hermes 的一部分 |

---

## 十、文件结构（目标）

```
multi-agent-chat/
├── __init__.py
├── __main__.py
├── main.py                          # CLI 入口 + REPL
├── core/
│   ├── __init__.py
│   ├── orchestrator.py              # 主控逻辑：状态机、发言权、路由
│   ├── profile_manager.py           # Profile 发现与加载（不变）
│   ├── context_builder.py           # 上下文构建（不变）
│   ├── state_manager.py             # 会话持久化（扩展支持 goal）
│   └── session.py                   # 新：会话管理器（socket 生命周期）
├── agents/                          # 新：Profile Agent 封装
│   ├── __init__.py
│   ├── base.py                     # Base profile agent 封装
│   └── profile_agent.py            # 启动和管理 hermes profile 子进程
├── bus/                             # 新：Socket 通信总线
│   ├── __init__.py
│   ├── chat_bus.py                # UDS socket 服务端
│   ├── protocol.py                # 消息协议定义
│   └── exceptions.py               # 总线异常
├── rules/                           # 新：规则引擎
│   ├── __init__.py
│   ├── speech_controller.py       # 发言控制状态机
│   ├── admin_role.py              # 管理员权限
│   └── goal_mode.py               # Goal 模式
├── bridge/
│   └── hermes_bridge.py           # 适配常驻进程模式（重写）
├── ui/
│   ├── command_parser.py          # 扩展支持 /goal 等新命令
│   └── cli_renderer.py
├── config/
│   ├── settings.py
│   └── defaults.yaml
└── state/
    └── .gitkeep
```
