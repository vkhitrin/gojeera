import asyncio
import threading
from typing import Any, cast

from gojeera.utils.data.fields import FieldMode
from gojeera.utils.ui.widgets_factory_utils import (
    DynamicFieldWrapper,
    FieldMetadata,
    map_field_to_widget,
)
from gojeera.widgets.selection.multi_select import MultiSelect

ADF_FIELD_METADATA = {
    'fieldId': 'customfield_10001',
    'key': 'customfield_10001',
    'name': 'Architecture Notes',
    'required': False,
    'operations': [],
    'schema': {'type': 'string'},
}
VISIBLE_ADF_VALUE = {
    'type': 'doc',
    'version': 1,
    'content': [
        {
            'type': 'paragraph',
            'content': [{'type': 'text', 'text': 'Keep every field visible'}],
        }
    ],
}


def test_service_desk_customer_organizations_field_maps_to_multiselect():
    widget = map_field_to_widget(
        FieldMode.UPDATE,
        FieldMetadata(
            {
                'fieldId': 'customfield_10727',
                'key': 'customfield_10727',
                'name': 'Organizations',
                'required': False,
                'operations': ['set'],
                'schema': {
                    'type': 'array',
                    'items': 'option',
                    'custom': 'com.atlassian.servicedesk:sd-customer-organizations',
                    'customId': 10727,
                },
                'allowedValues': [
                    {'id': '10727', 'value': 'Engineering'},
                    {'id': '10728', 'value': 'Support'},
                ],
            }
        ),
        current_value=[{'id': '10728', 'value': 'Support'}],
    )

    assert isinstance(widget, DynamicFieldWrapper)
    widget.materialize()
    assert isinstance(widget.widget, MultiSelect)


def test_adf_field_materializes_after_deferred_widget_import():
    widget = map_field_to_widget(
        FieldMode.UPDATE,
        FieldMetadata(ADF_FIELD_METADATA),
        current_value=VISIBLE_ADF_VALUE,
    )

    assert isinstance(widget, DynamicFieldWrapper)
    assert widget.widget is None

    widget.materialize()

    assert widget.widget is not None
    assert widget.widget.__class__.__name__ == 'ADFTextAreaWidget'
    assert 'Keep every field visible' in cast(Any, widget.widget).convert_value_to_markdown(
        VISIBLE_ADF_VALUE
    )


async def test_adf_field_conversion_finishes_in_worker_before_materialization(monkeypatch):
    from gojeera.widgets.markdown.adf_textarea import ADFTextAreaWidget

    conversion_threads = []
    original_convert = ADFTextAreaWidget.convert_value_to_markdown

    def record_conversion(value):
        conversion_threads.append(threading.get_ident())
        return original_convert(value)

    monkeypatch.setattr(
        ADFTextAreaWidget,
        'convert_value_to_markdown',
        staticmethod(record_conversion),
    )
    main_thread = threading.get_ident()
    metadata = FieldMetadata(ADF_FIELD_METADATA)
    value = {
        'type': 'doc',
        'version': 1,
        'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'Notes'}]}],
    }

    widget = await asyncio.to_thread(map_field_to_widget, FieldMode.UPDATE, metadata, value)

    assert isinstance(widget, DynamicFieldWrapper)
    assert conversion_threads and conversion_threads[0] != main_thread

    widget.materialize()

    assert len(conversion_threads) == 1
