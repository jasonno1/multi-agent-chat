"""Main orchestrator for the multi-agent chat system.

Replaces the old main.py MultiAgentChat class. Manages:
  - ChatBus socket server (background thread)
  - Agent process lifecycle (spawn, monitor, terminate)
  - Speech control via SpeechController
  - Admin role and goal mode
  - Message routing between user and agents
"""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.profile_manager import ProfileManager, Profile
from core.state_manager import StateManager
from core.context_builder import ContextBuilder
from bus.chat_bus import ChatBus
from bus.protocol import MessageType, Message, parse_message, make_message
from rules.speech_controller import SpeechController, SpeechState
from rules.admin_role import AdminRole
from rules.goal_mode import GoalMode
from ui.cli_renderer import CLIRenderer
from ui.command_parser import CommandParser, Command


class Orchestrator:
    """Main orchestrator for the multi-agent chat system."""

    END_MARKER = "我的发言结束。"

    def __init__(self):
        self.renderer = CLIRenderer()
        self.parser = CommandParser()
        self.profile_manager = ProfileManager()
        self.state_manager = StateManager()

        # Session
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.running = True
        self.mode: str = "free"

        # Speech control
        self.speech = SpeechController()
        self.speech.on_speech_end = self._on_agent_speech_end

        # Admin & Goal
        self.admin = AdminRole()
        self.goal = GoalMode()
        self.goal_task_counter = 0

        # Chat bus
        self.bus = ChatBus(self.session_id)
        self.bus.on_message = self._on_bus_message
        self.bus.on_join = self._on_agent_join
        self.bus.on_leave = self._on_agent_leave

        # Agent processes
        self._agent_processes: dict[str, subprocess.Popen] = {}
        self._agent_ready: set[str] = set()

        # Conversation history
        self.conversation_history: list[dict] = []

        # Speaking order
        self.speaking_order: dict[str, int] = {}

        # Bus thread
        self._bus_thread: Optional[threading.Thread] = None

        # Speech timeout management
        self._speech_timers: dict[str, threading.Timer] = {}
        self._max_speech_time: int = 120  # seconds

        # Agent heartbeat health check
        self._heartbeat_timers: dict[str, threading.Timer] = {}
        self._agent_last_seen: dict[str, float] = {}  # profile_name -> timestamp
        self._heartbeat_interval: int = 30  # seconds between heartbeats
        self._heartbeat_timeout: int = 90  # seconds without heartbeat = dead

    # ── Public API ─────────────────────────────────────────

    def run(self):
        """Start the orchestrator and enter the REPL loop."""
        self.renderer.banner()

        # Start the chat bus
        if not self.bus.start():
            print("Failed to start chat bus.", file=sys.stderr)
            return

        # Start bus event loop in background thread
        self._bus_thread = threading.Thread(target=self.bus.run_loop, daemon=True)
        self._bus_thread.start()

        # Try to restore previous session
        self._try_restore()

        # Main REPL
        try:
            self._repl()
        finally:
            self._shutdown()

    def invite_profile(self, name: str, as_admin: bool = False) -> bool:
        """Invite a profile to the group chat.

        Spawns an independent agent process for the profile.
        """
        all_profiles = {p.name for p in self.profile_manager.list_all()}
        if name not in all_profiles:
            self.renderer.error(f"Profile '{name}' not found.")
            return False

        if name in self._agent_processes:
            self.renderer.warning(f"{name} is already in the chat.")
            return False

        # Load profile info for display
        profile = self.profile_manager.load(name)
        display_name = (profile.display_name if profile else name) or name

        # Determine speaking order
        order = self.speaking_order.get(name, 0)

        # Set admin if needed
        if as_admin:
            self.admin.set_admin(name)
            self.speech.admins.add(name)

        # Add to speech controller members
        self.speech.members.append(name)
        if self.speaking_order:
            self.speech.speaking_order = self.speaking_order

        # Spawn agent process
        process = self._spawn_agent(name, is_admin=as_admin, speaking_order=order)
        if process:
            self._agent_processes[name] = process
            n = len(self._agent_processes)
            role = "管理员" if as_admin else ""
            self.renderer.success(f"{display_name} ({name}) {role} 已加入群聊。({n} 成员)")
            return True
        else:
            self.renderer.error(f"无法启动 {name} 进程。")
            return False

    def kick_profile(self, name: str) -> bool:
        """Remove a profile from the group chat."""
        if name not in self._agent_processes:
            self.renderer.warning(f"{name} is not in the chat.")
            return False

        # Notify agent to disconnect
        if self.bus.is_connected(name):
            self.bus.send_to(name, make_message(MessageType.SHUTDOWN, from_="orchestrator"))

        # Terminate process
        proc = self._agent_processes.pop(name, None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # Clean up state
        self.speech.members.remove(name)
        self.speech.admins.discard(name)
        self.speaking_order.pop(name, None)
        if name in self._agent_ready:
            self._agent_ready.discard(name)
        if self.admin.is_admin(name):
            self.admin.remove_admin()

        n = len(self._agent_processes)
        profile = self.profile_manager.load(name)
        display_name = (profile.display_name if profile else name) or name
        self.renderer.success(f"{display_name} 已退出群聊。({n} 成员)")

        return True

    def set_mode(self, mode: str):
        """Set the conversation mode."""
        valid_modes = {"free", "mention", "ordered"}
        if mode not in valid_modes:
            self.renderer.error(f"无效模式: {mode}。可选: {', '.join(valid_modes)}")
            return

        if mode == "ordered" and not self.speaking_order:
            self.renderer.warning("尚未设置发言顺序。")
            return

        self.mode = mode
        self.renderer.success(f"模式切换为: {mode.upper()}")

    def set_speaking_order(self, name: str, order: int, force: bool = False):
        """Set a profile's speaking order."""
        if name not in self._agent_processes:
            self.renderer.error(f"{name} 不在群聊中。")
            return
        if order < 1:
            self.renderer.error("序号必须 >= 1。")
            return

        if not force:
            for ename, eorder in self.speaking_order.items():
                if eorder == order and ename != name:
                    self.renderer.warning(f"位置 {order} 已被 {ename} 占用。使用 -f 强制覆盖。")
                    return

        self.speaking_order[name] = order
        self.speech.speaking_order = self.speaking_order
        self.mode = "ordered"
        profile = self.profile_manager.load(name)
        display_name = (profile.display_name if profile else name) or name
        self.renderer.success(f"{display_name} 发言顺序: #{order}。模式: ORDERED。")

    def clear_order(self):
        """Clear speaking order."""
        self.speaking_order = {}
        self.speech.speaking_order = {}
        self.mode = "free"
        self.renderer.success("发言顺序已清除。模式: FREE。")

    def set_goal(self, title: str):
        """Set a goal for the group chat."""
        if not self.admin.has_admin:
            self.renderer.warning("需要先设置管理员。使用 /admin <name> 设置。")
            return

        self.goal.set_goal(title)
        self.renderer.success(f"🎯 目标已设定: {title}")

        # Send goal to admin
        if self.bus.is_connected(self.admin.admin_name):
            msg = make_message(
                MessageType.GOAL_SET,
                from_="user",
                to=self.admin.admin_name,
                goal=title,
            )
            self.bus.send(msg)

            # Grant admin speech to decompose goal
            admin_msg = make_message(
                MessageType.GRANT_SPEECH,
                from_="orchestrator",
                to=self.admin.admin_name,
                text=f"请将目标拆解为子任务，并 @ 合适的成员分配任务。\n\n目标: {title}",
                speaker="user",
            )
            self.speech.grant_speech(self.admin.admin_name, "goal_decomposition")
            self.bus.send(admin_msg)

        self.renderer.success(f"已通知管理员 {self.admin.admin_name} 拆解目标。")

    def send_message(self, text: str, mentions: list[str] = None):
        """Handle a user message and route it to appropriate agents."""
        if mentions is None:
            mentions = self.parser.extract_mentions(text)

        # Save to history
        self.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "speaker": "You",
            "message": text,
        })

        # Determine who should respond
        member_names = list(self._agent_processes.keys())
        if not member_names:
            self.renderer.warning("群聊中没有成员。使用 /invite <name> 邀请。")
            return

        if self.mode == "mention" and not mentions:
            self.renderer.warning("MENTION 模式下需要 @ 成员才能发言。")
            return

        speakers = self.speech.resolve_speakers(mentions, member_names)

        # Show who will speak
        speaker_displays = []
        for name in speakers:
            profile = self.profile_manager.load(name)
            d = (profile.display_name if profile else name) or name
            speaker_displays.append(d)

        # Grant speech to first speaker
        first_speaker = speakers[0]

        # Broadcast the user message to all agents
        broadcast = make_message(
            MessageType.MESSAGE,
            from_="user",
            to="*",
            text=text,
            mentions=mentions,
        )
        self.bus.broadcast(broadcast)

        # Grant speech to the first speaker
        grant = make_message(
            MessageType.GRANT_SPEECH,
            from_="orchestrator",
            to=first_speaker,
            text=text,
            speaker="用户",
        )
        self.speech.grant_speech(first_speaker, "user_message")
        self.bus.send(grant)
        self._start_speech_timer(first_speaker)

        # Enqueue remaining speakers
        for speaker in speakers[1:]:
            self.speech.enqueue(speaker)

    def interrupt(self, target: str = ""):
        """Interrupt the current speaker (admin/user only)."""
        if self.speech.state != SpeechState.SPEAKING:
            self.renderer.warning("当前没有人正在发言。")
            return

        speaker = target or self.speech.current_speaker
        if not speaker:
            return

        # Send interrupt message
        msg = make_message(
            MessageType.INTERRUPT,
            from_="user",
            to=speaker,
        )
        self.bus.send(msg)
        self.speech.interrupt(speaker, "user")

        profile = self.profile_manager.load(speaker)
        display_name = (profile.display_name if profile else speaker) or speaker
        self.renderer.warning(f"已打断 {display_name} 的发言。")

    # ── Agent Process Management ───────────────────────────

    def _spawn_agent(
        self, profile_name: str, is_admin: bool = False, speaking_order: int = 0
    ) -> Optional[subprocess.Popen]:
        """Spawn an independent agent process."""
        runner_path = Path(__file__).parent.parent / "agents" / "agent_runner.py"
        cmd = [
            sys.executable,
            str(runner_path),
            profile_name,
            self.session_id,
            str(self.bus.socket_path),
        ]
        if is_admin:
            cmd.append("--admin")
        if speaking_order > 0:
            cmd.extend(["--order", str(speaking_order)])

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return process
        except Exception:
            return None

    # ── Bus Event Handlers ─────────────────────────────────

    def _on_bus_message(self, msg: Message):
        """Handle a message from the chat bus."""
        handlers = {
            MessageType.RESPONSE: self._on_response,
            MessageType.END_OF_SPEECH: self._on_end_of_speech,
            MessageType.INTERRUPTED: self._on_interrupted,
            MessageType.STATUS_REPLY: self._on_status_reply,
        }
        handler = handlers.get(msg.type)
        if handler:
            handler(msg)

    def _on_agent_join(self, profile_name: str):
        """Called when an agent connects to the bus."""
        self._agent_ready.add(profile_name)
        self._start_heartbeat_check(profile_name)

        # Send welcome message with context
        profile = self.profile_manager.load(profile_name)
        display_name = (profile.display_name if profile else profile_name)

        welcome_payload = {
            "members": list(self._agent_processes.keys()),
            "mode": self.mode,
            "is_admin": self.admin.is_admin(profile_name),
            "speaking_order": self.speaking_order,
            "history": self.conversation_history[-10:],
            "rules": self._build_group_rules(profile_name),
        }

        welcome = make_message(
            MessageType.WELCOME,
            from_="orchestrator",
            to=profile_name,
            **welcome_payload,
        )
        self.bus.send(welcome)

    def _on_agent_leave(self, profile_name: str):
        """Called when an agent disconnects."""
        self._agent_ready.discard(profile_name)
        self._cancel_speech_timer(profile_name)
        if profile_name in self._agent_last_seen:
            del self._agent_last_seen[profile_name]

    def _on_response(self, msg: Message):
        """Handle a response from an agent."""
        profile_name = msg.from_
        self._on_agent_heartbeat(profile_name)  # Reset heartbeat timer
        text = msg.payload.get("text", "")

        profile = self.profile_manager.load(profile_name)
        display_name = (profile.display_name if profile else profile_name) or profile_name

        # Display the response
        self.renderer.profile_message(display_name, profile_name, text)

        # Save to history
        self.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "speaker": display_name,
            "message": text,
        })

        # Check for @mentions in the response
        mentions = self.parser.extract_mentions(text)
        valid_mentions = [m for m in mentions if m in self._agent_processes and m != profile_name]
        if valid_mentions:
            for mentioned in valid_mentions:
                self.renderer.success(f"-> @{mentioned} 被提及")
                # Enqueue mentioned agent to speak
                self.speech.enqueue(mentioned, priority=True)

    def _on_end_of_speech(self, msg: Message):
        """Handle end of speech signal from an agent."""
        profile_name = msg.from_
        self._cancel_speech_timer(profile_name)  # Cancel timeout timer
        self.speech.end_speech(profile_name)

        # The speech controller callback (_on_agent_speech_end) handles
        # activating the next speaker in the queue.

    def _on_agent_speech_end(self, profile_name: str):
        """Called by speech controller when an agent finishes speaking."""
        # Check if there's a next speaker in the queue
        next_speaker = self.speech.dequeue()
        if next_speaker and next_speaker in self._agent_processes:
            # Send context about what was just said to the next speaker
            last_msg = self.conversation_history[-1] if self.conversation_history else {"message": ""}
            grant = make_message(
                MessageType.GRANT_SPEECH,
                from_="orchestrator",
                to=next_speaker,
                text=last_msg.get("message", ""),
                speaker=profile_name,
            )
            self.speech.grant_speech(next_speaker, "queue")
            self.bus.send(grant)

    def _on_interrupted(self, msg: Message):
        """Handle interrupted signal from an agent."""
        # Agent acknowledges it was interrupted
        pass

    def _on_status_reply(self, msg: Message):
        """Handle a status message from an agent."""
        # For debugging
        pass

    # ── REPL ───────────────────────────────────────────────

    def _repl(self):
        """Main REPL loop."""
        while self.running:
            try:
                user_input = input(self.renderer.prompt())
            except (KeyboardInterrupt, EOFError):
                print()
                break

            if not user_input.strip():
                continue

            parsed = self.parser.parse(user_input)

            if parsed.is_command:
                self._handle_command(parsed)
            else:
                self.send_message(parsed.raw_text, parsed.mentions)

    # ── Command Handling ───────────────────────────────────

    def _handle_command(self, parsed):
        cmd = parsed.command.command
        args = parsed.command.args

        handlers = {
            Command.PROFILE_LIST: self._cmd_list,
            Command.PROFILE_INVITE: self._cmd_invite,
            Command.PROFILE_KICK: self._cmd_kick,
            Command.PROFILE_T_LIST: self._cmd_member_list,
            Command.PROFILE_ORDER: self._cmd_order,
            Command.PROFILE_ORDER_OFF: self._cmd_order_off,
            Command.PROFILE_MODE: self._cmd_mode,
            Command.HELP: lambda: self.renderer.help_text(),
            Command.QUIT: self._cmd_quit,
            Command.ADMIN: self._cmd_admin,
            Command.GOAL: self._cmd_goal,
            Command.INTERRUPT: self._cmd_interrupt,
        }

        handler = handlers.get(cmd)
        if handler:
            handler(**args) if args else handler()
        else:
            self.renderer.warning("未知命令。输入 /help 查看帮助。")

    def _cmd_list(self):
        profiles = self.profile_manager.list_all()
        self.renderer.profile_list(profiles)

    def _cmd_invite(self, name: str):
        self.invite_profile(name)

    def _cmd_kick(self, name: str):
        self.kick_profile(name)

    def _cmd_member_list(self):
        members = []
        for name in self._agent_processes:
            profile = self.profile_manager.load(name)
            display_name = (profile.display_name if profile else name)
            role = (profile.role if profile else "")
            # Create a simple profile-like object for the renderer
            from core.profile_manager import Profile as P
            m = P(name=name, display_name=display_name, role=role)
            if self.admin.is_admin(name):
                m.role = f"管理员 | {role}"
            members.append(m)
        self.renderer.member_list(members, self.mode, self.speaking_order)

    def _cmd_order(self, name: str, order: int, force: bool = False):
        self.set_speaking_order(name, order, force)

    def _cmd_order_off(self):
        self.clear_order()

    def _cmd_mode(self, mode: str):
        self.set_mode(mode)

    def _cmd_quit(self):
        self._save_state()
        self.running = False
        print(f"\n  {self.renderer.C_DIM}再见! (会话已保存){self.renderer.C_RESET}\n")

    def _cmd_admin(self, name: str):
        """Set a profile as admin."""
        if name not in self._agent_processes:
            self.renderer.error(f"请先邀请 {name} 进入群聊。")
            return
        self.invite_profile(name, as_admin=name)  # re-invite doesn't work, just set admin
        # Actually just set admin directly
        self.admin.set_admin(name)
        self.speech.admins.add(name)
        profile = self.profile_manager.load(name)
        display_name = (profile.display_name if profile else name) or name
        self.renderer.success(f"{display_name} 已被设为群管理员。")

    def _cmd_goal(self, title: str = ""):
        """Set or show the group goal."""
        if not title:
            if self.goal.active:
                self.renderer.success(self.goal.get_progress())
            else:
                self.renderer.warning("当前没有活跃目标。使用 /goal <目标描述> 设定。")
            return
        self.set_goal(title)

    def _cmd_interrupt(self):
        self.interrupt()

    # ── Session ────────────────────────────────────────────

    def _try_restore(self):
        """Try to restore a previous session."""
        data = self.state_manager.load()
        if not data:
            return

        members = data.get("members", [])
        if not members:
            return

        if not sys.stdin.isatty():
            self._do_restore(data)
            return

        print(f"\n  发现之前的会话 ({len(members)} 位成员)。")
        try:
            choice = input(f"  恢复? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return

        if choice and choice != 'y':
            self.state_manager.clear()
            return

        self._do_restore(data)

    def _do_restore(self, data: dict):
        """Restore session from saved data."""
        members = data.get("members", [])
        admin_name = data.get("admin", "")

        for member_info in members:
            name = member_info.get("name", "")
            if name:
                is_admin = (name == admin_name)
                self.invite_profile(name, as_admin=is_admin)

        self.mode = data.get("mode", "free")
        self.speaking_order = data.get("speaking_order", {})
        self.speech.speaking_order = self.speaking_order

        goal_data = data.get("goal", {})
        if goal_data:
            self.goal.set_goal(goal_data.get("title", ""))

        history = data.get("history", [])
        if history:
            self.conversation_history = history
            print(f"  已恢复 {len(history)} 条对话记录。\n")

    def _save_state(self):
        """Save current session state.
        
        Saves conversation history as JSON for session persistence.
        Admin can use /log to review session history.
        """
        data = {
            "session_id": self.session_id,
            "saved_at": time.time(),
            "members": [{"name": name} for name in self._agent_processes],
            "admin": self.admin.admin_name,
            "mode": self.mode,
            "speaking_order": self.speaking_order,
            "history": self.conversation_history[-50:],
            "goal": {
                "title": self.goal.current_goal.title,
                "tasks": self.goal.current_goal.tasks,
            } if self.goal.current_goal else {},
        }
        self.state_manager.save(data)

    # ── Speech Timeout Management ─────────────────────────

    def _start_speech_timer(self, profile_name: str):
        """Start a timer for the current speaker. If no END_OF_SPEECH received, force skip."""
        # Cancel any existing timer for this speaker
        if profile_name in self._speech_timers:
            self._speech_timers[profile_name].cancel()
        
        timer = threading.Timer(
            self._max_speech_time,
            self._handle_speech_timeout,
            args=(profile_name,)
        )
        self._speech_timers[profile_name] = timer
        timer.start()

    def _cancel_speech_timer(self, profile_name: str):
        """Cancel the speech timer when agent sends END_OF_SPEECH."""
        if profile_name in self._speech_timers:
            self._speech_timers[profile_name].cancel()
            del self._speech_timers[profile_name]

    def _handle_speech_timeout(self, profile_name: str):
        """Handle speech timeout - force interrupt and advance to next speaker."""
        if self.speech.current_speaker != profile_name:
            return  # Already moved on
        
        self.renderer.warning(f"⏱ {profile_name} 响应超时（>{self._max_speech_time}s），强制跳过。")
        
        # Send interrupt to stuck agent
        self.bus.send_to(profile_name, make_message(
            MessageType.INTERRUPT,
            from_="orchestrator",
            payload={"reason": "timeout"}
        ))
        
        # Reset speech state
        self.speech.state = __import__('rules.speech_controller', fromlist=['SpeechState']).SpeechState.IDLE
        self.speech.current_speaker = None
        
        # Advance to next speaker
        self._advance_to_next_speaker()

    def _advance_to_next_speaker(self):
        """Grant speech to the next speaker in queue, if any."""
        next_speaker = self.speech.dequeue()
        if next_speaker and next_speaker in self._agent_processes:
            last_msg = self.conversation_history[-1] if self.conversation_history else {"message": ""}
            grant = make_message(
                MessageType.GRANT_SPEECH,
                from_="orchestrator",
                to=next_speaker,
                text=last_msg.get("message", ""),
                speaker=self.speech.current_speaker or "previous",
            )
            self.speech.grant_speech(next_speaker, "queue")
            self.bus.send(grant)
            self._start_speech_timer(next_speaker)
        else:
            # No more speakers, speech queue empty
            pass

    # ── Agent Heartbeat Health Check ──────────────────────

    def _start_heartbeat_check(self, profile_name: str):
        """Start periodic heartbeat check for an agent."""
        self._agent_last_seen[profile_name] = time.time()
        
        timer = threading.Timer(
            self._heartbeat_interval,
            self._check_heartbeat,
            args=(profile_name,)
        )
        self._heartbeat_timers[profile_name] = timer
        timer.start()

    def _check_heartbeat(self, profile_name: str):
        """Check if agent is still alive. Respawn if not responding."""
        if not self.running:
            return
        
        last_seen = self._agent_last_seen.get(profile_name, 0)
        if time.time() - last_seen > self._heartbeat_timeout:
            self.renderer.warning(f"⚠️ {profile_name} 无心跳响应，尝试重启...")
            self._respawn_agent(profile_name)
        else:
            # Schedule next check
            timer = threading.Timer(
                self._heartbeat_interval,
                self._check_heartbeat,
                args=(profile_name,)
            )
            self._heartbeat_timers[profile_name] = timer
            timer.start()

    def _respawn_agent(self, profile_name: str):
        """Respawn a crashed or unresponsive agent."""
        # Remove old process
        old_proc = self._agent_processes.pop(profile_name, None)
        if old_proc:
            try:
                old_proc.terminate()
                old_proc.wait(timeout=2)
            except Exception:
                try:
                    old_proc.kill()
                except Exception:
                    pass
        
        # Remove from ready set
        self._agent_ready.discard(profile_name)
        
        # Remove from speech queue
        if profile_name in self.speech.speech_queue:
            self.speech.speech_queue.remove(profile_name)
        
        # Respawn
        is_admin = self.admin.is_admin(profile_name)
        order = self.speaking_order.get(profile_name, 0)
        
        new_proc = self._spawn_agent(profile_name, is_admin=is_admin, speaking_order=order)
        if new_proc:
            self._agent_processes[profile_name] = new_proc
            self._start_heartbeat_check(profile_name)
            self.renderer.success(f"✅ {profile_name} 已重启。")
        else:
            self.renderer.error(f"❌ {profile_name} 重启失败。")

    def _on_agent_heartbeat(self, profile_name: str):
        """Called when agent sends a heartbeat/status update."""
        self._agent_last_seen[profile_name] = time.time()

    # ── Shutdown ───────────────────────────────────────────

    def _shutdown(self):
        """Graceful shutdown."""
        self._save_state()
        self.running = False

        # Cancel all timers
        for t in list(self._speech_timers.values()) + list(self._heartbeat_timers.values()):
            t.cancel()
        self._speech_timers.clear()
        self._heartbeat_timers.clear()

        # Shutdown the bus
        self.bus.stop()

        # Shutdown all agent processes gracefully
        for name in list(self._agent_processes.keys()):
            proc = self._agent_processes[name]
            try:
                proc.terminate()
            except Exception:
                pass

        # Wait for graceful shutdown (up to 10 seconds total)
        deadline = time.time() + 10
        for name in list(self._agent_processes.keys()):
            proc = self._agent_processes[name]
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            self._agent_processes.pop(name, None)

        # Force kill any remaining processes
        for name in list(self._agent_processes.keys()):
            proc = self._agent_processes.pop(name, None)
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass

        self._agent_processes.clear()

    def _build_group_rules(self, profile_name: str) -> str:
        """Build group chat rules text for a profile."""
        rules = f"""# 群聊规则

你是群聊中的参与者。

## 发言规则 (必须严格遵守)
1. **禁止 Think**: 不得输出任何内部推理、思考过程。只输出最终结论。
2. **发言结束标记**: 每次发言必须以"{self.END_MARKER}"结尾。
3. **禁止打断**: 只有获得发言权时才能发言。
4. **输出干净**: 不输出过程性内容（如"正在搜索"、"正在分析"等）。
5. **精炼简洁**: 直接说结论，1-3 段即可。"""

        if self.admin.is_admin(profile_name):
            rules += """

## 管理员权限
- 可以 @ 任何成员分配任务
- 可以在必要时打断其他成员的发言
- /goal 模式下负责拆解目标并分发任务"""

        return rules
