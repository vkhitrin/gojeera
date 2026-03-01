# Markdown ↔ ADF Conversion Reference

## Overview

This document describes how **gojeera** converts between Markdown and Atlassian
Document Format (ADF).

gojeera uses **GitHub Flavored Markdown** as a baseline for parsing
Markdown input.

## References

- **ADF Documentation**: <https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/>
- **ADF JSON Schema**: <https://unpkg.com/@atlaskit/adf-schema@51.5.7/dist/json-schema/v1/full.json>
- **markdown-it-py**: <https://github.com/executablebooks/markdown-it-py>
- **atlas-doc-parser**: <https://github.com/MacHu-GWU/atlas_doc_parser-project>

## Supported ADF Nodes (ADF → Markdown)

### Block Nodes

| ADF Node Type   | Markdown Output     | Processing Function           |
| --------------- | ------------------- | ----------------------------- |
| `paragraph`     | Paragraph           | `atlas_doc_parser`            |
| `heading` (1-6) | `#` headers         | `atlas_doc_parser`            |
| `bulletList`    | `- item`            | `atlas_doc_parser`            |
| `orderedList`   | `1. item`           | `atlas_doc_parser`            |
| `listItem`      | List item           | `atlas_doc_parser`            |
| `taskList`      | `☐` / `☑`           | `_render_task_checkboxes()`   |
| `taskItem`      | `☐ text` / `☑ text` | `_render_task_checkboxes()`   |
| `codeBlock`     | `lang\n...\n`       | `atlas_doc_parser` + fixes    |
| `blockquote`    | `> text`            | `atlas_doc_parser`            |
| `panel`         | `> [!TYPE]`         | `_convert_panels_to_alerts()` |
| `table`         | Markdown table      | `atlas_doc_parser`            |
| `tableRow`      | Table row           | `atlas_doc_parser`            |
| `tableHeader`   | Header cell         | `atlas_doc_parser`            |
| `tableCell`     | Body cell           | `atlas_doc_parser`            |
| `rule`          | `---`               | `atlas_doc_parser`            |

### Inline Nodes

| ADF Node Type  | Markdown Output                       | Processing Function                                                                  |
| -------------- | ------------------------------------- | ------------------------------------------------------------------------------------ |
| `text`         | Plain text                            | `atlas_doc_parser`                                                                   |
| `mediaSingle`  | `(See file "..." in attachments tab)` | `replace_media_with_text()`                                                          |
| `media`        | Attachment reference                  | `replace_media_with_text()`                                                          |
| `mention`      | `[@User](url/jira/people/id)`         | `replace_mentions_with_links()`                                                      |
| `status`       | `[status:c]text`                      | `replace_status_with_colored_text()` + `_convert_status_markers_to_inline_code()`    |
| `date`         | `[date]YYYY-MM-DD`                    | `replace_date_with_colored_text()` + `_convert_date_markers_to_inline_code()`        |
| `decisionList` | Blockquote with decisions             | `replace_decision_with_styled_text()`                                                |
| `decisionItem` | `[decision:s]text`                    | `replace_decision_with_styled_text()` + `_convert_decision_markers_to_inline_code()` |

### Text Marks (Inline Styles)

| ADF Mark | Markdown      |
| -------- | ------------- |
| `strong` | `**text**`    |
| `em`     | `*text*`      |
| `code`   | `text`        |
| `link`   | `[text](url)` |
| `strike` | `~~text~~`    |

## Supported Markdown Patterns (Markdown → ADF)

### Block Patterns

| Markdown Pattern    | ADF Node Type                | Processing Function            |
| ------------------- | ---------------------------- | ------------------------------ |
| Paragraph           | `paragraph`                  | `_convert_tokens_to_adf()`     |
| `#` - `######`      | `heading` (level 1-6)        | `_convert_tokens_to_adf()`     |
| `- item`            | `bulletList` + `listItem`    | `_convert_tokens_to_adf()`     |
| `1. item`           | `orderedList` + `listItem`   | `_convert_tokens_to_adf()`     |
| `- [ ]` / `- [x]`   | `taskList` + `taskItem`      | `_convert_task_list_tokens()`  |
| `lang`              | `codeBlock`                  | `_convert_tokens_to_adf()`     |
| `> text`            | `blockquote`                 | `_convert_blockquote_tokens()` |
| `> [!NOTE]`         | `panel` (info)               | `_convert_blockquote_tokens()` |
| `> [!TIP]`          | `panel` (success)            | `_convert_blockquote_tokens()` |
| `> [!IMPORTANT]`    | `panel` (note)               | `_convert_blockquote_tokens()` |
| `> [!WARNING]`      | `panel` (warning)            | `_convert_blockquote_tokens()` |
| `> [!CAUTION]`      | `panel` (error)              | `_convert_blockquote_tokens()` |
| Markdown table      | `table` + `tableRow` + cells | `_convert_table_tokens()`      |
| `\| A \|` + `\|-\|` | Single-cell table workaround | `_convert_table_tokens()`      |
| `---`               | `rule`                       | `_convert_tokens_to_adf()`     |

### Inline Patterns

