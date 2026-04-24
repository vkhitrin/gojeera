# Usage Guide

This guide provides an overview of how to use **gojeera**, a TUI (Textual
User Interface) application for interacting with Atlassian Jira.

For configuration options, see [configuration.md](configuration.md).

## Overview

![gojeera interface](/tests/__snapshots__/test_work_item_description/TestWorkItemDescription.test_internal_jira_link_tooltip_snapshot.svg)

gojeera's interface is navigable using mouse and keyboard.

The main view is inspired by the Jira Cloud web UI, with a
search panel on the left, work item details in the middle, and work item fields
panel on the right.

## Authenticating With Atlassian Jira

gojeera uses profiles for authentication. Each profile stores Jira connection
metadata while secrets are stored in the operating
system keyring.

Supported authentication modes:

- **Basic**: Jira site URL + email + API token
  <https://id.atlassian.com/manage-profile/security/api-tokens>
- **OAuth2**: Atlassian 3LO app + browser login + discovered Jira site
  <https://developer.atlassian.com/cloud/jira/software/oauth-2-3lo-apps/>

### Authentication Commands

```bash
# Create or edit a profile
gojeera auth login

# Show configured profiles and validation state
gojeera auth status

# Remove a profile
gojeera auth logout
```

### Basic Authentication

When you select `Basic (email + API token)`, the wizard prompts for:

- `Profile name`
- `Jira instance URL`
- `Jira email`
- `Jira API token`

Before the profile is saved, gojeera validates the credentials against Jira.

### OAuth2 Authentication

When you select `OAuth2`, gojeera supports Atlassian 3LO login.

The wizard prompts for:

- `Profile name`
- `Atlassian client ID`
- `Atlassian client secret`

gojeera always uses the `Extended + User Identity` scope set.

The application requests the following oauth2 scopes:
`read:jira-user`, `read:jira-work`, `write:jira-work`,
`manage:jira-data-provider`, `read:servicedesk-request`, `read:servicemanagement-insi
ght-objects`, `offline_access`, `read:me`, `read:account`

### Choosing a Profile

If you have multiple profiles, you can either:

- Mark one profile as active in `gojeera auth login`
- Select one explicitly when launching the app

```bash
gojeera --profile "service_account"
```

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

