from textual.widgets import Input


class ReadOnlyInputField(Input):
    """A read-only input field widget that is always disabled."""

    def __init__(self, **kwargs):
        classes = kwargs.pop('classes', '')

        if 'compact' not in kwargs:
            kwargs['compact'] = True
        super().__init__(**kwargs)
        self.disabled = True
        if classes:
            self.add_class(*classes.split(','))
