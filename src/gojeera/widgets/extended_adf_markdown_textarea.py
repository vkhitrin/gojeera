import logging
import re

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Label, TabPane, TextArea
from textual.widgets._tabbed_content import ContentTab

from gojeera.utils.adf_helpers import text_to_adf
from gojeera.utils.fields import (
    BaseField,
    FieldMode,
)
from gojeera.widgets.extended_jumper import set_jump_mode
from gojeera.widgets.extended_tabbed_content import ExtendedTabbedContent
from gojeera.widgets.extended_textarea import ExtendedTextArea
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown

logger = logging.getLogger('gojeera')


class ExtendedADFMarkdownTextArea(Vertical, BaseField):
    """
    ExtendedADFMarkdownTextArea widget with tabbed interface for edit and preview modes.
    """

    DEFAULT_CSS = """
    ExtendedADFMarkdownTextArea {
        height: 12;
        min-height: 12;
        max-height: 12;
        padding: 0;
        margin-bottom: 0;
        background: $surface-lighten-1;
    }

    ExtendedADFMarkdownTextArea TabbedContent {
        height: 12;
        min-height: 12;
        max-height: 12;
        background: $surface-lighten-1;
    }

    ExtendedADFMarkdownTextArea TabPane {
        padding: 0;
        height: 12;
    }

    ExtendedADFMarkdownTextArea TextArea {
        height: 10;
        min-height: 10;
        max-height: 10;
        padding: 0;
        background: $surface-lighten-1;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }

    ExtendedADFMarkdownTextArea VerticalScroll {
        height: 10;
        min-height: 10;
        max-height: 10;
        background: $surface-lighten-1;
        scrollbar-size-vertical: 1;
    }

    ExtendedADFMarkdownTextArea GojeeraMarkdown {
        height: auto;
        padding: 0;
        margin: 0;
    }

    ExtendedADFMarkdownTextArea .adf-warning {
        background: $warning-darken-1;
        color: $text;
        padding: 1;
        margin-top: 1;
    }

    """

    def __init__(
        self,
        field_id: str = 'description',
        required: bool = False,
        mode: FieldMode = FieldMode.CREATE,
    ):
        super().__init__(id=field_id)

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title='ExtendedADFMarkdownTextArea',
            required=required,
            compact=True,
        )

        self._required = required
        self._text = ''
        self._adf_warnings: list[str] = []

    def compose(self) -> ComposeResult:
        with ExtendedTabbedContent(id=f'{self.id}-tabs'):
            with TabPane('Edit', id=f'{self.id}-edit-tab'):
                textarea = ExtendedTextArea(
                    id=f'{self.id}-textarea',
                    language='markdown',
                    compact=True,
                )
                textarea.text = ''
                yield textarea

            with TabPane('Preview', id=f'{self.id}-preview-tab'):
                with VerticalScroll(id=f'{self.id}-preview-scroll'):
                    yield GojeeraMarkdown('_No content to preview_', id=f'{self.id}-markdown')

        yield Label('', id=f'{self.id}-warnings', classes='adf-warning')

    @property
    def textarea(self) -> TextArea:
        return self.query_one(f'#{self.id}-textarea', TextArea)

    @property
    def tabbed_content(self) -> ExtendedTabbedContent:
        return self.query_one(f'#{self.id}-tabs', ExtendedTabbedContent)

    @property
    def markdown_preview(self) -> GojeeraMarkdown:
        return self.query_one(f'#{self.id}-markdown', GojeeraMarkdown)

    @property
    def warning_label(self) -> Label:
        return self.query_one(f'#{self.id}-warnings', Label)

    @property
    def text(self) -> str:
        try:
            text_value = self.textarea.text if hasattr(self.textarea, 'text') else self._text
            return text_value
        except Exception:
            return self._text

    @text.setter
    def text(self, value: str) -> None:
        self._text = value
        try:
            self.textarea.text = value
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    @property
    def required(self) -> bool:
        return self._required

    def mark_required(self) -> None:
        self._required = True

    @on(TextArea.Changed)
    def handle_textarea_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == f'{self.id}-textarea':
            self._text = event.text_area.text

            if self._text.strip():
                self._check_adf_warnings(self._text)
            else:
                self._adf_warnings = []

            self._update_warning_display()

            self._update_tab_label()

    @on(ExtendedTabbedContent.TabActivated)
    def handle_tab_activated(self, event: ExtendedTabbedContent.TabActivated) -> None:
        if event.pane.id == f'{self.id}-preview-tab':
            try:
                current_text = self.textarea.text if hasattr(self.textarea, 'text') else ''
                if current_text.strip():
                    preview_text = self._render_task_checkboxes(current_text)
                    self.markdown_preview.update(preview_text)

                    self._check_adf_warnings(current_text)
                else:
                    self.markdown_preview.update('_No content to preview_')
                    self._adf_warnings = []

                self._update_warning_display()

                self._update_tab_label()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    def get_value_for_create(self) -> str | None:
        text = self.text.strip() if self.text else ''
        return text if text else None

    def set_original_value(self, value: str) -> None:
        pass

    def make_jumpable(self) -> None:
        try:
            content_tabs = list(self.tabbed_content.query(ContentTab))
            for content_tab in content_tabs:
                content_tab.can_focus = False
                set_jump_mode(content_tab, 'click')

            set_jump_mode(self.textarea, 'focus')
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def get_jumper_focus_target(self) -> TextArea | None:
        """Return the underlying textarea used for keyboard input."""

        try:
            return self.textarea
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')
            return None

    def insert_mention(self, account_id: str, display_name: str, base_url: str) -> None:
        """Insert a user mention at the current cursor position."""
        try:
            mention_text = f'[@{display_name}]({base_url}/jira/people/{account_id})'

            self.textarea.focus()
            self.textarea.insert(mention_text)
            self._text = self.textarea.text

        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def _render_task_checkboxes(self, text: str) -> str:
        """Replace GFM task list markers with UTF-8 checkbox characters for preview."""

        text = re.sub(r'([^\n\s-])(-\s+\[[ xX]\])', r'\1\n    \2', text)

        text = re.sub(r'([^\n\s-])(-\s+(?!\[))', r'\1\n    \2', text)

        lines = text.split('\n')
        fixed_lines = []
        in_nested_context = False
        previous_line = ''

        for line in lines:
            is_unindented_bullet = re.match(r'^-\s+', line)

            is_root_ordered = re.match(r'^\d+\.\s+', line)

            is_already_indented = line.startswith(' ')

            if is_unindented_bullet:
                if in_nested_context:
                    fixed_lines.append('    ' + line)
                    previous_line = line
                    continue
                elif re.match(r'^\d+\.\s+', previous_line):
                    in_nested_context = True
                    fixed_lines.append('    ' + line)
                    previous_line = line
                    continue
            elif is_root_ordered:
                in_nested_context = False
            elif not is_already_indented and line.strip() == '':
                pass
            elif not is_already_indented and line.strip() != '' and not is_unindented_bullet:
                in_nested_context = False

            fixed_lines.append(line)
            previous_line = line
        text = '\n'.join(fixed_lines)

        lines = text.split('\n')
        result_lines = []

        for i, line in enumerate(lines):
            match = re.match(r'^(\s*)-\s+\[([ xX])\](.*)$', line)
            if match:
                indent, checkbox_state, rest = match.groups()

                if checkbox_state == ' ':
                    result_lines.append(f'{indent}☐{rest}')
                else:
                    result_lines.append(f'{indent}☑{rest}')

                if i < len(lines) - 1:
                    result_lines.append('')
            else:
                result_lines.append(line)

        return '\n'.join(result_lines)

    def _check_adf_warnings(self, text: str) -> None:
        try:
            _, warnings = text_to_adf(text, track_warnings=True)
            self._adf_warnings = warnings
        except Exception:
            self._adf_warnings = []

    def _update_warning_display(self) -> None:
        try:
            if self._adf_warnings:
                warning_text = '⚠ ADF Conversion Warnings:\n' + '\n'.join(
                    f'  • {w}' for w in self._adf_warnings
                )
                self.warning_label.update(warning_text)
                self.warning_label.display = True
            else:
                self.warning_label.display = False
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def _update_tab_label(self) -> None:
        try:
            content_tabs = list(self.tabbed_content.query(ContentTab))

            for tab in content_tabs:
                label_str = (
                    str(tab._label)
                    if hasattr(tab, '_label')
                    else str(tab.label)
                    if hasattr(tab, 'label')
                    else ''
                )

                if 'Preview' in label_str:
                    if self._adf_warnings:
                        tab.update('Preview ⚠')
                    else:
                        tab.update('Preview')
                    break
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')
