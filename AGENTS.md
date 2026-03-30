# goojera Project Context

gojeera is a Textual User Interface (TUI) application for interacting with
Atlassian Jira with a focus on cloud instances using API v3.

## Project Overview

- **Language**: Python
- **Framework**: Textual TUI Framework (<https://textual.textualize.io/>)
- **Package Manager**: uv (<https://docs.astral.sh/uv/>)
- **Linting:**: ruff (<https://docs.astral.sh/ruff/>)
- **Type Checking:**: ty (<https://docs.astral.sh/ty/>)
- **Deadcode Analysis**: vulture (<https://github.com/jendrikseipp/vulture>)

## Development Workflow

1. After each change, analyze codebase using `make analyze-codebase` and attempt
   to fix all issues.
2. Run scoped testing on changed classes using `uv run pytest -n auto $AFFECTED_CLASSES`.

## Markdown ↔ ADF Conversion

gojeera converts between Markdown and Atlassian Document Format (ADF) for Jira
work item descriptions.

**IMPORTANT**: Any changes to Markdown → ADF or ADF → Markdown conversion logic
**MUST** be documented in `docs/markdown_to_adf_conversion.md`.
This file serves as the single source of truth for conversion mappings,
supported features, and implementation details.

**For complete conversion reference**, see: `docs/markdown_to_adf_conversion.md`

## Crucial Notes

- UI components inherit from Textual widgets
- Services handle Jira API communication
- Models use Pydantic for data validation
- Async operations for API calls
- Ensure proper error handling for API failures
- Respect rate limits when making API calls
- Use environment variables for sensitive data (API tokens, etc.)
- Keep the TUI responsive during long operations (do not block UI)
- Avoid using the following widgets (due to performance issues with mouse
  events):
  - `ListView`
  - `ListItem`
