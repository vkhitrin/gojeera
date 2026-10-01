# Configuration

## Configuration File Location

By default, gojeera looks for a configuration file at:

- `~/.config/gojeera/gojeera.yaml` (Linux/macOS)

You can override this location by setting the `GOJEERA_CONFIG_FILE`
environment variable:

```bash
export GOJEERA_CONFIG_FILE=/path/to/your/config.yaml
```

## Authentication

Create profiles for authentication:

```bash
gojeera auth login
```

Or use environment variables:

```bash
# API token authentication
export GOJEERA_JIRA__API_EMAIL="your-email@example.com"
export GOJEERA_JIRA__API_BASE_URL="https://your-instance.atlassian.net"
export GOJEERA_JIRA__API_TOKEN="your-api-token"
# OAuth2
export GOJEERA_JIRA__OAUTH2_ACCESS_TOKEN="your-access-token"
export GOJEERA_JIRA__OAUTH2_REFRESH_TOKEN="your-refresh-token"
export GOJEERA_JIRA__OAUTH2_CLIENT_SECRET="your-client-secret"
```

Environment variables override the operating system keyring.

`gojeera auth login` stores API token profiles in the same shape as Atlassian
CLI profiles: `site` may be a hostname such as `your-instance.atlassian.net`,
`auth_type` is written as `api_token`, and `cloud_id` plus `account_id` are
derived during the authentication check when Jira returns them.

### OAuth2 Scope Requirements

gojeera's default OAuth2 flow requests Jira platform scopes and Jira Software
Agile scopes, plus Jira Service Management request scopes for public/internal
request comments. The Agile scopes are required for sprint selection and board /
sprint discovery:

- `read:project:jira`
- `read:board-scope:jira-software`
- `read:sprint:jira-software`
- `write:sprint:jira-software`
- `write:servicedesk-request`

If you update the OAuth2 scopes for an existing profile, you must run
`gojeera auth login` again and complete the browser consent flow to obtain a
new token with the updated scopes.

## Configuration via Environment Variables

All configuration options can be set via environment variables using the
prefix `GOJEERA_`. For nested configurations, use double underscores
(`__`) as delimiters.

Examples:

```bash
export GOJEERA_JIRA__API_EMAIL="your-email@example.com"
export GOJEERA_JIRA__API_TOKEN="your-api-token"
export GOJEERA_JIRA__API_BASE_URL="https://your-instance.atlassian.net"
export GOJEERA_LOG_LEVEL="DEBUG"
export GOJEERA_THEME="monokai"
```

## Configuration Precedence

Configuration is loaded in the following order (later sources override
earlier ones):

1. Default values
2. YAML configuration file
3. Environment variables
4. CLI arguments (for specific options)

## Optional Configuration

### Display Settings

```yaml
show_work_item_web_links: true
search_results_per_page: 20
search_results_truncate_work_item_summary: null
theme: null
```

- **`show_work_item_web_links`** (default: `true`): Retrieve and
  display remote links related to work items
- **`search_results_per_page`** (default: `20`, range: 1-200):
  Number of search results to display per page
- **`search_results_truncate_work_item_summary`** (optional):
  Maximum length for work item summaries in search results (no
  truncation if not set)
- **`theme`** (optional): Name of the Textual theme to use for
  the UI

### Search Behavior

```yaml
enable_advanced_full_text_search: true
search_on_startup: false
```

- **`enable_advanced_full_text_search`** (default: `true`):
  Enable full-text search across all text fields including comments
  (may be slower). If `false`, only search in summary and description
  fields
- **`search_on_startup`** (default: `false`): Automatically
  trigger a search when the UI starts (can also be set via CLI argument
  `--search-on-startup`)

### For You

Press **F10** or open **For You** from the command palette to see a personal
work feed in a modal. Select a row with Enter to open the work item, Ctrl+R
to refresh, or Escape to close. Selecting an item closes clean overlays and
returns to the workspace; an editor with unsaved changes blocks navigation
until you finish or close it. Startup behavior is unchanged.