| Markdown Pattern | ADF Node/Mark | Processing Function        |
| ---------------- | ------------- | -------------------------- |
| `**text**`       | `strong` mark | `_convert_inline_tokens()` |
| `*text*`         | `em` mark     | `_convert_inline_tokens()` |
| `text`           | `code` mark   | `_convert_inline_tokens()` |
| `[text](url)`    | `link` mark   | `_convert_inline_tokens()` |
| `~~text~~`       | `strike` mark | `_convert_inline_tokens()` |

**Special case**: Links matching pattern `/jira/people/<account_id>` are
converted to ADF `mention` nodes instead of `link` marks.

## TUI Display Features (Markdown Rendering)

These patterns are rendered with special styling in the gojeera TUI:

### Inline Code Pattern Styling

These patterns use inline code syntax with special prefixes that trigger custom styling:

| Pattern            | Visual Display        |
| ------------------ | --------------------- |
| `[date]YYYY-MM-DD` | Date with background  |
| `[status:n]text`   | Neutral status badge  |
| `[status:r]text`   | Error status badge    |
| `[status:b]text`   | Primary status badge  |
| `[status:g]text`   | Success status badge  |
| `[status:y]text`   | Warning status badge  |
| `[status:p]text`   | Accent status badge   |
| `[status:t]text`   | Teal status badge     |
| `[decision:d]text` | Decided item (⤷)      |
| `[decision:a]text` | Acknowledged item (⤷) |
| `[decision:u]text` | Discussion item (⤷)   |

### Standard Link Styling

User mentions are rendered as standard clickable markdown links:

| Pattern                       | Visual Display      |
| ----------------------------- | ------------------- |
| `[@User](url/jira/people/id)` | Clickable user link |

## Processing Pipelines

### ADF → Markdown Pipeline

The conversion from ADF to Markdown follows these steps (in order):

1. **`fix_ordered_list_attrs()`** - Add missing `attrs` to `orderedList` nodes
2. **`replace_media_with_text()`** - Convert `mediaSingle` to inline attachment
   references
3. **`fix_adf_text_with_marks()`** - Fix spacing issues in `strong`/`em` marks
4. **`fix_codeblock_in_list()`** - Extract `codeBlock` nodes from `listItem` nodes
5. **`replace_mentions_with_links()`** - Convert `mention` nodes to standard
   Markdown links `[@User](url/jira/people/id)`
6. **`replace_date_with_colored_text()`** - Add invisible date markers (U+200B)
7. **`replace_status_with_colored_text()`** - Add invisible status markers
   (U+200C/U+200D)
8. **`replace_decision_with_styled_text()`** - Add invisible decision markers
   (U+200E/U+200F)
9. **`atlas_doc_parser.parse_node().to_markdown()`** - Core ADF→Markdown
   conversion
10. **Postprocessing**:
    - Strip extra blank lines in code blocks
    - Strip leading newlines
    - **`_convert_status_markers_to_inline_code()`** - Convert invisible status
      markers to `[status:c]text`
    - **`_convert_date_markers_to_inline_code()`** - Convert invisible date
      markers to `[date]text`
    - **`_convert_decision_markers_to_inline_code()`** - Convert invisible
      decision markers to `[decision:s]text`
    - **`_render_task_checkboxes()`** - Replace `- [ ]`/`- [x]` with `☐`/`☑`
    - **`_convert_panels_to_alerts()`** - Convert panel blockquotes to
      GitHub alerts
    - **`_normalize_single_cell_tables()`** - Rewrite single-row/single-cell
      table output from `| A<br> |` to `| A |` + `|-|` so Markdown→ADF parsing
      recognizes it as a table

### Markdown → ADF Pipeline

The conversion from Markdown to ADF follows these steps:

1. **`markdown-it-py` parsing** - Parse markdown with GFM + tasklists plugin enabled
2. **Token tree traversal** - Walk the token tree in `_convert_tokens_to_adf()`
3. **Special handlers**:
   - **`_convert_task_list_tokens()`** - Convert task lists (uses tasklists
     plugin)
   - **`_convert_blockquote_tokens()`** - Convert blockquotes and GitHub alerts
     to panels
   - **`_convert_table_tokens()`** - Convert markdown tables to ADF tables
   - **`_convert_inline_tokens()`** - Convert inline content with marks support
     - Links matching `/jira/people/<account_id>` are converted to `mention`
       nodes
4. **Validation** - Track warnings for unsupported patterns (optional)

## Mentions Implementation

### ADF → Markdown (Display)

When converting ADF `mention` nodes to markdown for display:

1. **`replace_mentions_with_links()`** converts `mention` nodes to standard
   Markdown links:
   - Format: `[@Display Name](base_url/jira/people/account_id)`
   - Example: `[@John Doe](https://example.atlassian.net/jira/people/712020:abc)`

### Markdown → ADF (Edit/Create)

When converting Markdown links back to ADF:

1. **`_convert_inline_tokens()`** detects mention links by URL pattern matching:
   - Pattern: href ends with `/jira/people/<account_id>`
   - Example: `[@John Doe](/jira/people/712020:abc)` → ADF `mention` node
     with `id=712020:abc` and `text=@John Doe`
   - Example: `[@John Doe](https://example.atlassian.net/jira/people/712020:abc)` → Same result
2. Regular links not matching the pattern remain as `link` marks
