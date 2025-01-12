# © Copyright Databand.ai, an IBM Company 2022

from __future__ import print_function

import os

import pytest

from mock import MagicMock
from pytest import fixture

from dbnd._core.configuration.environ_config import (
    ENV_DBND__NO_PLUGINS,
    reset_dbnd_project_config,
)
from dbnd._core.utils.basics.environ_utils import set_on
from dbnd.testing.test_config_setter import add_test_configuration

from .mock_airflow_adapter import MockAirflowAdapter
from .mock_airflow_data_fetcher import MockDataFetcher
from .mock_airflow_tracking_service import (
    MockIntegrationManagementService,
    MockTrackingService,
)
from .mock_service_factory import MockAirflowServicesFactory


home = os.path.abspath(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "home"))
)
os.environ["DBND_HOME"] = home
os.environ["AIRFLOW_HOME"] = home
os.environ["AIRFLOW__CORE__UNIT_TEST_MODE"] = "True"
os.environ[
    "DBND__WEBSERVER__FERNET_KEY"
] = "-m4wWvVz9cGJPjFSRW1sI9zhTYUwnobQoJZjzXgBsWA="  # pragma: allowlist secret
reset_dbnd_project_config()

# we don't need to load dbnd plugins/modules
set_on(ENV_DBND__NO_PLUGINS)


def pytest_configure(config):
    add_test_configuration(__file__)


@fixture
def unittests_db():
    return "fetch-unittests.db"


@fixture
def empty_db():
    return "empty-unittests.db"


@fixture
def incomplete_data_db():
    return "incomplete-unittests.db"


@pytest.fixture()
def mock_airflow_services_factory() -> MockAirflowServicesFactory:
    yield MockAirflowServicesFactory()


@pytest.fixture
def mock_tracking_service(mock_airflow_services_factory) -> MockTrackingService:
    yield mock_airflow_services_factory.get_tracking_service(MagicMock())


@pytest.fixture
def mock_data_fetcher(mock_airflow_services_factory) -> MockDataFetcher:
    yield mock_airflow_services_factory.get_data_fetcher(MagicMock())


@pytest.fixture
def mock_airflow_adapter(mock_airflow_services_factory) -> MockAirflowAdapter:
    yield mock_airflow_services_factory.get_adapter(MagicMock())


@pytest.fixture
def mock_integration_management_service(
    mock_airflow_services_factory,
) -> MockIntegrationManagementService:
    yield mock_airflow_services_factory.get_integration_management_service()
