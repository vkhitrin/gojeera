from unittest.mock import AsyncMock, Mock, patch

import pytest
from textual.widgets import Button

from jiratui.api_controller.controller import APIController, APIControllerResponse
from jiratui.widgets.create_work_item.screen import AddWorkItemScreen


@pytest.fixture
def mock_api_controller():
    """Create a mock API controller for testing."""
    controller = Mock(spec=APIController)
    controller.search_projects = AsyncMock(
        return_value=APIControllerResponse(success=True, result=[])
    )
    controller.get_issue_types_for_project = AsyncMock(
        return_value=APIControllerResponse(success=True, result=[])
    )
    controller.search_users_assignable_to_projects = AsyncMock(
        return_value=APIControllerResponse(success=True, result=[])
    )
    return controller


@pytest.fixture
def create_metadata_with_editable_reporter():
    """Create metadata response where reporter field is editable."""
    return {
        'fields': [
            {
                'fieldId': 'reporter',
                'name': 'Reporter',
                'required': False,
                'operations': ['set'],  # 'set' operation means field is editable
                'schema': {
                    'type': 'user',
                    'system': 'reporter',
                },
            },
            {
                'fieldId': 'description',
                'name': 'Description',
                'required': False,
                'operations': ['set'],
            },
        ]
    }


@pytest.fixture
def create_metadata_without_editable_reporter():
    """Create metadata response where reporter field is NOT editable."""
    return {
        'fields': [
            {
                'fieldId': 'reporter',
                'name': 'Reporter',
                'required': False,
                'operations': [],  # No 'set' operation means field is NOT editable
                'schema': {
                    'type': 'user',
                    'system': 'reporter',
                },
            },
            {
                'fieldId': 'description',
                'name': 'Description',
                'required': False,
                'operations': ['set'],
            },
        ]
    }


@pytest.mark.asyncio
async def test_reporter_field_hidden_when_not_editable(
    mock_api_controller, create_metadata_without_editable_reporter
):
    """Test that reporter field is hidden when API metadata indicates it's not editable."""
    with patch('jiratui.widgets.create_work_item.screen.cast') as mock_cast:
        # Setup
        mock_app = Mock()
        mock_app.api = mock_api_controller
        mock_cast.return_value = mock_app

        screen = AddWorkItemScreen(project_key='TEST', reporter_account_id='user123')

        # Simulate mounting the screen
        async with screen.app.run_test() if hasattr(screen, 'app') else None:
            # Mock the API response for create metadata
            mock_api_controller.get_issue_create_metadata = AsyncMock(
                return_value=APIControllerResponse(
                    success=True, result=create_metadata_without_editable_reporter
                )
            )

            # Trigger metadata fetch
            await screen.fetch_issue_create_metadata('TEST', 'task-123')

            # Assertions
            assert screen._reporter_is_editable is False, 'Reporter should not be editable'
            assert screen.reporter_selector.display is False, 'Reporter field should be hidden'


@pytest.mark.asyncio
async def test_reporter_field_shown_when_editable(
    mock_api_controller, create_metadata_with_editable_reporter
):
    """Test that reporter field is shown when API metadata indicates it's editable."""
    with patch('jiratui.widgets.create_work_item.screen.cast') as mock_cast:
        # Setup
        mock_app = Mock()
        mock_app.api = mock_api_controller
        mock_cast.return_value = mock_app

        screen = AddWorkItemScreen(project_key='TEST', reporter_account_id='user123')

        # Mock the API response for create metadata
        mock_api_controller.get_issue_create_metadata = AsyncMock(
            return_value=APIControllerResponse(
                success=True, result=create_metadata_with_editable_reporter
            )
        )

        # Trigger metadata fetch
        await screen.fetch_issue_create_metadata('TEST', 'task-123')

        # Assertions
        assert screen._reporter_is_editable is True, 'Reporter should be editable'
        assert screen.reporter_selector.display is True, 'Reporter field should be shown'


