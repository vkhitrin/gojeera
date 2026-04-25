from pathlib import Path

from gojeera.components.screens.base_attachment_path_screen import AttachmentPathModalScreen


class SaveAttachmentScreen(AttachmentPathModalScreen):
    """A modal screen to save an attachment to a file."""

    def __init__(self, attachment_file_name: str):
        default_path = Path.home() / attachment_file_name
        super().__init__(
            modal_title=f'Save Attachment - {attachment_file_name}',
            form_id='save-attachment-form',
            field_label='Save Location',
            input_placeholder='Click "Browse..." to select save location',
            browse_button_id='browse-save-location-button',
            browse_title='Select Save Location',
            browse_open_button='Save',
            save_button_id='save-attachment-button-save',
            save_button_label='Save',
            cancel_button_id='save-attachment-button-quit',
            hint_text='• Click "Browse..." to select where to save the file\n'
            '• You can edit the filename in the picker',
            initial_path=default_path,
            default_file_name=attachment_file_name,
            must_exist=False,
        )
