"""State persistence for multi-agent-chat.

Saves and restores chat session state to JSON.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional


class StateManager:
    """Manages session state persistence."""
    
    def __init__(self, state_dir: Path = None):
        if state_dir is None:
            state_dir = Path(__file__).parent.parent / "state"
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.state_dir / "session.json"
    
    def save(self, data: dict) -> bool:
        """Save session state to JSON file."""
        data["saved_at"] = datetime.now().isoformat()
        try:
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def load(self) -> Optional[dict]:
        """Load session state from JSON file.
        
        Returns None if no saved state or state is older than 24 hours.
        """
        if not self.session_file.exists():
            return None
        
        try:
            with open(self.session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return None
        
        # Check age
        saved_at = data.get("saved_at", "")
        if saved_at:
            try:
                saved_time = datetime.fromisoformat(saved_at)
                age = (datetime.now() - saved_time).total_seconds()
                if age > 86400:  # 24 hours
                    return None
            except ValueError:
                pass
        
        return data
    
    def clear(self):
        """Remove saved state."""
        if self.session_file.exists():
            self.session_file.unlink()
