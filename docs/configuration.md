# Configuration

gojeera uses a YAML configuration file to customize its behavior and connect to
your Jira instance. This document describes all available configuration options.

## Configuration File Location

By default, gojeera looks for a configuration file at:

- `~/.config/gojeera/gojeera.yaml` (Linux/macOS)

You can override this location by setting the `GOJEERA_CONFIG_FILE`
environment variable:

```bash
export GOJEERA_CONFIG_FILE=/path/to/your/config.yaml
```

## Configuration via Environment Variables

All configuration options can be set via environment variables using the
prefix `GOJEERA_`. For nested configurations, use double underscores
(`__`) as delimiters.

Examples:

```bash
export GOJEERA_JIRA__API_USERNAME="your-email@example.com"
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

## Required Configuration

### Jira API Connection

These settings are **required** to connect to your Jira instance:

```yaml
jira:
  api_username: "your-email@example.com"
  api_token: "your-api-token"
  api_base_url: "https://your-instance.atlassian.net"
```

- **`api_username`** (**required**): Your Jira username or email address
- **`api_token`** (**required**): Your Jira API token
  ([generate one here](https://id.atlassian.com/manage-profile/security/api-tokens))
- **`api_base_url`** (**required**): The base URL of your Jira instance

## Optional Configuration

### Display Settings

```yaml
show_work_item_web_links: true
search_results_per_page: 20
search_results_truncate_work_item_summary: null
theme: null
obfuscate_personal_info: false
enable_images_support: true
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
- **`obfuscate_personal_info`** (default: `false`): Obfuscate
  username and instance URL in the app header for privacy
- **`enable_images_support`** (default: `true`): Display images
  attached to work items in the Attachments tab

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
    - "1"
    - "2"
    - "3"
    - "q"
    - "w"
    - "e"
    - "a"
    - "s"
    - "d"
```

- **`jumper.enabled`** (default: `true`): Enable the jumper
  overlay for quick navigation
- **`jumper.keys`** (default: `['1', '2', '3', 'q', 'w',
'e', 'a', 's', 'd']`): Keys to use for jumper targets

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
```

- **`confirm_before_quit`** (bool, default: `true`): Show a
  confirmation dialog before quitting the application

## Complete Example Configuration

See [`gojeera.example.yaml`](../gojeera.example.yaml) for a complete
example configuration file with common settings.

## Minimal Configuration Example

The minimum required configuration to get started:

```yaml
jira:
  api_username: "your-email@example.com"
  api_token: "your-api-token-here"
  api_base_url: "https://your-instance.atlassian.net"
```

## Configuration Tips

1. **Privacy**: If sharing screenshots or demos, enable
   `obfuscate_personal_info: true` to hide your username and instance
   URL.

2. **Sprint selection**: To enable the sprint dropdown when creating or
   updating work items, set `enable_sprint_selection: true`.
   The dropdown will show only active and future
   sprints from all boards in the project.

3. **JQL filters**: Use local filters for quick access to common
   queries. Use remote filters to sync with your team's saved filters in
   Jira.
