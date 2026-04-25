from __future__ import annotations

import re

ANSI_ESCAPE_SEQUENCE_RE = re.compile(
    r"""
    \x1B
    (?:
        \[[0-?]*[ -/]*[@-~]
        |[@-Z\\-_]
        |\][^\x1B\x07]*(?:\x07|\x1B\\)
    )
    """,
    re.VERBOSE,
)
CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')


def strip_terminal_control_sequences(text: str) -> str:
    """Remove ANSI escapes and non-printing control bytes while preserving newlines."""
    sanitized = ANSI_ESCAPE_SEQUENCE_RE.sub('', text)
    return CONTROL_CHAR_RE.sub('', sanitized)
