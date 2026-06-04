# Project Overview

gojeera is a Textual User Interface (TUI) application for interacting with
Atlassian Jira with a focus on cloud instances using API v3.

- **Language**: Python
- **Framework**: Textual TUI Framework (<https://textual.textualize.io/>)
- **Package Manager**: uv (<https://docs.astral.sh/uv/>)

## Development Workflow

1. After each change, analyze codebase using `make analyze-codebase` and attempt
   to fix all issues.
2. Run scoped testing on changed classes using `uv run pytest -n auto $AFFECTED_CLASSES`.
   **DO NOT RERUN SNAPSHOTS, remind the user it is their responsibility!**

## Markdown ↔ ADF Conversion

gojeera converts between Markdown and Atlassian Document Format (ADF).

**IMPORTANT**: Any changes to Markdown → ADF or ADF → Markdown conversion logic
**MUST** be documented in `docs/markdown_to_adf_conversion.md`.
This file serves as the single source of truth for conversion mappings,
supported features, and implementation details.
