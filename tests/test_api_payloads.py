from gojeera.api.api import JiraAPI


def test_build_payload_to_add_comment_uses_normal_text_conversion():
    payload = JiraAPI._build_payload_to_add_comment('hello')

    assert payload == {
        'body': {
            'type': 'doc',
            'version': 1,
            'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'hello'}]}],
        }
    }
