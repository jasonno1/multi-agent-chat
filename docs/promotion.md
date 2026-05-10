# 推广素材 — multi-agent-chat

## V2EX 帖子草稿

```
标题：用 Hermes Agent 做了一个「多 Agent 群聊」，支持 Claude/GPT 子进程自由对话

正文：

之前想给产品团队搭一个「AI 评审会」——让 GPT 和 Claude 对着一个需求互相辩论，看谁说得更有道理。

试了一圈市面上的多 Agent 框架，要么太重（要搭 Web 服务），要么进程隔离做得差（共享内存、互相干扰），要么没有发言控制（两个人同时说话）。

最后自己用 Hermes Agent 写了一个 CLI 版本：multi-agent-chat

核心特性：
- 每个 profile 是独立常驻进程，通过 Unix Domain Socket 通信
- 同一时间只有一人发言，以「我的发言结束。」结构化收尾
- 管理员权限：打断、优先发言、@ 分发任务
- Goal 模式：设定目标后，管理员自动拆解并分发子任务
- 记忆由 Hermes GBrain 统一管理，跨会话持久化

架构图：docs/architecture-diagram.html

使用示例：

# 1. 启动
python3 main.py

# 2. 拉人入群
/profile -t product-manager
/profile -t engineer

# 3. 设置管理员
/admin product-manager

# 4. 开始讨论
@product-manager 这个登录流程方案你怎么看？

# 5. 设置目标
/goal 实现用户注册功能
（管理员自动拆解任务并 @ 分发给 engineer、designer）

一句话：如果你需要在本地跑多个 AI Agent 协作讨论，这个 CLI 工具比搭 Web 服务简单 10 倍。

Repo: https://github.com/jasonno1/multi-agent-chat
```

---

## Twitter/X 英文推文草稿

```
Turned Hermes Agent into a multi-agent group chat CLI.

3 profiles (PM, Eng, Designer) arguing about a product spec in real terminal.

Architecture: isolated subprocesses + Unix Domain Socket + speech control FSM.

Built in a weekend. Open source.

github.com/jasonno1/multi-agent-chat

#AIagents #MultiAgent #HermesAgent
```

---

## 技术文章大纲（掘金/知乎）

```
标题：多 Agent 协作实战：子进程隔离 + UDS 通信 + 结构化发言控制

大纲：

1. 背景：为什么需要多 Agent 协作？
   - 单 Agent 的局限（一个模型解决不了复杂评审）
   - 多 Agent 的价值（分工、辩论、校验）

2. 核心设计
   2.1 进程隔离：每个 profile 是独立 Python 子进程
   2.2 进程间通信：Unix Domain Socket + select.select()
   2.3 发言控制：状态机 + END_MARKER
   2.4 记忆管理：Hermes GBrain profile 级别持久化

3. 关键代码解析
   - ChatBus 如何处理 10 种消息类型
   - SpeechController 三态流转
   - Hermes Bridge 如何调用子进程

4. 演示：让 Claude 和 GPT 评审一个产品需求

5. 下一步：可视化 Dashboard、语音输入输出
```

---

## 即刻/微博草稿

```
做了个小工具：用 Hermes Agent 让 GPT 和 Claude 在终端里「开会」。

产品经理提需求，工程师做技术评估，设计师给反馈——三个人真的在辩论，不是轮流念稿。

用了 Unix Domain Socket 做进程通信，END_MARKER 控制发言顺序，GBrain 管理跨会话记忆。

如果你也在研究 Multi-Agent，这套架构值得参考。
Demo 在 GitHub：github.com/jasonno1/multi-agent-chat
```
