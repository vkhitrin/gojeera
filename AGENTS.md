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

## Key Features

- Browse and search Jira work items
- View and manage work item details and comments
- Create, update, and delete work items
- Navigate between work items and projects
- Filter and sort work items
- Display work item metadata (status, priority, assignee, etc.)
- View and manage attachments
- Markdown-to-ADF conversion

## Development Workflow

1. Make changes to the codebase.
2. Analyze codebase using `make analyze-codebase` and attempt to fix all issues.

## Code Style Conventions

- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Write clear, descriptive variable names
- Include docstrings for public functions and classes
- Keep functions focused and small

## Common Patterns

- UI components inherit from Textual widgets
- Services handle Jira API communication
- Models use Pydantic for data validation
- Async operations for API calls

## Markdown ↔ ADF Conversion

gojeera converts between Markdown and Atlassian Document Format (ADF) for Jira
work item descriptions.

**IMPORTANT**: Any changes to Markdown → ADF or ADF → Markdown conversion logic
**MUST** be documented in `docs/markdown_to_adf_conversion.md`.
This file serves as the single source of truth for conversion mappings,
supported features, and implementation details.

**For complete conversion reference**, see: `docs/markdown_to_adf_conversion.md`

## Crucial Notes

- When using personal info, be aware of a user preference
  `obfuscate_personal_info` that ensures that personal information
  (such as the current username, user ID, instance URLs) **are never printed**.
- Ensure proper error handling for API failures
- Respect rate limits when making API calls
- Use environment variables for sensitive data (API tokens, etc.)
- Keep the TUI responsive during long operations (do not block UI)
- Avoid using the following widgets (due to performance issues with mouse
  events):
  - `ListView`
  - `ListItem`
