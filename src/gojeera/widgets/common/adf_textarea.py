"""ADF TextArea Widget - Handles Atlassian Document Format conversion and rendering."""

import logging

from textual.widgets import Markdown

from gojeera.widgets.common.base_fields import (
    BaseFieldWidget,
    FieldMode,
)

logger = logging.getLogger('gojeera')


class ADFTextAreaWidget(Markdown, BaseFieldWidget):
    """
    Read-only Markdown widget that handles Atlassian Document Format (ADF) conversion.

    This widget automatically converts ADF JSON to Markdown and renders it with formatting.
    It is read-only and displays rich text content with proper rendering (bold, italics, links, etc.).

    Features:
    - Automatic ADF to Markdown conversion on initialization
    - Rich text rendering (not editable plain text)
    - Read-only display
    - Compact field layout

    Usage in UPDATE mode:
        widget = ADFTextAreaWidget(
            mode=FieldMode.UPDATE,
            field_id="customfield_10745",
            title="HL Solution",
            original_value={'type': 'doc', 'content': [...]},  # ADF dict
        )
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        # UPDATE mode parameters
        original_value: dict | str | None = None,
        field_supports_update: bool = True,
    ):
        """
        Initialize an ADFTextAreaWidget.

        Args:
            mode: The field mode (CREATE or UPDATE)
            field_id: Field identifier (e.g., 'customfield_10745')
            title: Display title for the field
            required: Whether the field is required
            original_value: Original value from Jira - can be ADF dict, string, or None
            field_supports_update: Whether field can be updated (ignored - always read-only)
        """
        # Convert ADF to Markdown if needed
        markdown_text = self._convert_to_markdown(original_value)

        # Initialize Markdown widget with converted text
        super().__init__(
            markdown=markdown_text,
            id=field_id,
        )

        # Setup base field properties
        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title or 'Text Area',
            required=required,
            compact=True,
        )

        # Add CSS class for styling
        self.add_class('adf-textarea-readonly')

    def _convert_to_markdown(self, value: dict | str | None) -> str:
        """
        Convert ADF (Atlassian Document Format) to Markdown.

        Args:
            value: The value to convert - can be ADF dict, string, or None

        Returns:
            Markdown string representation
        """
        try:
            from gojeera.utils.adf_helpers import convert_adf_to_markdown

            markdown = convert_adf_to_markdown(value, base_url=None)
            return markdown if markdown.strip() else '_No content_'
        except Exception as e:
            logger.warning(f'Failed to convert ADF to markdown: {e}')
            return str(value) if value else '_No content_'
