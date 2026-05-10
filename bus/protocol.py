"""Message protocol for the multi-agent chat bus.

All inter-process communication uses single-line JSON messages
sent over Unix Domain Sockets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    # Connection lifecycle
    JOIN = "join"
    WELCOME = "welcome"
    LEAVE = "leave"
    SHUTDOWN = "shutdown"

    # Chat messages
    MESSAGE = "message"
    TASK = "task"
    RESPONSE = "response"

    # Speech control
    GRANT_SPEECH = "grant_speech"
    END_OF_SPEECH = "end_of_speech"
    INTERRUPT = "interrupt"
    INTERRUPTED = "interrupted"

    # System / control
    RULE_VIOLATION = "rule_violation"
    STATUS_REQUEST = "status_request"
    STATUS_REPLY = "status_reply"
    ACK = "ack"
    ERROR = "error"

    # Goal mode
    GOAL_SET = "goal_set"
    GOAL_COMPLETE = "goal_complete"


@dataclass
class Message:
    type: MessageType
    from_: str = ""
    to: str = "*"
    timestamp: str = ""
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        data = {
            "type": self.type.value,
            "from": self.from_,
            "to": self.to,
            "timestamp": self.timestamp or datetime.now().isoformat(timespec="milliseconds"),
            "payload": self.payload,
        }
        return json.dumps(data, ensure_ascii=False)


def parse_message(raw: str) -> Message | None:
    """Parse a JSON line into a Message. Returns None on failure."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    try:
        msg_type = MessageType(data["type"])
    except (KeyError, ValueError):
        return None

    return Message(
        type=msg_type,
        from_=data.get("from", ""),
        to=data.get("to", "*"),
        timestamp=data.get("timestamp", ""),
        payload=data.get("payload", {}),
    )


def make_message(
    msg_type: MessageType,
    from_: str = "",
    to: str = "*",
    **payload: Any,
) -> Message:
    return Message(
        type=msg_type,
        from_=from_,
        to=to,
        timestamp=datetime.now().isoformat(timespec="milliseconds"),
        payload=dict(payload),
    )
