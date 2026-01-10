# gojeera Configuration

This guide covers all configuration options and settings for gojeera.
All settings can be provided in a YAML file or via environment variables.

## Initial Configuration

> [!TIP]
> The application provides a sample configuration file called
> `gojeera.example.yaml` that you can use to define yours.

Before using the application you need to provide basic configuration.
All settings can be provided in a YAML file.

The application uses the
[XDG specification](https://specifications.freedesktop.org/basedir-spec/latest/)
to locate config (and log) files. The default config file name is
`config.yaml`. You can override the location via the environment variable
`GOJEERA_CONFIG_FILE`. The application loads the config file this way:

1. If `GOJEERA_CONFIG_FILE` is set, use that file.
2. If not, if `XDG_CONFIG_HOME` is set, load
   `${XDG_CONFIG_HOME}/gojeera/config.yaml`.
3. If not, load `${HOME}/.config/gojeera/config.yaml`.

## Jira API Credentials

You must provide the following values to connect to your Jira instance:

- `jira_api_username`: username for connecting to your Jira API.
- `jira_api_token`: token for connecting to your Jira API. This can be
  your Personal Access Token (PAT).
- `jira_api_base_url`: the base URL of your Jira API.

**Example:** Assuming your configuration file is at
`${XDG_CONFIG_HOME}/gojeera/config.yaml`:

```yaml
jira_api_username: "bart@simpson.com"
jira_api_token: "12345"
jira_api_base_url: "https://<your-jira-instance-hostname>.atlassian.net"
```

## Choosing the Jira Platform

Jira is available via the
[Jira Cloud Platform's API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/#about)
and via the
[Jira Data Center's API (aka. Jira on-premises)](https://developer.atlassian.com/server/jira/platform/rest/v11001/intro/#gettingstarted).
gojeera can connect to both platforms, although support for Jira Data
Center's API is limited.

By default, gojeera connects to Jira Cloud Platform's API. However, if
you want to use gojeera with your organization's on-premises
installation, configure this via the config file:

```yaml
cloud: False
```

## Choosing the API Version

> [!IMPORTANT]
> When `cloud: False`, gojeera will use the correct version for the API
> and ignore the value of `jira_api_version`. In other words,
> `jira_api_version` is only applicable when `cloud: True`.

gojeera supports
[Jira REST API v3](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/) and
[Jira REST API v2](https://developer.atlassian.com/cloud/jira/platform/rest/v2/intro/).

By default, gojeera uses Jira REST API v3, which is suited for Jira
cloud instances. However, Jira also offers an on-premises
installation mode where the API version may be v2 instead. To address
this, gojeera lets you choose which version of the API to use.

To set the API version, update your configuration file:

```yaml
jira_api_version: 2
```

## Configuration Settings Reference

All settings can be set using environment variables with the format
`GOJEERA_<name>`, where `<name>` is the setting name in the table below.

**Example:** these are equivalent:

- `GOJEERA_JIRA_API_USERNAME=foo@bar`
- `jira_api_username=foo@bar`

### Core Settings

| Name                        | Type   | Required | Default | Description                                                                                                                                 |
| --------------------------- | ------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `jira_api_username`         | `str`  | `Yes`    | `None`  | Username to use for connecting to the Jira API                                                                                              |
| `jira_api_token`            | `str`  | `Yes`    | `None`  | Token to use for connecting to the Jira API                                                                                                 |
| `jira_api_base_url`         | `str`  | `Yes`    | `None`  | Base URL of the Jira API                                                                                                                    |
| `jira_base_url`             | `str`  | `No`     | `None`  | Base URL of your Jira application. Used for building web links. Example: `https://<hostname>.atlassian.net`                                 |
| `jira_account_id`           | `str`  | `No`     | `None`  | ID of the Jira user using the application. Useful for auto-selecting your user in dropdowns and used as default reporter for new work items |
| `jira_user_group_id`        | `str`  | `No`     | `None`  | ID of the group that contains all (or most) of the Jira users in your installation. Used as a fallback mechanism to fetch available users   |
| `cloud`                     | `bool` | `No`     | `True`  | Set to False if using Jira Data Center (on-premises)                                                                                        |
| `jira_api_version`          | `int`  | `No`     | `3`     | API version to use. Only applicable when `cloud: True`                                                                                      |
| `use_bearer_authentication` | `bool` | `No`     | `False` | Set to True if your Jira instance uses Bearer authentication instead of Basic                                                               |

### Search and Display Settings

| Name                                                | Type   | Required | Default                               | Description                                                                                             |
| --------------------------------------------------- | ------ | -------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `search_results_per_page`                           | `int`  | `No`     | `30`                                  | Number of results to show in the search results                                                         |
| `search_issues_default_day_interval`                | `int`  | `No`     | `15`                                  | Days worth of issues to fetch when no other search criteria has been defined                            |
| `search_results_truncate_work_item_summary`         | `int`  | `No`     | `None`                                | When defined, work item summaries in search results are truncated to this length                        |
| `search_results_style_work_item_status`             | `bool` | `No`     | `True`                                | If True, work item status is styled in search results                                                   |
| `search_results_style_work_item_type`               | `bool` | `No`     | `True`                                | If True, work item type is styled in search results                                                     |
| `search_results_default_order`                      | `str`  | `No`     | `WorkItemsSearchOrderBy.CREATED_DESC` | Default order for search results                                                                        |
| `search_results_page_filtering_enabled`             | `bool` | `No`     | `True`                                | If True, users can refine search in search results                                                      |
| `search_results_page_filtering_minimum_term_length` | `int`  | `No`     | `3`                                   | Minimum characters required to refine search results                                                    |
| `full_text_search_minimum_term_length`              | `int`  | `No`     | `3`                                   | Minimum length of search term for full-text search. gojeera enforces a value >= 3                       |
| `enable_advanced_full_text_search`                  | `bool` | `No`     | `True`                                | If True, full-text search works on any text-based Jira field; otherwise only on summary and description |

### Work Item Settings

| Name                          | Type   | Required | Default | Description                                                                                                                     |
| ----------------------------- | ------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `show_issue_web_links`        | `bool` | `No`     | `True`  | If True, application retrieves remote links related to a work item                                                              |
| `ignore_users_without_email`  | `bool` | `No`     | `True`  | Controls whether Jira users without an email should be included in user lists                                                   |
| `default_project_key_or_id`   | `str`  | `No`     | `None`  | Case-sensitive string that identifies a Jira project. If set, used as default selected project and only this project is fetched |
| `custom_field_id_sprint`      | `str`  | `No`     | `None`  | Name of custom field used to identify sprints. Example: `customfield_12345`                                                     |
| `fetch_attachments_on_delete` | `bool` | `No`     | `True`  | If True, fetch attachments after deleting one (more accurate but slower)                                                        |
| `fetch_comments_on_delete`    | `bool` | `No`     | `True`  | If True, fetch comments after deleting one (more accurate but slower)                                                           |

### JQL and Queries

| Name                                      | Type   | Required | Default | Description                                                                                                                                              |
| ----------------------------------------- | ------ | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pre_defined_jql_expressions`             | `dict` | `No`     | `None`  | Pre-defined JQL expressions. See [Configuring Pre-defined JQL Expressions](#configuring-pre-defined-jql-expressions)                                     |
| `jql_expression_id_for_work_items_search` | `int`  | `No`     | `None`  | If set to an expression ID from `pre_defined_jql_expressions`, app uses this expression to retrieve work items when no criteria or JQL query is provided |

### UI Settings

| Name                                  | Type   | Required | Default | Description                                                                                                  |
| ------------------------------------- | ------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `tui_title`                           | `str`  | `No`     | `None`  | Optional title for the application, displayed in top bar                                                     |
| `tui_custom_title`                    | `str`  | `No`     | `None`  | Custom title for the application. Overrides `tui_title` if set. If set to empty string, no title is rendered |
| `tui_title_include_jira_server_title` | `bool` | `No`     | `True`  | See [Include Jira Server Title in the UI Title](#include-jira-server-title-in-the-ui-title)                  |
| `theme`                               | `str`  | `No`     | `None`  | Name of Textual theme to use. See [Choosing a Theme](#choosing-a-theme)                                      |
| `confirm_before_quit`                 | `bool` | `No`     | `False` | If True, app asks for confirmation before quitting                                                           |
| `enable_images_support`               | `bool` | `No`     | `True`  | If True, application displays images attached to work items in Attachments tab                               |

### Startup and Performance

| Name                              | Type   | Required | Default | Description                                                                 |
| --------------------------------- | ------ | -------- | ------- | --------------------------------------------------------------------------- |
| `on_start_up_only_fetch_projects` | `bool` | `No`     | `True`  | See [Fetching Only Projects on Startup](#fetching-only-projects-on-startup) |
| `search_on_startup`               | `bool` | `No`     | `False` | When True, application searches work items on startup                       |

### Advanced Field Configuration

| Name                                  | Type         | Required | Default | Description                                                                                                                                                                                                 |
| ------------------------------------- | ------------ | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `enable_updating_additional_fields`   | `bool`       | `No`     | `False` | When True, app displays (some) custom/system fields in issue details tab allowing updates. See [Enable Updating Additional Fields](#enable-updating-additional-fields)                                      |
| `update_additional_fields_ignore_ids` | `list[dict]` | `No`     | `None`  | When `enable_updating_additional_fields = True`, fields with these IDs or keys are ignored in Details tab                                                                                                   |
| `enable_creating_additional_fields`   | `bool`       | `No`     | `False` | When True, app renders ALL optional fields from create-metadata when creating work items. See [Configuring Optional Fields in Create Work Item Form](#configuring-optional-fields-in-create-work-item-form) |
| `create_additional_fields_ignore_ids` | `list[str]`  | `No`     | `None`  | List of optional field IDs to exclude from create work item form. Example: `['priority', 'customfield_10001']`                                                                                              |

### Other Settings

| Name                           | Type               | Required | Default   | Description                                                                                                                |
| ------------------------------ | ------------------ | -------- | --------- | -------------------------------------------------------------------------------------------------------------------------- |
| `attachments_source_directory` | `str`              | `No`     | `/`       | Directory to start the search of files to attach to work items. User can navigate through sub-directories                  |
| `log_file`                     | `str`              | `No`     | `None`    | Name of the log file to use                                                                                                |
| `log_level`                    | `str`              | `No`     | `WARNING` | Python's `logging` level to use                                                                                            |
| `ssl`                          | `SSLConfiguration` | `No`     | `None`    | Settings for SSL                                                                                                           |
| `git_repositories`             | `dict`             | `No`     | `None`    | Configure Git repos available for creating branches from the UI. See [Setting Git Repositories](#setting-git-repositories) |

## Advanced Configuration

### Choosing a Theme

You can set the theme for the UI using
[Textual Themes](https://textual.textualize.io/guide/design/).

The default theme is `textual-dark`. If the theme you provide is not
recognized, this default will be used.

**Setting the theme in the configuration file:**

```yaml
theme: "monokai"
```

**Setting the theme on startup:**

You can provide the theme name using the `--theme` (`-t`) argument when
launching via the CLI command `gojeera ui`:

```bash
gojeera ui --theme textual-light
```

The application sets the theme based on these rules:

1. `--theme` (`-t`) has priority over `config.theme`
2. If neither `--theme` nor `config.theme` are defined, use the default
3. If the theme name is not recognized, use the default

The app provides a CLI command to list supported themes:

```bash
gojeera themes
```

### Configuring Pre-defined JQL Expressions

To define your own JQL expressions, use the setting
`pre_defined_jql_expressions`. These expressions are accessible via the
JQL Expression Editor. Open the editor by going to the JQL Expression
input and pressing `^e`. The setting accepts a dictionary of
user-defined IDs whose values are expression details including a label
and a string with the JQL expression value. The label is used as the
dropdown selector label.

**Example:**

```yaml
pre_defined_jql_expressions:
  1:
    {
      "label": "Find work created by John and sort by created asc",
      "expression": "creator = 'john' order by created asc",
    }
  2:
    {
      "label": "Find work due on 2100-12-31 for production",
      "expression": "dueDate = '2100-12-31' AND environment = 'production'",
    }
```

### Fetching Only Projects on Startup

When this setting is `True`, the application only loads the list of
available projects at startup. Status codes, users, and work item types
are loaded when the user selects a project. If `False`, the application
loads (fetches from the API) status codes, users, and work item types
in addition to projects, making startup a bit slower.

### Include Jira Server Title in the UI Title

If `tui_title_include_jira_server_title = True`, the application
fetches server information from the Jira API and uses the server's
title or server base URL to build the application title. If `False`,
the title is set to the default or to the value of `tui_custom_title`
if defined.

You can use `tui_custom_title` to set a custom title. If set to an
empty string (`""`), no title is rendered at all. If not set, the
application falls back to using `tui_title`.

### Enable Filtering Search Results

gojeera allows you to further refine search results by filtering work
items based on their summary. This feature is controlled by 2
configuration variables.

The variable `search_results_page_filtering_enabled` controls whether
this feature is enabled or not. The default is enabled. When enabled,
the user can press `/` while focused on the search results table. Doing
so shows an input field that the user can use to refine results by
filtering items whose summary field do not match the filtering
criteria.

In addition, the variable
`search_results_page_filtering_minimum_term_length` defines the minimum
number of characters required to start filtering results. The default
is 3 but can be set to any value >= 1.

### Setting the Default Order for Search Results

You can control the default sort order for search results using the
`search_results_default_order` configuration option. This determines
how issues are ordered when you perform a search in gojeera.

**Accepted values:**

- `created asc`
- `created desc`
- `priority asc`
- `priority desc`
- `key asc`
- `key desc`

These correspond to the available sort orders in gojeera. The value you
set must match one of the above exactly.

**Example:**

```yaml
search_results_default_order: "created desc"
```

You can still change the order interactively in the UI; this setting
only controls the initial/default value.

### Setting Git Repositories

gojeera allows users to create Git branches
directly from the UI. Once you select a work item, press `^g` to open a
dialog to create a new Git branch using the work item's key as the
initial value for the branch.

To support this, you need to configure the repositories that the tool
can use to create branches. In principle, there is no direct connection
between projects and Git repos. A project may use different repos and a
repo may be used in different projects. Because of this, you need to
configure the Git repos you want to use.

You can do this via the configuration variable `git_repositories`.
Using this setting, you define repositories specifying an ID, a name,
and a path to the repository's `.git` directory.

**Example:**

```yaml
git_repositories:
  1:
    name: "My Project A"
    path: "/projects/project-a/.git"
  2:
    name: "My Project B"
    path: "/projects/project-b/.git"
```

Using this configuration, gojeera displays these repositories, and you
can choose the target repo for creating a new branch.

### Enable Updating Additional Fields

By default, gojeera does not allow users to view and update these
fields. To enable this feature, set the variable
`enable_updating_additional_fields: True`.

If you want to disable viewing/updating a
specific system/custom field enabled by this feature, you can add the
field's ID (or key) to a list of fields to ignore. To do so, set the
configuration variable `update_additional_fields_ignore_ids`.

```yaml
enable_updating_additional_fields: True
update_additional_fields_ignore_ids:
  - customfield_12345
```

### Configuring Optional Fields in Create Work Item Form

By default, gojeera does not allow users to view and update these
fields. To enable this feature, set the variable
`enable_creating_additional_fields: True`.

Use `create_additional_fields_ignore_ids` to hide specific fields from
the default set. This is useful when you want to hide problematic
fields.

```yaml
create_additional_fields_ignore_ids:
  - customfield_10001
  - customfield_10002
```
