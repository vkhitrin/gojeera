from datetime import date

from gojeera.utils.jira.jql import (
    build_work_item_search_jql,
    quote_jql_string,
    text_search_jql,
    work_item_flagged_jql,
)


def test_quote_jql_string_escapes_quotes_and_backslashes() -> None:
    assert quote_jql_string('a "quoted" \\ value') == '"a \\"quoted\\" \\\\ value"'


def test_text_search_jql_quotes_user_text() -> None:
    assert text_search_jql('broken "phrase"') == 'textfields ~ "broken \\"phrase\\""'


def test_work_item_flagged_jql_uses_native_flagged_field_name() -> None:
    assert (
        work_item_flagged_jql('ENG-25346')
        == 'key = "ENG-25346" AND "Flagged[Checkboxes]" = Impediment'
    )


def test_build_work_item_search_jql_preserves_existing_order_by_behavior() -> None:
    assert (
        build_work_item_search_jql(
            project_key='ENG',
            created_from=date(2026, 6, 1),
            jql_query='ORDER BY updated DESC',
        )
        == 'project = "ENG" and created >= "2026-06-01" ORDER BY updated DESC'
    )
