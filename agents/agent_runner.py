"""Persistent profile agent wrapper process.

Each agent runs as a separate Python process that:
1. Connects to the ChatBus via Unix Domain Socket
2. Uses Hermes GBrain for persistent memory (profile-level)
3. Calls `hermes chat -q` for AI responses when granted speech
4. Respects speech control: only responds when given speaking rights
5. Ends every response with the structured marker: 我的发言结束。
"""

import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bus.protocol import MessageType, Message, parse_message, make_message
from bridge.hermes_bridge import HermesBridge
from core.context_builder import ContextBuilder
from core.profile_manager import ProfileManager


class ProfileAgent:
    """A persistent agent that represents one profile in the group chat."""

    END_MARKER = "我的发言结束。"

    def __init__(
        self,
        profile_name: str,
        session_id: str,
        socket_path: str,
        is_admin: bool = False,
        speaking_order: int = 0,
    ):
        self.profile_name = profile_name
        self.session_id = session_id
        self.socket_path = socket_path
        self.is_admin = is_admin
        self.speaking_order = speaking_order

        # Modules
        self.profile_manager = ProfileManager()
        self.profile = self.profile_manager.load(profile_name)
        self.context_builder = ContextBuilder()
        self.hermes = HermesBridge()

        # State
        self._socket: Optional[socket.socket] = None
        self._running = True
        self._has_speech_right = False
        self._interrupted = False
        self._conversation_history: list[dict] = []

        # Display
        self.display_name = self.profile.display_name if self.profile else profile_name

    # ── Lifecycle ──────────────────────────────────────────

    def run(self):
        """Main agent loop."""
        if not self._connect():
            print(f"[{self.display_name}] Failed to connect to chat bus.", file=sys.stderr)
            return

        self._join()

        while self._running:
            try:
                msg = self._recv()
                if msg is None:
                    time.sleep(0.1)
                    continue
                self._handle_message(msg)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[{self.display_name}] Error: {e}", file=sys.stderr)
                time.sleep(0.5)

        self._disconnect()

    # ── Message Handling ───────────────────────────────────

    def _handle_message(self, msg: Message):
        handlers = {
            MessageType.WELCOME: self._on_welcome,
            MessageType.MESSAGE: self._on_chat_message,
            MessageType.TASK: self._on_task,
            MessageType.GRANT_SPEECH: self._on_grant_speech,
            MessageType.INTERRUPT: self._on_interrupt,
            MessageType.GOAL_SET: self._on_goal_set,
            MessageType.SHUTDOWN: self._on_shutdown,
        }
        handler = handlers.get(msg.type)
        if handler:
            handler(msg)

    def _on_welcome(self, msg: Message):
        """Received welcome from orchestrator with group chat context."""
        payload = msg.payload
        members = payload.get("members", [])
        mode = payload.get("mode", "free")
        rules = payload.get("rules", "")

        self._conversation_history = payload.get("history", [])

        # Display join notification (for debugging)
        role = "管理员" if self.is_admin else "成员"
        self._send_status(f"已加入群聊 [{role}]")

    def _on_chat_message(self, msg: Message):
        """Received a chat message from another profile or user."""
        speaker = msg.from_
        text = msg.payload.get("text", "")

        # Record in conversation history
        self._conversation_history.append({"speaker": speaker, "message": text})

        # If we have speech right, respond
        if self._has_speech_right:
            self._respond(text, speaker)

    def _on_task(self, msg: Message):
        """Received a task assignment (from admin or user)."""
        task_id = msg.payload.get("task_id", "")
        goal = msg.payload.get("goal", "")
        requirements = msg.payload.get("requirements", [])
        sender = msg.from_

        # Record in conversation history
        self._conversation_history.append({
            "speaker": sender,
            "message": f"[任务] {goal}",
        })

        # If we have speech right, respond to the task
        if self._has_speech_right:
            task_text = f"任务: {goal}\n要求: {', '.join(requirements)}"
            self._respond(task_text, sender, is_task=True)

    def _on_grant_speech(self, msg: Message):
        """Orchestrator grants us speaking rights."""
        self._has_speech_right = True
        self._interrupted = False

        # The message payload may contain the text we should respond to
        text = msg.payload.get("text", "")
        speaker = msg.payload.get("speaker", "user")

        if text:
            self._respond(text, speaker)

    def _on_interrupt(self, msg: Message):
        """We're being interrupted - stop speaking immediately."""
        if self._has_speech_right:
            self._has_speech_right = False
            self._interrupted = True
            # Signal that we've been interrupted
            reply = make_message(
                MessageType.INTERRUPTED,
                from_=self.profile_name,
                to=msg.from_,
            )
            self._send(reply)

    def _on_goal_set(self, msg: Message):
        """A goal has been set for the group chat."""
        goal = msg.payload.get("goal", "")
        self._conversation_history.append({
            "speaker": "system",
            "message": f"[目标] {goal}",
        })

    def _on_shutdown(self, _msg: Message):
        """Orchestrator is shutting down."""
        self._running = False
        self._disconnect()

    # ── Response Generation ────────────────────────────────

    def _respond(self, text: str, speaker: str, is_task: bool = False):
        """Generate and send a response via hermes."""
        if not self.profile:
            self._send_response("(无法加载 profile)", speaker)
            self._end_speech()
            return

        # Build the prompt
        prompt = self._build_prompt(text, speaker, is_task)

        # Get response from hermes
        response = self.hermes.query(self.profile_name, self.profile_name, prompt)

        if response:
            # Clean response: remove think blocks and internal reasoning
            response = self._clean_response(response)
            # Ensure it ends with the end marker
            if not response.rstrip().endswith(self.END_MARKER):
                response = response.rstrip() + f"\n{self.END_MARKER}"
        else:
            response = f"(无法生成回复) {self.END_MARKER}"

        # Save to conversation history
        self._conversation_history.append({
            "speaker": self.display_name,
            "message": response,
        })

        # Send the response
        self._send_response(response, speaker)

        # Release speech
        self._end_speech()

    def _build_prompt(self, text: str, speaker: str, is_task: bool = False) -> str:
        """Build the context for hermes response."""
        parts = []

        # 1. Identity & Rules
        parts.append(self._build_system_prompt())

        # 2. Conversation history
        if self._conversation_history:
            parts.append(self._build_history())

        # 3. Current message
        if is_task:
            parts.append(f"## 任务消息 (来自 {speaker})\n{text}")
        else:
            parts.append(f"## 当前消息 (来自 {speaker})\n{text}")

        # 4. Response instruction
        parts.append(self._build_instruction(is_task))

        return "\n\n".join(parts)

    def _build_system_prompt(self) -> str:
        """Build the system/rule prompt for this agent."""
        name = self.display_name
        role = "管理员" if self.is_admin else "成员"
        soul = self.profile.soul_content if self.profile else ""

        # Strip SOUL.md frontmatter for the prompt
        if soul.startswith("---"):
            idx = soul.find("---", 3)
            if idx > 0:
                soul = soul[idx + 3:].strip()

        rules = f"""# 群聊规则

你是 **{name}**，正在参与一个多智能体群聊。

## 你的身份
- Profile: {self.profile_name}
- 权限: {role}

## 发言规则 (必须严格遵守)
1. **禁止 Think**: 不得输出任何内部推理、思考过程。只输出最终结论。
2. **发言结束标记**: 每次发言必须以"{self.END_MARKER}"结尾。在此之前的任何内容都是你的发言。
3. **禁止打断**: 只有当系统要求你发言时，你才能发言。不要主动发起对话。
4. **输出干净**: 不输出"正在搜索"、"正在分析"等过程性内容。
5. **精炼简洁**: 直接说结论，1-3段即可。"""
        if self.is_admin:
            rules += """
## 管理员权限
- 你可以 @ 任何成员分配任务
- 你可以在必要时打断其他成员的发言
- 你有权设置发言顺序和模式
- 在 /goal 模式下，你负责拆解目标并分发任务"""

        return f"{soul}\n\n{rules}"

    def _build_history(self) -> str:
        """Build conversation history section."""
        recent = self._conversation_history[-20:]
        lines = ["## 对话记录"]
        for entry in recent:
            s = entry.get("speaker", "unknown")
            m = entry.get("message", "")
            if len(m) > 500:
                m = m[:500] + "..."
            lines.append(f"**{s}**: {m}")
        return "\n".join(lines)

    def _build_instruction(self, is_task: bool = False) -> str:
        """Build the response instruction."""
        timeout_note = "（请在 90 秒内完成回复，超时将被强制跳过）"
        if is_task:
            return f"请完成上述任务。使用你可以用的工具获取信息。完成后以'{self.END_MARKER}'结尾。{timeout_note}"
        return f"请回复上述消息。保持简洁。以'{self.END_MARKER}'结尾。{timeout_note}"

    def _clean_response(self, text: str) -> str:
        """Remove think blocks and internal reasoning from response.
        
        Only removes explicit XML-style thinking tags. Does NOT filter
        normal conversational expressions like '我认为' or '让我想想'.
        """
        # Remove explicit thinking XML tags (blocks only)
        text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<think>.*?</plan>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<think>.*?', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'</session>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<think>.*?</>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<plans>.*?</plans>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<reflection>.*?</reflection>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove trailing progress indicators (...) at end of lines
        text = re.sub(r'\.{3,}($', r'.\1', text, flags=re.MULTILINE)

        # Remove inline tool call progress text but keep the line
        text = re.sub(r'\([正在都]*(?:搜索|分析|查询|加载|处理)中[.。]*\)', '', text)

        return text.strip()

    def _send_response(self, text: str, to: str):
        """Send a response message."""
        msg = make_message(
            MessageType.RESPONSE,
            from_=self.profile_name,
            to=to,
            text=text,
            display_name=self.display_name,
        )
        self._send(msg)

    def _end_speech(self):
        """Signal end of speech."""
        self._has_speech_right = False
        self._send(make_message(
            MessageType.END_OF_SPEECH,
            from_=self.profile_name,
        ))

    def _send_status(self, text: str):
        """Send a status update (not a chat message)."""
        self._send(make_message(
            MessageType.STATUS_REPLY,
            from_=self.profile_name,
            text=text,
        ))

    def _send(self, msg: Message):
        """Send a message on the socket."""
        if self._socket:
            try:
                self._socket.sendall((msg.to_json() + "\n").encode("utf-8"))
            except Exception:
                pass

    def _recv(self) -> Optional[Message]:
        """Receive a message from the socket (non-blocking)."""
        if not self._socket:
            return None
        try:
            self._socket.settimeout(0.5)
            raw = self._socket.recv(65536)
            if not raw:
                self._running = False
                return None
            line = raw.decode("utf-8").strip()
            return parse_message(line) if line else None
        except socket.timeout:
            return None
        except Exception:
            self._running = False
            return None

    # ── Connection ─────────────────────────────────────────

    def _connect(self) -> bool:
        """Connect to the chat bus."""
        for attempt in range(30):  # retry for up to 15s
            try:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._socket.connect(self.socket_path)
                self._socket.setblocking(True)
                return True
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.5)
                continue
            except Exception:
                return False
        return False

    def _join(self):
        """Send JOIN message to register with the orchestrator."""
        self._send(make_message(
            MessageType.JOIN,
            from_=self.profile_name,
            is_admin=self.is_admin,
            speaking_order=self.speaking_order,
            display_name=self.display_name,
        ))

    def _disconnect(self):
        """Disconnect from the chat bus."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None


# ── Process Entry Point ────────────────────────────────────

def start_agent_process(
    profile_name: str,
    session_id: str,
    socket_path: str,
    is_admin: bool = False,
    speaking_order: int = 0,
):
    """Entry point for a standalone agent process.

    Called via: python -m agents.agent_runner <profile_name> <session_id> <socket_path> [--admin] [--order N]
    """
    agent = ProfileAgent(
        profile_name=profile_name,
        session_id=session_id,
        socket_path=socket_path,
        is_admin=is_admin,
        speaking_order=speaking_order,
    )
    agent.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Agent Chat Profile Runner")
    parser.add_argument("profile_name", help="Hermes profile name")
    parser.add_argument("session_id", help="Session ID")
    parser.add_argument("socket_path", help="Path to chat bus socket")
    parser.add_argument("--admin", action="store_true", help="Grant admin privileges")
    parser.add_argument("--order", type=int, default=0, help="Speaking order")

    args = parser.parse_args()
    start_agent_process(
        profile_name=args.profile_name,
        session_id=args.session_id,
        socket_path=args.socket_path,
        is_admin=args.admin,
        speaking_order=args.order,
    )
