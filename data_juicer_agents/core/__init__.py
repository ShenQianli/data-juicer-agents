# -*- coding: utf-8 -*-
"""Core modules for Data Juicer Agent."""

from .agent_factory import create_agent
from .prompts import (
    DJ_SYS_PROMPT,
    DJ_DEV_SYS_PROMPT,
    ROUTER_SYS_PROMPT,
    MCP_SYS_PROMPT,
)
from .dj_agent_hooks import register_dj_agent_hooks
from ._version import __version__

__all__ = [
    "create_agent",
    "DJ_SYS_PROMPT",
    "DJ_DEV_SYS_PROMPT",
    "ROUTER_SYS_PROMPT",
    "MCP_SYS_PROMPT",
    "register_dj_agent_hooks",
    "__version__",
]
