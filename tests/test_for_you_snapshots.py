"""For You visual coverage. Baselines must be generated and reviewed by the maintainer."""

import pytest

from .for_you_test_helpers import prepare_for_you_tab


class TestForYouSnapshots:
    @pytest.mark.parametrize('for_you_app', ['textual-dark', 'textual-light'], indirect=True)
    @pytest.mark.parametrize('section', ['due', 'updated', 'mentions'])
    @pytest.mark.parametrize(
        'mock_jira_api_for_you', ['populated', 'empty', 'loading'], indirect=True
    )
    def test_for_you_tab(
        self,
        snap_compare,
        for_you_app,
        mock_jira_api_for_you,
        section,
    ):

        async def run_before(pilot):
            await prepare_for_you_tab(pilot, section, mock_jira_api_for_you)

        assert snap_compare(for_you_app, terminal_size=(120, 40), run_before=run_before)