```yaml
for_you:
  due_soon_days: 7
  recent_days: 7
  items_per_section: 50
  mention_scan_items: 50
  comments_per_item: 100
```

- **`due_soon_days`** (1–365): Open assignments overdue or due through the end
  of the day this many days ahead, using Jira's JQL timezone. Done-category
  items are excluded; overdue items have no lower date bound.
- **`recent_days`** (1–365): Lookback for assigned/watched updates and comment
  activity. Updated items can include completed work and your own changes.
- **`items_per_section`** (1–200): Maximum displayed items per tab. Due items
  are ordered earliest first; updates and mentions are newest first.
- **`mention_scan_items`** (1–200): Maximum recently updated accessible items
  whose comments are scanned for mentions, across all projects, not just
  assigned/watched items. Only candidates returned by an account-ID comment text
  search within `recent_days` are scanned; there is no broad recent-update fallback.
  Increase this setting to scan more candidates, at the cost of additional requests.
- **`comments_per_item`** (1–500): Maximum newest comments scanned per item,
  following Jira comment pagination. At most four items are scanned concurrently.

Mentions are **best effort, not notifications**. A result requires an ADF mention
with your exact account ID in a comment created or edited within `recent_days`.
An edited old comment may still contain an old mention; the API does not tell us
when that mention was added. Comment text search is only a candidate-selection
hint: it may not index mentions on every Jira instance. An empty search makes no
comment requests; a failed search does not fall back to unrelated recent updates. Search candidates are paginated up to `mention_scan_items` and
deduplicated. Only those candidates' comments are fetched to verify exact ADF
account-ID mentions and comment timestamps; text matches alone never count.
Descriptions are not scanned. Older comments beyond the cap, items beyond the
scan limit, restricted comments, unindexed mentions, and search-index delays
can cause missed mentions. Failed queries and unavailable comments produce
section-specific notifications. Result and scan limits do not trigger warnings;
successful empty results also remain quiet.
Tables have no captions or tab tooltips. An item may
appear in multiple tabs but only once per tab. Nothing is marked read, and there is no background polling or persistent
feed cache; opening or refreshing the modal fetches fresh data.

Environment overrides use the usual nested syntax, for example
`GOJEERA_FOR_YOU__RECENT_DAYS=3`.

### User Management

```yaml
ignore_users_without_email: true
```

- **`ignore_users_without_email`** (default: `true`): Exclude
  Jira users without an email address from user lists and assignment
  options

### Custom Fields

```yaml
enable_sprint_selection: true
enable_updating_additional_fields: false
update_additional_fields_ignore_ids: null
enable_creating_additional_fields: false
create_additional_fields_ignore_ids: null
```

- **`enable_sprint_selection`** (default: `true`): Enable the
  sprint selection dropdown when creating or updating work items. When
  `false`, the sprint field uses a plain text input
- **`enable_updating_additional_fields`** (default: `false`):
  Allow viewing and updating additional custom and system fields
- **`update_additional_fields_ignore_ids`** (optional): List
  of field IDs to exclude from the Details tab when
  `enable_updating_additional_fields` is `true`
- **`enable_creating_additional_fields`** (default: `false`): Show
  additional optional fields when creating work items. When `false`,
  only `duedate` and `priority` are shown
- **`create_additional_fields_ignore_ids`** (optional): List
  of field IDs to exclude from the create form. Example:
  `['customfield_10050', 'customfield_10051']`

### JQL Filters

#### Local Filters

Define local JQL filters that appear in the autocomplete dropdown with a
⌂ symbol:

```yaml
jql_filters:
  - label: "Work in the current sprint"
    expression: "sprint in openSprints()"
  - label: "My open work items"
    expression: >
      assignee = currentUser() AND status != Done
      ORDER BY priority DESC
  - label: "Recently updated"
    expression: "updated >= -7d ORDER BY updated DESC"

jql_filter_label_for_work_items_search: "Work in the current sprint"
```

