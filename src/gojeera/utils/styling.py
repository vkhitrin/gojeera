"""Styling utilities for work items."""


def map_jira_status_color_to_textual(jira_color: str | None, for_background: bool = False) -> str:
    """Maps Jira status category color names to Textual colors."""
    if not jira_color:
        return 'surface' if for_background else 'text'

    normalized_color = jira_color.lower().replace('_', '-')

    if for_background:
        color_map = {
            'yellow': 'warning-muted',
            'green': 'success-muted',
            'blue-gray': 'accent-muted',
            'medium-gray': 'surface',
        }
    else:
        color_map = {
            'yellow': 'text-warning',
            'green': 'text-success',
            'blue-gray': 'text-accent',
            'medium-gray': 'text-muted',
        }

    return color_map.get(normalized_color, 'surface' if for_background else 'text')
