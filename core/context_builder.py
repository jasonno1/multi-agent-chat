"""Build prompts for profile responses in multi-agent chat.

Constructs the complete system prompt + context for each profile
before sending to Hermes for response generation.
"""

from typing import Optional
from core.profile_manager import Profile


class ContextBuilder:
    """Builds prompts for each profile's response."""
    
    # Max conversation history rounds to include
    MAX_HISTORY_ROUNDS = 10
    
    def build(
        self,
        profile: Profile,
        current_message: str,
        conversation_history: list[dict] = None,
        previous_speaker: str = None,
    ) -> str:
        """Build a complete prompt for a profile's response.
        
        Args:
            profile: The profile to build context for
            current_message: The message this profile should respond to
            conversation_history: List of {speaker, message} dicts
            previous_speaker: Name of the profile/user who sent current_message
            
        Returns:
            Complete prompt string ready for hermes chat -q
        """
        parts = []
        
        # 1. Role & Context header
        parts.append(self._build_role_header(profile))
        
        # 2. Multi-agent chat protocol
        parts.append(self._build_protocol(profile))
        
        # 3. Conversation history (if any)
        if conversation_history:
            parts.append(self._build_history(conversation_history))
        
        # 4. Current message
        parts.append(self._build_current_message(
            current_message, previous_speaker
        ))
        
        # 5. Response instruction
        parts.append(self._build_instruction(profile))
        
        return '\n\n'.join(parts)
    
    def _build_role_header(self, profile: Profile) -> str:
        """Build the role identification header."""
        name = profile.display_name or profile.name
        role = profile.role or "participant"
        return f"# Context\nYou are **{name}** ({role}) participating in a multi-agent group chat."
    
    def _build_protocol(self, profile: Profile) -> str:
        """Build the multi-agent chat protocol instructions."""
        return """## Group Chat Rules
- You are in a group chat with the user and possibly other AI agents.
- Respond naturally in character, as if you were in a real chat room.
- Keep responses concise (1-3 paragraphs). This is a chat, not an essay.
- You may use tools (terminal, web, files) to look up information when needed.
- If you want to address another participant, use @name syntax.
- Do NOT prefix your response with your name — the system handles that.
- Just type what you would say."""
    
    def _build_history(self, history: list[dict]) -> str:
        """Build conversation history section.
        
        Args:
            history: List of {speaker, message} dicts, most recent last
        """
        recent = history[-self.MAX_HISTORY_ROUNDS:] if len(history) > self.MAX_HISTORY_ROUNDS else history
        
        lines = ["## Conversation So Far"]
        for entry in recent:
            speaker = entry.get('speaker', 'unknown')
            message = entry.get('message', '')
            # Truncate long messages in history
            if len(message) > 500:
                message = message[:500] + "..."
            lines.append(f"**{speaker}**: {message}")
        
        return '\n'.join(lines)
    
    def _build_current_message(self, message: str, speaker: str = None) -> str:
        """Build the current message section."""
        who = speaker if speaker else "User"
        return f"## New Message from {who}\n{message}"
    
    def _build_instruction(self, profile: Profile) -> str:
        """Build the response instruction."""
        name = profile.display_name or profile.name
        return f"Respond to the message above as {name}. Be concise and in character."