@pytest.mark.asyncio
async def test_validation_skips_reporter_when_not_editable(
    mock_api_controller, create_metadata_without_editable_reporter
):
    """Test that validation does not require reporter field when it's not editable."""
    with patch('jiratui.widgets.create_work_item.screen.cast') as mock_cast:
        # Setup
        mock_app = Mock()
        mock_app.api = mock_api_controller
        mock_cast.return_value = mock_app

        screen = AddWorkItemScreen(project_key='TEST')

        # Mock the API response for create metadata
        mock_api_controller.get_issue_create_metadata = AsyncMock(
            return_value=APIControllerResponse(
                success=True, result=create_metadata_without_editable_reporter
            )
        )

        # Trigger metadata fetch
        await screen.fetch_issue_create_metadata('TEST', 'task-123')

        # Set required fields (but not reporter)
        screen.project_selector.selection = 'TEST'
        screen.issue_type_selector.selection = 'task-123'
        screen.summary_field.value = 'Test Summary'
        screen.reporter_selector.selection = None  # No reporter selected

        # Validation should pass even without reporter
        assert screen._validate_required_fields() is True, (
            "Validation should pass without reporter when it's not editable"
        )


@pytest.mark.asyncio
async def test_save_excludes_reporter_when_not_editable(
    mock_api_controller, create_metadata_without_editable_reporter
):
    """Test that save handler does not include reporter field when it's not editable."""
    with patch('jiratui.widgets.create_work_item.screen.cast') as mock_cast:
        # Setup
        mock_app = Mock()
        mock_app.api = mock_api_controller
        mock_cast.return_value = mock_app

        screen = AddWorkItemScreen(project_key='TEST')
        screen.dismiss = Mock()

        # Mock the API response for create metadata
        mock_api_controller.get_issue_create_metadata = AsyncMock(
            return_value=APIControllerResponse(
                success=True, result=create_metadata_without_editable_reporter
            )
        )

        # Trigger metadata fetch
        await screen.fetch_issue_create_metadata('TEST', 'task-123')

        # Set required fields
        screen.project_selector.selection = 'TEST'
        screen.issue_type_selector.selection = 'task-123'
        screen.summary_field.value = 'Test Summary'
        screen.assignee_selector.selection = 'assignee123'
        screen.reporter_selector.selection = 'reporter123'  # Set but should be ignored
        screen.parent_key_field.value = None
        screen.description_field.text = 'Test Description'

        # Trigger save
        screen.handle_save()

        # Get the data passed to dismiss
        dismiss_args = screen.dismiss.call_args[0][0]

        # Assertions
        assert 'reporter_account_id' not in dismiss_args, (
            'Reporter should not be included in save data when not editable'
        )
        assert dismiss_args['project_key'] == 'TEST'
        assert dismiss_args['summary'] == 'Test Summary'


@pytest.mark.asyncio
async def test_save_includes_reporter_when_editable(
    mock_api_controller, create_metadata_with_editable_reporter
):
    """Test that save handler includes reporter field when it's editable."""
    with patch('jiratui.widgets.create_work_item.screen.cast') as mock_cast:
        # Setup
        mock_app = Mock()
        mock_app.api = mock_api_controller
        mock_cast.return_value = mock_app

        screen = AddWorkItemScreen(project_key='TEST', reporter_account_id='reporter123')
        screen.dismiss = Mock()

        # Mock the API response for create metadata
        mock_api_controller.get_issue_create_metadata = AsyncMock(
            return_value=APIControllerResponse(
                success=True, result=create_metadata_with_editable_reporter
            )
        )

        # Trigger metadata fetch
        await screen.fetch_issue_create_metadata('TEST', 'task-123')

        # Set required fields
        screen.project_selector.selection = 'TEST'
        screen.issue_type_selector.selection = 'task-123'
        screen.summary_field.value = 'Test Summary'
        screen.assignee_selector.selection = 'assignee123'
        screen.reporter_selector.selection = 'reporter123'
        screen.parent_key_field.value = None
        screen.description_field.text = 'Test Description'

        # Trigger save
        screen.handle_save()

        # Get the data passed to dismiss
        dismiss_args = screen.dismiss.call_args[0][0]

        # Assertions
        assert 'reporter_account_id' in dismiss_args, (
            'Reporter should be included in save data when editable'
        )
        assert dismiss_args['reporter_account_id'] == 'reporter123'
        assert dismiss_args['project_key'] == 'TEST'
        assert dismiss_args['summary'] == 'Test Summary'
