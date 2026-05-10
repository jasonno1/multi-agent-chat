"""Integration tests for the Multi-Agent Chat v2.0 core modules.

Tests the protocol, speech controller, admin, goal mode, and memory
modules without requiring Hermes to be installed.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_protocol():
    """Test message protocol serialization."""
    from bus.protocol import MessageType, Message, parse_message, make_message

    # Test message creation
    msg = make_message(MessageType.JOIN, from_="test_agent", is_admin=True)
    json_str = msg.to_json()
    assert "join" in json_str
    assert "test_agent" in json_str

    # Test parsing
    parsed = parse_message(json_str)
    assert parsed is not None
    assert parsed.type == MessageType.JOIN
    assert parsed.from_ == "test_agent"
    assert parsed.payload.get("is_admin") is True

    # Test parse failure
    assert parse_message("") is None
    assert parse_message("not json") is None
    assert parse_message('{"not": "a message"}') is None

    # Test all message types
    for msg_type in MessageType:
        msg = make_message(msg_type, from_="test")
        assert msg.type == msg_type
        parsed = parse_message(msg.to_json())
        assert parsed is not None
        assert parsed.type == msg_type

    print("✅ Protocol tests passed")


def test_speech_controller():
    """Test speech control state machine."""
    from rules.speech_controller import SpeechController, SpeechState

    sc = SpeechController(
        members=["agent_a", "agent_b", "agent_c"],
        admins={"admin"},
        speaking_order={"agent_a": 1, "agent_b": 2, "agent_c": 3},
    )

    # Initial state
    assert sc.state == SpeechState.IDLE
    assert sc.current_speaker is None

    # Grant speech
    sc.grant_speech("agent_a")
    assert sc.state == SpeechState.SPEAKING
    assert sc.current_speaker == "agent_a"

    # End speech without marker
    ended = sc.end_speech("agent_a", "some text")
    assert ended is False  # No end marker
    assert sc.state == SpeechState.IDLE

    # End speech with marker
    sc.grant_speech("agent_a")
    ended = sc.end_speech("agent_a", f"Hello! {sc.END_MARKER}")
    assert ended is True

    # Admin can interrupt
    sc.grant_speech("agent_a")
    assert sc.interrupt("agent_a", "admin") is True
    assert sc.state == SpeechState.INTERRUPTED

    # Non-admin cannot interrupt
    sc.grant_speech("agent_a")
    assert sc.interrupt("agent_a", "agent_b") is False

    # Queue management
    sc.enqueue("agent_b")
    sc.enqueue("agent_c")
    assert sc.dequeue() == "agent_b"
    assert sc.dequeue() == "agent_c"
    assert sc.dequeue() is None

    # Priority enqueue
    sc.enqueue("agent_b")
    sc.enqueue("agent_c", priority=True)
    assert sc.dequeue() == "agent_c"  # Priority first

    # Resolve speakers
    speakers = sc.resolve_speakers(
        mentions=["agent_b"],
        all_members=["admin", "agent_a", "agent_b", "agent_c"],
    )
    # Admin first, then @mentioned, then by order
    assert speakers[0] == "admin"
    assert "agent_b" in speakers[:3]  # @mentioned gets priority after admin

    print("✅ Speech controller tests passed")


def test_admin_role():
    """Test admin role management."""
    from rules.admin_role import AdminRole

    admin = AdminRole()

    assert not admin.has_admin
    admin.set_admin("pm_agent")
    assert admin.has_admin
    assert admin.is_admin("pm_agent")
    assert not admin.is_admin("engineer")

    # Task assignment
    task = admin.assign_task(
        "task_001",
        "Implement user authentication",
        ["JWT tokens", "password hashing"],
        "engineer",
    )
    assert task["status"] == "assigned"

    # Task completion
    admin.complete_task("task_001", "Done: implemented JWT + bcrypt", "engineer")
    assert admin.all_tasks_completed()

    # Multiple tasks
    admin.assign_task("task_002", "Design login UI", ["responsive", "dark mode"], "designer")
    assert not admin.all_tasks_completed()

    # Get tasks for assignee
    tasks = admin.get_tasks_for("engineer")
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "task_001"

    # Summary
    summary = admin.summary()
    assert "task_001" in summary
    assert "task_002" in summary
    assert "✅" in summary
    assert "⏳" in summary

    # Remove admin
    admin.remove_admin()
    assert not admin.has_admin

    print("✅ Admin role tests passed")


def test_goal_mode():
    """Test goal mode."""
    from rules.goal_mode import GoalMode

    gm = GoalMode()

    assert not gm.active

    # Set goal
    goal = gm.set_goal("Build a web application")
    assert gm.active
    assert goal.status == "active"
    assert goal.title == "Build a web application"

    # Add tasks
    gm.add_task("task_001", "Design database schema", "engineer")
    gm.add_task("task_002", "Create UI mockups", "designer", ["Figma", "responsive"])
    assert len(gm.current_goal.tasks) == 2

    # Progress
    progress = gm.get_progress()
    assert "Build a web application" in progress
    assert "0/2" in progress

    # Complete tasks
    assert gm.complete_task("task_001", "Schema done")
    assert not gm.is_complete()

    assert gm.complete_task("task_002", "Mockups done")
    assert gm.is_complete()

    # Complete goal
    assert gm.complete_goal()
    assert not gm.active
    assert len(gm.goal_history) == 1

    # Deactivate without completing
    gm.set_goal("Another goal")
    gm.add_task("task_003", "Something", "someone")
    gm.deactivate()
    assert not gm.active
    assert gm.goal_history[-1].status == "failed"

    print("✅ Goal mode tests passed")


def test_chat_bus():
    """Test chat bus server and client communication."""
    from bus.chat_bus import ChatBus
    from bus.protocol import MessageType, make_message, parse_message
    import socket
    import threading

    session_id = f"test_bus_{int(time.time())}"
    bus = ChatBus(session_id)

    # Track received messages
    received = []
    joins = []

    def on_msg(msg):
        received.append(msg)

    def on_join(name):
        joins.append(name)

    bus.on_message = on_msg
    bus.on_join = on_join

    # Start bus
    assert bus.start()

    # Start bus loop in thread
    loop_thread = threading.Thread(target=bus.run_loop, daemon=True)
    loop_thread.start()
    time.sleep(0.2)

    # Connect a client
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(bus.socket_path))

    # Send JOIN
    join_msg = make_message(MessageType.JOIN, from_="test_agent")
    client.sendall((join_msg.to_json() + "\n").encode("utf-8"))
    time.sleep(0.3)

    # Should have received join callback
    assert "test_agent" in joins or bus.is_connected("test_agent")

    # Send a message
    msg = make_message(
        MessageType.RESPONSE,
        from_="test_agent",
        to="orchestrator",
        text=f"Hello, this is a test. {bus.session_id}",
    )
    client.sendall((msg.to_json() + "\n").encode("utf-8"))
    time.sleep(0.3)

    # Check message received
    assert len(received) >= 1
    if received:
        assert received[-1].type == MessageType.RESPONSE
        assert received[-1].from_ == "test_agent"

    # Broadcast test
    broadcast_msg = make_message(MessageType.MESSAGE, from_="orchestrator", text="broadcast test")
    bus.broadcast(broadcast_msg)
    time.sleep(0.2)

    # Cleanup
    client.close()
    bus.stop()
    time.sleep(0.1)

    print("✅ Chat bus tests passed")


def test_end_to_end_flow():
    """Test the full flow without Hermes dependency.

    Verifies: speech → response → end_of_speech → next speaker flow.
    """
    from rules.speech_controller import SpeechController, SpeechState

    speech_log = []
    interrupt_log = []

    sc = SpeechController(
        members=["admin", "engineer", "designer"],
        admins={"admin"},
        speaking_order={"admin": 1, "engineer": 2, "designer": 3},
    )

    sc.on_grant = lambda name, reason: speech_log.append(f"grant:{name}:{reason}")
    sc.on_speech_end = lambda name: speech_log.append(f"end:{name}")
    sc.on_interrupt = lambda name, who: interrupt_log.append(f"interrupt:{name}:{who}")

    # Simulate full flow:
    # 1. Admin speaks first
    sc.grant_speech("admin", "goal_decomposition")
    assert sc.is_speaking("admin")
    assert speech_log[-1] == "grant:admin:goal_decomposition"

    # 2. Admin ends speech with marker
    sc.end_speech("admin", f"Task decomposed. {sc.END_MARKER}")
    assert sc.state == SpeechState.IDLE
    assert speech_log[-1] == "end:admin"

    # 3. Engineer is next in queue
    sc.grant_speech("engineer", "task_execution")
    assert sc.is_speaking("engineer")

    # 4. Admin interrupts engineer
    sc.interrupt("engineer", "admin")
    assert sc.state == SpeechState.INTERRUPTED
    assert len(interrupt_log) == 1

    # 5. Verify full speaker resolution
    speakers = sc.resolve_speakers(
        mentions=["engineer"],
        all_members=["admin", "engineer", "designer"],
    )
    assert speakers[0] == "admin"  # Admin always first
    assert speakers[1] == "engineer"  # @mentioned second

    print("✅ End-to-end flow tests passed")


if __name__ == "__main__":
    test_protocol()
    test_speech_controller()
    test_admin_role()
    test_goal_mode()
    test_chat_bus()
    test_end_to_end_flow()
    print("\n🎉 All tests passed!")
