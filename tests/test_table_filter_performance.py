from rich.style import Style
from textual.app import App, ComposeResult

from gojeera.widgets.layout.extended_table import ExtendedTable


class TableApp(App[None]):
    def compose(self) -> ComposeResult:
        yield ExtendedTable()


async def test_replace_rows_rebuilds_rows_and_styles_in_one_operation() -> None:
    app = TableApp()

    async with app.run_test() as pilot:
        table = pilot.app.query_one(ExtendedTable)
        table.add_columns('Name', 'Status')

        table.replace_rows(
            [('First', 'Overdue'), ('Second', 'Current')],
            row_styles=[Style(color='red'), None],
        )

        assert table.row_count == 2
        assert len(table._row_styles) == 1

        table.replace_rows([('Replacement', 'Current')])

        assert table.row_count == 1
        assert table.get_row_at(0) == ['Replacement', 'Current']
        assert table._row_styles == {}


async def test_append_rows_preserves_existing_rows_and_styles() -> None:
    app = TableApp()

    async with app.run_test() as pilot:
        table = pilot.app.query_one(ExtendedTable)
        table.add_columns('Name', 'Status')
        table.replace_rows([('First', 'Current')])

        table.append_rows(
            [('Second', 'Overdue')],
            row_styles=[Style(color='red')],
        )

        assert table.row_count == 2
        assert table.get_row_at(0) == ['First', 'Current']
        assert table.get_row_at(1) == ['Second', 'Overdue']
        assert len(table._row_styles) == 1
