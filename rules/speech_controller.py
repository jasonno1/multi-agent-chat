"""Speech control state machine for multi-agent group chat.

Controls who can speak and when. Ensures orderly conversation flow:
  - Only one profile speaks at a time
  - Admin and User can interrupt anyone
  - Speaking ends only when "我的发言结束。" is received
  - Next speaker is activated only after current one finishes
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable


class SpeechState(str, Enum):
    IDLE = "idle"           # No one speaking, waiting for input
    SPEAKING = "speaking"   # A profile is currently speaking
    INTERRUPTED = "interrupted"  # A profile was interrupted


@dataclass
class SpeechController:
    """Manages speaking rights in the group chat."""

    members: list[str] = field(default_factory=list)
    admins: set[str] = field(default_factory=set)  # profile names with admin rights
    users: set[str] = field(default_factory=lambda: {"user", "orchestrator"})
    speaking_order: dict[str, int] = field(default_factory=dict)

    # State
    state: SpeechState = SpeechState.IDLE
    current_speaker: Optional[str] = None
    speech_queue: list[str] = field(default_factory=list)

    # Callbacks - set by orchestrator
    on_grant: Callable[[str, str], None] | None = None   # (profile_name, reason)
    on_interrupt: Callable[[str, str], None] | None = None  # (profile_name, by_whom)
    on_speech_end: Callable[[str], None] | None = None  # (profile_name)

    # The required end-of-speech marker
    END_MARKER = "我的发言结束。"

    # ── Speech Rights ──────────────────────────────────────

    def can_speak(self, profile_name: str) -> bool:
        """Check if a profile can speak right now."""
        if profile_name in self.admins or profile_name in self.users:
            return True  # Admins and users can always speak
        if self.state == SpeechState.IDLE:
            return True
        if self.current_speaker == profile_name and self.state == SpeechState.SPEAKING:
            return True
        return False

    def can_interrupt(self, profile_name: str) -> bool:
        """Check if a profile can interrupt the current speaker."""
        return profile_name in self.admins or profile_name in self.users

    def grant_speech(self, profile_name: str, reason: str = ""):
        """Grant speaking rights to a profile."""
        if self.state == SpeechState.SPEAKING and self.current_speaker != profile_name:
            # Someone else is speaking - only allow if admin/user
            if not self.can_interrupt(profile_name):
                return
            # Interrupt current speaker
            if self.current_speaker and self.on_interrupt:
                self.on_interrupt(self.current_speaker, profile_name)

        self.current_speaker = profile_name
        self.state = SpeechState.SPEAKING

        if self.on_grant:
            self.on_grant(profile_name, reason)

    def end_speech(self, profile_name: str, text: str = "") -> bool:
        """Called when a profile ends their speech.

        Returns True if the speech ended cleanly (with end marker).
        """
        if self.current_speaker != profile_name:
            return False

        self.state = SpeechState.IDLE
        self.current_speaker = None

        if self.on_speech_end:
            self.on_speech_end(profile_name)

        # Check if next in queue should automatically speak
        if self.speech_queue:
            next_speaker = self.speech_queue.pop(0)
            self.grant_speech(next_speaker, "queue")

        return self._has_end_marker(text)

    def interrupt(self, profile_name: str, by_whom: str) -> bool:
        """Interrupt the current speaker."""
        if not self.can_interrupt(by_whom):
            return False

        if self.state != SpeechState.SPEAKING:
            return False

        old_speaker = self.current_speaker
        self.state = SpeechState.INTERRUPTED
        self.current_speaker = None

        if self.on_interrupt and old_speaker:
            self.on_interrupt(old_speaker, by_whom)

        return True

    # ── Queue Management ───────────────────────────────────

    def enqueue(self, profile_name: str, priority: bool = False):
        """Add a profile to the speech queue."""
        if priority:
            self.speech_queue.insert(0, profile_name)
        else:
            if profile_name not in self.speech_queue:
                self.speech_queue.append(profile_name)

    def dequeue(self) -> Optional[str]:
        """Get the next speaker from the queue."""
        return self.speech_queue.pop(0) if self.speech_queue else None

    def clear_queue(self):
        """Clear the speech queue."""
        self.speech_queue.clear()

    # ── Order Resolution ───────────────────────────────────

    def resolve_speakers(
        self, mentions: list[str], all_members: list[str]
    ) -> list[str]:
        """Resolve the speaking order based on mentions and preset order.

        Priority: admins > @mentioned > speaking_order > remaining members
        """
        result = []
        seen = set()

        # Phase 1: Admins first
        for name in all_members:
            if name in self.admins and name not in seen:
                result.append(name)
                seen.add(name)

        # Phase 2: @mentioned profiles
        for name in mentions:
            if name in all_members and name not in seen:
                result.append(name)
                seen.add(name)

        # Phase 3: By speaking order
        ordered = sorted(
            [(n, o) for n, o in self.speaking_order.items() if n in all_members],
            key=lambda x: x[1],
        )
        for name, _ in ordered:
            if name not in seen:
                result.append(name)
                seen.add(name)

        # Phase 4: Remaining members
        for name in all_members:
            if name not in seen:
                result.append(name)
                seen.add(name)

        return result

    # ── Helpers ────────────────────────────────────────────

    def _has_end_marker(self, text: str) -> bool:
        return self.END_MARKER in text

    def is_speaking(self, profile_name: str) -> bool:
        return self.state == SpeechState.SPEAKING and self.current_speaker == profile_name

    def reset(self):
        self.state = SpeechState.IDLE
        self.current_speaker = None
        self.speech_queue.clear()
