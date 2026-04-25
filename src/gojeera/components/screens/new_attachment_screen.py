from gojeera.components.screens.base_attachment_path_screen import AttachmentPathModalScreen


class AddAttachmentScreen(AttachmentPathModalScreen):
    """A modal screen to add an attachment to a work item."""

    def __init__(self, work_item_key: str | None = None):
        self._work_item_key = work_item_key
        super().__init__(
            modal_title=f'Add Attachment - {work_item_key}',
            form_id='add-attachment-form',
            field_label='File Path',
            input_placeholder='Click "Browse..." to select a file',
            browse_button_id='browse-file-button',
            browse_title='Select File to Attach',
            browse_open_button='Select',
            save_button_id='add-attachment-button-save',
            save_button_label='Attach',
            cancel_button_id='add-attachment-button-quit',
            hint_text='• Click "Browse..." to open the file picker\n'
            '• Navigate and select the file to attach',
            warning_text='⚠ Large files may cause temporary UI unresponsiveness!',
            initial_path=None,
            default_file_name=None,
            must_exist=True,
        )