- **`jql_filters`** (optional): List of predefined JQL
  filters. Each entry must have:
  - `label` (string): Display name for the filter
  - `expression` (string): The JQL query expression
- **`jql_filter_label_for_work_items_search`** (optional):
  Default filter label to use when no search criteria is provided. Must
  match one of the labels in `jql_filters`

#### Remote Filters

Fetch saved filters from your Jira instance (shown with ☁ symbol in
autocomplete):

```yaml
fetch_remote_filters:
  enabled: true
  include_shared: false
  starred_only: false
  cache_ttl: 3600
```

- **`fetch_remote_filters.enabled`** (default: `false`): Enable
  fetching filters from the Jira API
- **`fetch_remote_filters.include_shared`** (default: `false`):
  Include filters shared with you via groups/projects. If `false`, only
  fetch your personal filters
- **`fetch_remote_filters.starred_only`** (default: `false`):
  Only fetch filters you've starred (marked as favorite)
- **`fetch_remote_filters.cache_ttl`** (default: `3600`): Cache
  duration in seconds before re-fetching from the server

### Jumper - Quick Navigation

The jumper overlay allows quick keyboard navigation between widgets
(activate with `Ctrl+\`):

```yaml
jumper:
  enabled: true
  keys:
    - "q"
    - "w"
    - "e"
    - "a"
    - "s"
    - "d"
    - "z"
    - "x"
    - "c"
```

- **`jumper.enabled`** (default: `true`): Enable the jumper
  overlay for quick navigation
- **`jumper.keys`** (default: `['q', 'w', 'e', 'a', 's', 'd', 'z', 'x', 'c']`):
  Keys to use for jumper targets

### Logging

```yaml
log_file: null
log_level: "WARNING"
```

- **`log_file`** (optional): Path to the log file. Set to an
  empty string to disable file logging
- **`log_level`** (default: `"WARNING"`): Log level using
  Python's logging names: `CRITICAL`, `FATAL`, `ERROR`, `WARN`,
  `WARNING`, `INFO`, `DEBUG`, `NOTSET`

### SSL Configuration

Configure SSL/TLS settings for secure connections:

```yaml
ssl:
  verify_ssl: true
  ca_bundle: null
  certificate_file: null
  key_file: null
  password: null
```

- **`ssl.verify_ssl`** (default: `true`): Enable SSL certificate
  verification for HTTP requests
- **`ssl.ca_bundle`** (optional): Path to a custom CA bundle
  file
- **`ssl.certificate_file`** (optional): Path to a client-side
  certificate file (e.g., `cert.pem`)
- **`ssl.key_file`** (optional): Path to the private key file
  for the certificate
- **`ssl.password`** (optional): Password for the encrypted
  key file

### Miscellaneous

```yaml
confirm_before_quit: true
show_footer: true
```

- **`confirm_before_quit`** (bool, default: `true`): Show a
  confirmation dialog before quitting the application
- **`show_footer`** (bool, default: `true`): Show the footer with
  key bindings at the bottom of the screen

You can also toggle the footer from the command palette with
`Show Footer` / `Hide Footer`, or by pressing `F11`. These controls are
session-only and do not modify your config file.

## Complete Example Configuration

See [`gojeera.example.yaml`](../gojeera.example.yaml) for a complete
example configuration file with common settings.

## Minimal Configuration Example

Authentication is not stored in `gojeera.yaml`. The minimum setup is:

1. Create a profile with `gojeera auth login`
2. Optionally add non-auth settings to `gojeera.yaml`

For example:

```yaml
theme: null
search_on_startup: false
show_footer: true
```

## Configuration Tips

1. **Sprint selection**: To enable the sprint dropdown when creating or
   updating work items, set `enable_sprint_selection: true`.
   The dropdown will show only active and future
   sprints from all boards in the project.

2. **JQL filters**: Use local filters for quick access to common
   queries. Use remote filters to sync with your team's saved filters in
   Jira.
