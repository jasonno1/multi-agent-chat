"""Profile discovery and management for multi-agent-chat.

Reads Hermes profiles from ~/.hermes/profiles/, extracts SOUL.md
identity information, and manages the active chat member list.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProfileInfo:
    """Lightweight profile metadata (for listing)."""
    name: str
    display_name: str = ""
    role: str = ""
    has_soul: bool = False


@dataclass  
class Profile:
    """Full profile with SOUL.md content and memory."""
    name: str
    display_name: str = ""
    role: str = ""
    description: str = ""
    soul_content: str = ""
    memory: str = ""          # GBrain page content (loaded lazily)
    in_chat: bool = False
    joined_at: str = ""


class ProfileManager:
    """Manages Hermes profiles and chat membership."""
    
    def __init__(self, hermes_home: str = None):
        # Use real user home (not Hermes profile home)
        import pwd
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if hermes_home:
            self.hermes_home = Path(os.path.expanduser(hermes_home))
        else:
            self.hermes_home = real_home / ".hermes"
        self.profiles_dir = self.hermes_home / "profiles"
        self.members: dict[str, Profile] = {}  # active chat members
        
    # ── Discovery ──────────────────────────────────────────
    
    def list_all(self) -> list[ProfileInfo]:
        """List all available Hermes profiles."""
        if not self.profiles_dir.exists():
            return []
        
        profiles = []
        for d in sorted(self.profiles_dir.iterdir()):
            if not d.is_dir():
                continue
            soul_file = d / "SOUL.md"
            info = ProfileInfo(
                name=d.name,
                has_soul=soul_file.exists()
            )
            if soul_file.exists():
                identity = self._parse_soul_identity(soul_file)
                info.display_name = identity.get("name", "")
                info.role = identity.get("role", "")
            profiles.append(info)
        
        return profiles
    
    def _parse_soul_identity(self, soul_path: Path) -> dict:
        """Extract name and role from SOUL.md frontmatter or content."""
        try:
            content = soul_path.read_text()
        except Exception:
            return {}
        
        result = {}
        
        # Try YAML frontmatter (supports both SOUL.md and SKILL.md formats)
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            fm = fm_match.group(1)
            for line in fm.split('\n'):
                line = line.strip()
                if ':' not in line:
                    continue
                key, _, val = line.partition(':')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == 'name':
                    result['name'] = val
                elif key == 'description':
                    result['role'] = val
                elif key == 'agent_name':
                    result['name'] = val
        
        # Fallback: look for "你是 Alex" or "I am Alex" patterns in content
        if not result.get('name'):
            m = re.search(r'你(?:是|叫)\s*[「【]*(\S+?)[」】]*[,，\s]', content)
            if m:
                result['name'] = m.group(1)
        
        # Fallback: role from first content line after frontmatter
        if not result.get('role'):
            content_after_fm = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
            # Look for # 标题 that describes the role
            m = re.search(r'^#\s*(.+?)(?:\n|$)', content_after_fm, re.MULTILINE)
            if m:
                title = m.group(1)
                # Skip generic titles like "Identity"
                if title not in ('Identity', '身份', '身份与记忆', 'Core Mission', '核心使命'):
                    result['role'] = title
        
        return result
    
    # ── Load ───────────────────────────────────────────────
    
    def load(self, name: str) -> Optional[Profile]:
        """Load a full profile with SOUL.md content."""
        soul_path = self.profiles_dir / name / "SOUL.md"
        if not soul_path.exists():
            return None
        
        soul_content = soul_path.read_text()
        identity = self._parse_soul_identity(soul_path)
        
        profile = Profile(
            name=name,
            display_name=identity.get("name", name),
            role=identity.get("role", ""),
            description=identity.get("role", ""),
            soul_content=soul_content,
        )
        
        # Try to load GBrain memory
        profile.memory = self._load_memory(name)
        
        return profile
    
    def _load_memory(self, name: str) -> str:
        """Try to load profile's GBrain memory page.
        
        This requires GBrain MCP to be available. Falls back gracefully.
        """
        # GBrain access requires MCP server - skip for MVP
        # Phase 2: use gbrain_get_page(f"agents/{name}")
        return ""
    
    # ── Membership ─────────────────────────────────────────
    
    def invite(self, name: str) -> Optional[Profile]:
        """Invite a profile to the chat. Returns the loaded profile or None."""
        if name in self.members:
            return self.members[name]  # already in chat
        
        profile = self.load(name)
        if profile is None:
            return None
        
        profile.in_chat = True
        profile.joined_at = self._now()
        self.members[name] = profile
        return profile
    
    def kick(self, name: str) -> bool:
        """Remove a profile from the chat. Returns True if was in chat."""
        if name not in self.members:
            return False
        del self.members[name]
        return True
    
    def list_members(self) -> list[Profile]:
        """List all profiles currently in the chat."""
        return list(self.members.values())
    
    @staticmethod
    def _now() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
