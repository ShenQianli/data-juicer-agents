# -*- coding: utf-8 -*-

import logging

from data_juicer_agents.agents.react_planner_agent import (
    _IgnoreThinkingBlockWarningFilter,
)


def test_ignore_thinking_warning_filter_blocks_only_target_message():
    filt = _IgnoreThinkingBlockWarningFilter()

    blocked = logging.LogRecord(
        name="as",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Unsupported block type thinking in the message, skipped.",
        args=(),
        exc_info=None,
    )
    kept = logging.LogRecord(
        name="as",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Some other warning should remain visible.",
        args=(),
        exc_info=None,
    )

    assert filt.filter(blocked) is False
    assert filt.filter(kept) is True
