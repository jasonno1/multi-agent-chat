"""Command parser for multi-agent-chat.

Parses /profile commands and extracts @mentions from messages.
All commands use the '/' prefix (independent namespace).
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Command(Enum):
    PROFILE_LIST = "profile_list"
    PROFILE_INVITE = "profile_invite"
    PROFILE_KICK = "profile_kick"
    PROFILE_T_LIST = "profile_t_list"
    PROFILE_ORDER = "profile_order"
    PROFILE_ORDER_OFF = "profile_order_off"
    PROFILE_MODE = "profile_mode"
    HELP = "help"
    QUIT = "quit"
    ADMIN = "admin"
    GOAL = "goal"
    INTERRUPT = "interrupt"
    UNKNOWN = "unknown"


@dataclass
class ParsedCommand:
    """Result of parsing a command."""
    command: Command
    args: dict = None
    
    def __post_init__(self):
        if self.args is None:
            self.args = {}


@dataclass
class ParsedMessage:
    """Result of parsing user input."""
    is_command: bool
    command: Optional[ParsedCommand] = None
    mentions: list[str] = None
    raw_text: str = ""
    
    def __post_init__(self):
        if self.mentions is None:
            self.mentions = []


class CommandParser:
    """Parses user input into commands or messages with @mentions."""
    
    # Command patterns: (regex, Command) — ORDER MATTERS (specific first)
    PATTERNS = [
        (r"^/profile\s+-t\s+list\s*$", Command.PROFILE_T_LIST),     # must be before PROFILE_INVITE
        (r"^/profile\s+list\s*$", Command.PROFILE_LIST),
        (r"^/profile\s+-t\s+(\S+)\s+-(\d+)(?:\s+-f)?\s*$", Command.PROFILE_ORDER),  # before PROFILE_INVITE
        (r"^/profile\s+-t\s+(\S+)\s*$", Command.PROFILE_INVITE),
        (r"^/profile\s+-m\s+(\S+)\s*$", Command.PROFILE_KICK),
        (r"^/profile\s+order\s+off\s*$", Command.PROFILE_ORDER_OFF),
        (r"^/profile\s+mode\s+(free|mention|ordered)\s*$", Command.PROFILE_MODE),
        (r"^/invite\s+(\S+)\s*$", Command.PROFILE_INVITE),
        (r"^/kick\s+(\S+)\s*$", Command.PROFILE_KICK),
        (r"^/admin\s+(\S+)\s*$", Command.ADMIN),
        (r"^/goal(?:\s+(.+))?\s*$", Command.GOAL),
        (r"^/interrupt\s*$", Command.INTERRUPT),
        (r"^/help\s*$", Command.HELP),
        (r"^/(quit|exit|q)\s*$", Command.QUIT),
    ]
    
    def parse(self, text: str) -> ParsedMessage:
        """Parse user input. Returns ParsedMessage with command or mentions."""
        text = text.strip()
        
        if not text:
            return ParsedMessage(is_command=False, raw_text=text)
        
        # Check if it's a command
        for pattern, cmd in self.PATTERNS:
            m = re.match(pattern, text, re.IGNORECASE)
            if m:
                return self._build_command(cmd, m)
        
        # Not a command - parse @mentions
        mentions = self.extract_mentions(text)
        return ParsedMessage(
            is_command=False,
            mentions=mentions,
            raw_text=text
        )
    
    def _build_command(self, cmd: Command, match: re.Match) -> ParsedMessage:
        """Build ParsedCommand from regex match groups."""
        args = {}
        groups = match.groups()
        
        if cmd == Command.PROFILE_INVITE:
            args["name"] = groups[0]
        elif cmd == Command.PROFILE_KICK:
            args["name"] = groups[0]
        elif cmd == Command.PROFILE_ORDER:
            args["name"] = groups[0]
            args["order"] = int(groups[1])
            args["force"] = "-f" in match.group(0)
        elif cmd == Command.PROFILE_MODE:
            args["mode"] = groups[0]
        elif cmd == Command.ADMIN:
            args["name"] = groups[0]
        elif cmd == Command.GOAL:
            args["title"] = (groups[0] or "").strip() if groups else ""
        
        return ParsedMessage(
            is_command=True,
            command=ParsedCommand(cmd, args),
            raw_text=match.group(0)
        )
    
    @staticmethod
    def extract_mentions(text: str) -> list[str]:
        """Extract @mentions from message text."""
        # Match @name where name is alphanumeric + hyphens
        return re.findall(r"@([a-zA-Z0-9_-]+)", text)