# Use a specific authentication profile
gojeera --profile "service_account"
```

## Global Keybindings

| Key      | Action           | Description                                              |
| -------- | ---------------- | -------------------------------------------------------- |
| `Ctrl+C` | Quit             | Exit the application                                     |
| `Ctrl+\` | Jump Mode        | Activate jumper overlay for quick navigation             |
| `Ctrl+P` | Command Palette  | Open command palette                                     |
| `CTRL+N` | New Work Item    | Create a new work item from the main search/results view |
| `?`      | Help             | Open help                                                |
| `F10`    | Quick Navigation | Open a work item directly by key                         |
| `F11`    | Toggle Footer    | Show or hide the footer for the current session          |
| `F12`    | Debug Info       | Show debug information (config, server, user)            |
| `[`      | Previous Tab     | Navigate to previous tab in work item details            |
| `]`      | Next Tab         | Navigate to next tab in work item details                |

## External Editing

When focus is on an editable text widget, press `F2` to open its contents in
your external editor from `$EDITOR`.

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

### JQL Filters

![Unified search filters view](/static/unified_search_filters_view.svg)

You can fetch saved filters from your Jira instance by enabling the feature
in your configuration.

Remote filters appear in the JQL autocomplete dropdown with a ☁ symbol.

Filters can also be defined locally via the configuration file and appear
with a ⌂ symbol.

## Browsing Work Items

### Search Results

![Work item search results](/static/work_item_search_results.svg)

After executing a search, gojeera shows a dedicated results pane with:

- Ordering controls:
  - Order by predefined fields, `Created`, `Key`, `Last viewed`, `Priority`,
    `Resolved`, `Status`, `Updated`
    By default `Created` is set.
  - Sort by ascending/descending value of the field.
    By default `Descending` is set.
- Work items.
- Pagination and total results returned by search.

Each work item may contain:

- Work item key and type.
- Summary
- Priority, Status, and Assignee.

### Search Result Navigation

Use the results pane to move through matches and load the selected item:

- `j` / `↓` - Move to the next result
- `k` / `↑` - Move to the previous result
- `g` - Jump to the first result
- `G` - Jump to the last result
- `n` - Load the next page of search results
- `p` - Load the previous page of search results
- `Enter` - Load the selected work item
- `CTRL+O` - Open the selected work item in browser
- `CTRL+B` - Clone the selected work item
- `CTRL+Y` - Copy the selected work item key
- `CTRL+U` - Copy the selected work item URL

### Search Result Controls

The search results pane combines:

- search ordering controls
- page navigation
- rendered Jira result cards

The controls row above the results lets you:

- change the ordering field
- toggle ascending / descending direction
- rerun the active search

### Work Item Tabs

Once a result is loaded, the information panel switches to work-item tabs.

The information panel contains multiple tabs:

- Description
- Attachments
- Subtasks
- Web Links
- Comments

Several shortcuts are contextual and depend on the active tab:

- `CTRL+D` - delete the selected item in the active context
- `CTRL+G` - load the selected linked/internal work item
- `CTRL+O` - open the selected item in the browser
- `CTRL+E` - edit the current description or selected subtask
- `CTRL+S` - save fields or download the selected attachment

#### Description Tab

![Work item summary tab](/static/work_item_description_tab.svg)

Displays work item summary and description with Markdown rendering.

**Keybindings**:

- `CTRL+E` - Edit work item summary and description
- `CTRL+G` - Load the focused internal Jira link, or the parent work item when no internal link is focused
- `CTRL+L` - Open worklog
- `CTRL+T` - Log work

#### Attachments Tab

![Work item attachments tab](/static/work_item_attachments_tab.svg)

Manage files attached to work items.

**Keybindings**:

- `CTRL+N` - Add new attachment when the Attachments tab is active
- `CTRL+D` - Delete the selected attachment
- `Enter` - Open attachment in browser
- `CTRL+S` - Download attachment
- `CTRL+O` - Open attachment in browser

#### Subtasks Tab

![Work item subtasks tab](/static/work_item_subtasks_tab.svg)

Manage subtasks for the current work item.

**Keybindings**:

- `CTRL+N` - New subtask when the Subtasks tab is active
- `CTRL+B` - Clone selected subtask
- `CTRL+E` - Edit selected subtask summary
- `Ctrl+G` - Load selected subtask
- `Enter` - Load selected subtask
- `CTRL+O` - Open subtask in browser

#### Web Links Tab

![Work item web links tab](/static/work_item_web_links_tab.svg)

Manage remote links associated with work items.

**Keybindings**:

- `CTRL+N` - Add new web link when the Web Links tab is active
- `CTRL+D` - Delete selected web link
- `e` - Edit web link
- `CTRL+O` - Open link in browser

#### Comments Tab

![Work item comments tab](/static/work_item_comments_tab.svg)

Manage work item comments.

**Keybindings**:

- `CTRL+N` - Add new comment when the Comments tab is active
- `CTRL+D` - Delete selected comment
- `CTRL+E` - Edit comment
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

When the worklog list is open:

- `CTRL+D` - Delete the selected worklog
- `CTRL+E` - Edit the selected worklog
- `CTRL+O` - Open the selected worklog in browser

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
This shortcut is contextual and applies from the main search/results view.

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

Press `Ctrl+P` to access commands.

The command palette is contextual: it includes commands registered for the
currently focused screen, widget, or loaded work item. Commands hidden from the
footer can still appear here when they are intentionally registered.

### Available Commands

**Insertion Commands** (available in text editors only):

- **Insert User Mention**: Add a mention to a Jira user
- **Insert Decision**: Add a decision marker for meeting notes
- **Insert Panel/Alert**: Add styled panels (NOTE, TIP, IMPORTANT, WARNING, CAUTION)

**UI Commands**:

- **Show Footer / Hide Footer**: Toggle footer visibility for the current session
- **Debug Information**: Open the debug information screen
- **Quick Navigation**: Jump directly to a work item by key
- **Contextual Work Item Commands** when a work item is loaded

## Jumper Mode

![Jumper mode](/tests/__snapshots__/test_jumper/TestJumper.test_main_screen_jumper_overlay.svg)

The jumper overlay (`Ctrl+\`) allows quick keyboard navigation to different parts
of the interface.

Each active widget is assigned a key. Press the corresponding key to jump
directly to that widget.

## Additional Resources

- **Configuration**: See [configuration.md](configuration.md) for all configuration options
- **Markdown/ADF**: See [markdown_to_adf_conversion.md](markdown_to_adf_conversion.md) for conversion details
- **Jira JQL**: [Jira Query Language documentation](https://support.atlassian.com/jira-service-management-cloud/docs/use-advanced-search-with-jira-query-language-jql/)
