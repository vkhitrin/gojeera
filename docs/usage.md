# Usage Guide

This guide provides an overview of how to use **gojeera**, a TUI (Textual
User Interface) application for interacting with Atlassian Jira.

For configuration options, see [configuration.md](configuration.md).

## Overview

![gojeera interface](/static/gojeera.svg)

gojeera aims to provide a vim-like keyboard-driven interface for interacting with
Jira work items. The main view is inspired by the Jira Cloud web UI, with a
search panel on the left, work item list in the middle, and work item fields
panel on the right.

## Starting gojeera

```bash
# Start with default configuration
gojeera

# Start with search on startup
gojeera --search-on-startup

# Start with specific project pre-selected
gojeera --project-key "PROJ"

# Start with specific assignee pre-selected
gojeera --assignee "john.doe@example.com"

# Start with a specific JQL filter
gojeera --jql-filter "My Work Items"

# Open a specific work item
gojeera --work-item-key "PROJ-123"
```

## Global Keybindings

| Key      | Action          | Description                                   |
| -------- | --------------- | --------------------------------------------- |
| `Ctrl+C` | Quit            | Exit the application                          |
| `Ctrl+\` | Jump Mode       | Activate jumper overlay for quick navigation  |
| `Ctrl+P` | Command Palette | Open command palette                          |
| `?`      | Help            | Open in-app help documentation                |
| `F12`    | Debug Info      | Show debug information (config, server, user) |
| `[`      | Previous Tab    | Navigate to previous tab in work item details |
| `]`      | Next Tab        | Navigate to next tab in work item details     |

## Unified Search

gojeera features a unified search widget that supports three modes:

### Search Modes

#### 1. BASIC Mode (Default)

![Unified search basic mode](/static/unified_search_basic_mode.svg)

Search using individual filters:

- **Work Item Key**: Search by exact key (e.g., `PROJ-123`)
- **Project**: Filter by project
- **Assignee**: Filter by assigned user
- **Status**: Filter by work item status
- **Type**: Filter by work item type (Bug, Story, Task, etc.)

#### 2. TEXT Mode

![Unified search text mode](/static/unified_search_text_mode.svg)

Full-text search across work item fields.

- If `enable_advanced_full_text_search` is enabled in config: Searches across
  all text fields including comments
- If disabled: Only searches in summary and description fields

#### 3. JQL Mode

![Unified search JQL mode](/static/unified_search_jql_mode.svg)

Advanced search using Jira Query Language (JQL).

**Default query** (when no search criteria is provided):

```sql
created >= -30d ORDER BY created DESC
```

**Features**:

- Autocomplete for JQL expressions (local or remote filters)
- Local filters (defined in config) marked with ⌂ symbol
- Remote filters (fetched from Jira) marked with ☁ symbol

**Example JQL queries**:

```sql
assignee = currentUser() AND status != Done ORDER BY priority DESC
project = "MYPROJ" AND sprint in openSprints()
updated >= -7d ORDER BY updated DESC
```

### Remote Filters

![Unified search filters view](/static/unified_search_filters_view.svg)

You can fetch saved filters from your Jira instance by enabling the feature
in your configuration.

Remote filters appear in the JQL autocomplete dropdown with a ☁ symbol.

## Working with Work Items

### Interacting with Work Items

After executing a search, work items are displayed in the information panel.
Navigate using:

- `j` / `↓` - Move down
- `k` / `↑` - Move up
- `l` - Next page
- `h` - Previous page
- `CTRL+O` - Open in browser
- `CTRL+B` - Clone work item
- `CTRL+K` - Copy key to clipboard
- `CTRL+L` - Copy URL to clipboard
- `CTRL+N` - New work item
- `Enter` - Load full details of selected work item

### Work Item Tabs

The information panel contains multiple tabs:

#### Summary Tab

![Work item summary tab](/static/work_item_summary_tab.svg)

Displays work item summary and description with Markdown rendering.

**Keybindings**:

- `CTRL+E` - Edit work item summary and description
- `CTRL+L` - Open worklog
- `CTRL+T` - Log work

#### Attachments Tab

![Work item attachments tab](/static/work_item_attachments_tab.svg)

Manage files attached to work items.

**Keybindings**:

- `CTRL+N` - Add new attachment
- `d` - Delete the selected attachment
- `Enter` - View attachment (if supported format)
- `CTLR+S` - Save/download attachment
- `CTRL+O` - Open attachment in browser

**Supported preview formats**:

![Work item attachments screen](/static/work_item_attachment_screen.svg)

- Images: PNG, JPG, GIF, etc. (if `enable_images_support` is enabled)
- Text: TXT, CSV, Markdown

#### Subtasks Tab

![Work item subtasks tab](/static/work_item_subtasks_tab.svg)

Manage subtasks for the current work item.

**Keybindings**:

- `CTRL+N` - New subtask
- `Ctrl+G` - Load selected subtask
- `CTRL+O` - Open subtask in browser

#### Related Work Items Tab

![Work item related items tab](/static/work_item_related_tab.svg)

Manage work item relationships (blocks, is blocked by, relates to, etc.).

**Keybindings**:

- `CTRL+N` - Link to another work item
- `d` - Unlink selected work item
- `Ctrl+G` - Load selected work item
- `CTRL+O` - Open work item in browser

#### Web Links Tab

![Work item web links tab](/static/work_item_web_links_tab.svg)

Manage remote links associated with work items.

**Keybindings**:

- `CTRL+N` - Add new web link
- `d` - Delete selected web link
- `e` - Edit web link
- `CTRL+O` - Open link in browser

#### Comments Tab

![Work item comments tab](/static/work_item_comments_tab.svg)

Manage work item comments.

**Keybindings**:

- `CTRL+N` - Add new comment
- `d` - Delete selected comment
- `e` - Edit comment
- `CTRL+O` - Open comment in browser

**Comment Features**:

- Markdown support with ADF conversion
- User mentions via `@username` (use command palette to insert)
- Decision markers for meeting notes
- Panels/alerts (NOTE, TIP, IMPORTANT, WARNING, CAUTION)

## Time Tracking

![Log work screen](/static/log_work_screen.svg)

gojeera supports Jira's time tracking features:

- View time spent, remaining estimate, and original estimate
- Add work log entries with time spent and comments
- Update remaining estimate when logging work
- View and edit existing work log entries

### Fields Panel

![Fields panel](/static/fields_panel.svg)

Shows and allows editing of work item fields:

- **Basic fields**: Status, Priority, Labels, Due Date, etc.
- **Time Tracking**: Original estimate, time spent, remaining estimate
- **Custom fields**: Configurable via `enable_updating_additional_fields`

## Creating and Editing Work Items

### Creating a New Work Item

![New work item screen](/static/new_work_item_screen.svg)

Press `Ctrl+N` from the main screen to open the new work item dialog.

**Required fields**:

- **Project**: Select the target project
- **Type**: Select work item type (Bug, Task, Story, etc.)
- **Summary**: Brief description

**Optional fields** (depending on configuration):

- Description (with Markdown support)
- Priority
- Due Date
- Labels
- Custom fields (if `enable_creating_additional_fields` is enabled)

## Markdown and ADF Support

gojeera provides seamless conversion between Markdown and Atlassian Document
Format (ADF).

### Supported Markdown Features

**Basic formatting**:

- `**bold**`, `*italic*`, `~~strikethrough~~`
- `` `inline code` ``
- `[links](url)`
- Headers: `#` through `######`

