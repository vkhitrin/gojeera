from gojeera.utils.data.fields import FieldMode
from gojeera.utils.ui.widgets_factory_utils import (
    DynamicFieldWrapper,
    FieldMetadata,
    map_field_to_widget,
)
from gojeera.widgets.selection.multi_select import MultiSelect


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
