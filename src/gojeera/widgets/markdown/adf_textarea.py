import logging

from gojeera.utils.data.fields import (
    BaseField,
)
from gojeera.utils.data.fields import (
    FieldMode as ADFFieldMode,
)
from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown
from gojeera.widgets.markdown.gojeera_markdown import GojeeraMarkdown

logger = logging.getLogger('gojeera')


class ADFTextAreaWidget(GojeeraMarkdown, BaseField):
    """
    Read-only GojeeraMarkdown widget that handles Atlassian Document Format (ADF) conversion.
    """

    def __init__(
        self,
        mode: ADFFieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: dict | str | None = None,
        field_supports_update: bool = True,
        preconverted_markdown: str | None = None,
    ):
        """
        Initialize an ADFTextAreaWidget.

        Args:
            mode: The field mode (CREATE or UPDATE).
            field_id: Field identifier (e.g., 'customfield_10745').
            title: Display title for the field.
            required: Whether the field is required.
            original_value: Original value from Jira - can be ADF dict, string, or None.
            field_supports_update: Accepted for API compatibility; ignored because this widget
                is always rendered read-only.
        """
        del field_supports_update

        markdown_text = (
            preconverted_markdown
            if preconverted_markdown is not None
            else self.convert_value_to_markdown(original_value)
        )

        super().__init__(
            markdown=markdown_text,
            id=field_id,
        )

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title or 'Text Area',
            required=required,
        )

        self.add_class('adf-textarea-readonly')

    @staticmethod
    def convert_value_to_markdown(value: dict | str | None) -> str:
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
        except Exception:
            logger.warning('Failed to convert ADF to markdown', exc_info=True)
            return str(value) if value else '_No content_'
