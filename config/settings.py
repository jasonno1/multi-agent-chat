"""Configuration management for multi-agent-chat."""

import os
import yaml
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).parent / "defaults.yaml"


def load_config(config_path: Path = None) -> dict[str, Any]:
    """Load configuration, merging defaults with user overrides."""
    config = {}
    
    # Load defaults
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
    
    # Load user config (overrides defaults)
    if config_path and config_path.exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
            _deep_merge(config, user_config)
    
    # Expand ~ in paths
    _expand_paths(config)
    
    return config


def _deep_merge(base: dict, override: dict):
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _expand_paths(config: dict):
    """Expand ~ in string values."""
    for key, value in config.items():
        if isinstance(value, str) and value.startswith("~"):
            config[key] = os.path.expanduser(value)
        elif isinstance(value, dict):
            _expand_paths(value)
