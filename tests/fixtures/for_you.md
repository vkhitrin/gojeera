# For You fixtures

The `jira_for_you_*.json` files are synthetic Jira REST v3 responses used by
`tests/test_for_you_snapshots.py` and `tests/test_for_you_fixtures.py`.

- `jira_for_you_due.json`: overdue, due-today, and upcoming items.
- `jira_for_you_updated.json`: recently updated items, including completed work.
- `jira_for_you_mentions.json`: targeted account-ID search candidates.
- `jira_for_you_comments.json`: per-item comment endpoint responses containing
  repeated mentions, a seven-hour-old mention, timezone offsets, plain-text
  account IDs, another user's mention, and a mention outside the lookback window.
- `jira_search_empty.json`: existing empty search response, reused for empty tabs.

The fixture account ID matches `jira_myself.json`. Test helpers fix the service's
reference time at **2026-07-01 12:00 UTC**, while exercising the real API client,
controller parsing, mention verification, and modal. Loading cases hold HTTP
search responses pending and freeze only the native indicator's animation clock.

Snapshot cases cover every tab in populated, empty, and loading states in both
light and dark themes (18 cases). Captions and tab tooltips should not appear.

The usage guide embeds the `populated-due-textual-dark` test snapshot directly.
Its image appears once that SVG baseline is generated; no separate static copy
is needed. Updating that baseline also updates the documentation screenshot.

The maintainer must generate and review the SVG baselines:

```sh
uv run pytest -n auto tests/test_for_you_snapshots.py --snapshot-update
```

Fixture behavior can be checked without executing any snapshot tests:

```sh
uv run pytest -n auto tests/test_for_you_fixtures.py tests/test_for_you.py
```