**Lists**:

- Bulleted lists: `- item`
- Numbered lists: `1. item`
- Task lists: `- [ ]` unchecked, `- [x]` checked

**Code blocks**:

````markdown
```python
def hello():
    print("Hello, World!")
```
````

**Tables**:

```markdown
| Header 1 | Header 2 |
| -------- | -------- |
| Cell 1   | Cell 2   |
```

**Blockquotes and Alerts**:

```markdown
> Regular blockquote

> [!NOTE]
> Informational panel

> [!WARNING]
> Warning panel

> [!IMPORTANT]
> Important panel
```

**User mentions**:

```markdown
[@John Doe](https://your-instance.atlassian.net/jira/people/account-id)
```

**Special markers** (rendered with styling in gojeera):

- `[date]2024-01-15` - Date with background
- `[status:g]Done` - Status badge (g=green, r=red, b=blue, y=yellow, etc.)
- `[decision:d]We decided to...` - Decision marker

For complete conversion reference, see [markdown_to_adf_conversion.md](markdown_to_adf_conversion.md).

## Command Palette

Press `Ctrl+P` to access commands:

### Available Commands

**Insertion Commands** (available in text editors only):

- **Insert User Mention**: Add a mention to a Jira user
- **Insert Decision**: Add a decision marker for meeting notes
- **Insert Panel/Alert**: Add styled panels (NOTE, TIP, IMPORTANT, WARNING, CAUTION)

## Jumper Mode

![Jumper mode](/static/jumper_mode.svg)

The jumper overlay (`Ctrl+\`) allows quick keyboard navigation to different parts
of the interface.

Each visible widget is assigned a key. Press the corresponding key to jump
directly to that widget.

## Additional Resources

- **Configuration**: See [configuration.md](configuration.md) for all configuration options
- **Markdown/ADF**: See [markdown_to_adf_conversion.md](markdown_to_adf_conversion.md) for conversion details
- **Jira JQL**: [Jira Query Language documentation](https://support.atlassian.com/jira-service-management-cloud/docs/use-advanced-search-with-jira-query-language-jql/)
- **API Tokens**: [Generate Jira API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
