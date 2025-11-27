# -*- coding: utf-8 -*-
"""
DataJuicer Agent - A multi-agent data processing system
"""

from .core import (
    __version__,
    create_agent,
    DJ_SYS_PROMPT,
    DJ_DEV_SYS_PROMPT,
    ROUTER_SYS_PROMPT,
    MCP_SYS_PROMPT,
    register_dj_agent_hooks,
)

__all__ = [
    "__version__",
    "create_agent",
    "DJ_SYS_PROMPT",
    "DJ_DEV_SYS_PROMPT",
    "ROUTER_SYS_PROMPT",
    "MCP_SYS_PROMPT",
    "register_dj_agent_hooks",
]