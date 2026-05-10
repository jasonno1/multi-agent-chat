#!/usr/bin/env python3
"""Multi-Agent Chat — CLI Entry Point.

A Hermes-based multi-agent group chat tool with:
  - Persistent independent agent processes via UDS socket bus
  - Speech control with structured end-of-speech markers
  - Admin role and /goal mode for task decomposition
  - Per-profile independent memory management

Run with: python -m multi_agent_chat
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.orchestrator import Orchestrator


def main():
    app = Orchestrator()
    app.run()


if __name__ == "__main__":
    main()
