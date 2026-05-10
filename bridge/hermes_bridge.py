"""Bridge to Hermes Agent for profile responses.

Calls `hermes chat -q` as a subprocess to get profile responses.
Each call runs in the profile's context with tools available (via --yolo).
"""

import subprocess
import os
import re
import tempfile
from pathlib import Path
from typing import Optional


class HermesBridge:
    """Calls Hermes CLI to get profile responses."""
    
    def __init__(self, hermes_bin: str = "hermes", timeout: int = 120, yolo: bool = True):
        self.hermes_bin = hermes_bin
        self.timeout = timeout
        self.yolo = yolo
    
    def query(self, profile_name: str, skill_name: str, prompt: str) -> Optional[str]:
        """Query a profile and return its response.
        
        Args:
            profile_name: Hermes profile name (e.g., 'product-manager')
            skill_name: Skill to load (e.g., 'product-manager')
            prompt: Full prompt text to send
            
        Returns:
            Profile's response text, or None on failure.
        """
        # Write prompt to temp file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8'
        ) as f:
            f.write(prompt)
            prompt_file = f.name
        
        try:
            cmd = [
                self.hermes_bin, "chat",
                "-p", profile_name,
                "-s", skill_name,
                "-q", prompt,
                "--quiet",
            ]
            
            if self.yolo:
                cmd.append("--yolo")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ},  # inherit env (API keys etc.)
            )
            
            return self._parse_response(result.stdout, result.stderr)
            
        except subprocess.TimeoutExpired:
            return None
        except Exception as e:
            return None
        finally:
            # Clean up temp file
            try:
                os.unlink(prompt_file)
            except OSError:
                pass
    
    def _parse_response(self, stdout: str, stderr: str) -> Optional[str]:
        """Extract the response from hermes chat -q output.
        
        Expected format:
            session_id: 20260509_151100_2e0eba
            <response text>
        """
        if not stdout.strip():
            return None
        
        lines = stdout.strip().split('\n')
        
        # Skip session_id line
        if lines and lines[0].startswith('session_id:'):
            lines = lines[1:]
        
        response = '\n'.join(lines).strip()
        
        if not response:
            return None
        
        return response
