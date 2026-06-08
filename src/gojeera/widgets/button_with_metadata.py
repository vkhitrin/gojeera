from typing import Any

from textual.widgets import Button


class ButtonWithMetadata(Button):
    """Button that renders optional metadata inside the button label."""

    DEFAULT_CSS = """
    ButtonWithMetadata {
        width: auto;
        min-width: 3;
    }

    """

    def __init__(
        self,
        *,
        icon: str,
        metadata: str = '',
        compact: bool = True,
        **kwargs: Any,
    ) -> None:
        self._icon = icon
        self._metadata_text = metadata
        classes = kwargs.pop('classes', '')
        kwargs['classes'] = f'action-button-chrome {classes}'.strip()
        super().__init__(
            self._label_for_metadata(metadata),
            compact=compact,
            **kwargs,
        )

    @property
    def metadata(self) -> str:
        return self._metadata_text

    @metadata.setter
    def metadata(self, value: str) -> None:
        old_label = self.label
        self._metadata_text = value
        self.label = self._label_for_metadata(value)
        if self.label != old_label:
            self.refresh(layout=True)

    def _label_for_metadata(self, metadata: str) -> str:
        return f'{self._icon} {metadata}' if metadata else self._icon
