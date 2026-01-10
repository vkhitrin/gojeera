"""ADF TextArea Widget - Handles Atlassian Document Format conversion and rendering."""

import logging

from gojeera.utils.adf_helpers import convert_adf_to_markdown
from gojeera.utils.fields import (
    BaseField,
    FieldMode,
)
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown

logger = logging.getLogger('gojeera')


class ADFTextAreaWidget(GojeeraMarkdown, BaseField):
    """
    Read-only GojeeraMarkdown widget that handles Atlassian Document Format (ADF) conversion.
    """

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: dict | str | None = None,
        field_supports_update: bool = True,
    ):
        """
        Initialize an ADFTextAreaWidget.

        Args:
            mode: The field mode (CREATE or UPDATE).
            field_id: Field identifier (e.g., 'customfield_10745').
            title: Display title for the field.
            required: Whether the field is required.
            original_value: Original value from Jira - can be ADF dict, string, or None.
            field_supports_update: Whether field can be updated (ignored - always read-only).
        """

        markdown_text = self._convert_to_markdown(original_value)

        super().__init__(
            markdown=markdown_text,
            id=field_id,
        )

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title or 'Text Area',
            required=required,
            compact=True,
        )

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
            if value is None:
                return '_No content_'
            if isinstance(value, str):
                return value if value.strip() else '_No content_'
            markdown = convert_adf_to_markdown(value, base_url=None)
            return markdown if markdown.strip() else '_No content_'
        except Exception as e:
            logger.warning(f'Failed to convert ADF to markdown: {e}')
            return str(value) if value else '_No content_'
