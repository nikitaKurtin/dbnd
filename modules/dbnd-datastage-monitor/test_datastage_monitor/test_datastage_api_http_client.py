# © Copyright Databand.ai, an IBM Company 2022
import logging

from http import HTTPStatus
from unittest import mock
from unittest.mock import MagicMock

import pytest

from dbnd_datastage_monitor.datastage_client.datastage_api_client import (
    CLOUD_IAM_AUTH,
    ON_PREM_BASIC_AUTH,
    DataStageApiHttpClient,
)


@pytest.mark.parametrize(
    "host_name, called_host, auth_type",
    [
        [None, DataStageApiHttpClient.DEFAULT_HOST, CLOUD_IAM_AUTH],
        ["https://myhost.com", "https://myhost.com", ON_PREM_BASIC_AUTH],
    ],
)
@mock.patch("requests.session")
def test_get_runs_ids(mock_session, host_name, called_host, auth_type):
    session_mock = mock_session.return_value
    mock_cams_query_response = session_mock.request.return_value
    mock_cams_query_response.status_code = HTTPStatus.OK
    mock_cams_query_response.json.return_value = {
        "results": [
            {"metadata": {"asset_id": "01234"}, "href": "https://myrun.com/01234"},
            {"metadata": {"asset_id": "56789"}, "href": "https://myrun.com/56789"},
        ]
    }

    client = DataStageApiHttpClient(
        host_name=host_name,
        project_id="123",
        authentication_type=auth_type,
        api_key="abc",
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    response = client.get_runs_ids("", "")

    assert response == (
        {
            "01234": f"{called_host}/v2/assets/01234?project_id=123",
            "56789": f"{called_host}/v2/assets/56789?project_id=123",
        },
        None,
    )


@mock.patch("requests.session")
def test_get_run_info(mock_session):
    session_mock = mock_session.return_value
    mock_get_run_response = session_mock.request.return_value
    mock_get_run_response.status_code = HTTPStatus.OK
    mock_get_run_response.json.return_value = {"run_mock": "data"}
    client = DataStageApiHttpClient("", "")
    client.get_session = MagicMock(return_value=session_mock)
    response = client.get_run_info("https://myrun.com/01234")

    assert response == {"run_mock": "data"}


@mock.patch("requests.session")
def test_error_response_get(mock_session):
    session_mock = mock_session.return_value
    mock_get_response = session_mock.request.return_value
    mock_get_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    client = DataStageApiHttpClient("", "")
    client.get_session = MagicMock(return_value=session_mock)
    client._make_http_request(method="GET", url="")
    mock_get_response.raise_for_status.assert_called()


@mock.patch("requests.session")
def test_error_response_post(mock_session):
    session_mock = mock_session.return_value
    mock_post_response = session_mock.request.return_value
    mock_post_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    client = DataStageApiHttpClient("", "")
    client.get_session = MagicMock(return_value=session_mock)
    client._make_http_request(method="POST", url="", body={"a": "b"})
    mock_post_response.raise_for_status.assert_called()


@mock.patch("requests.session")
def test_token_refresh_get(mock_session):
    session_mock = mock_session.return_value
    mock_get_response = session_mock.request.return_value
    mock_get_response.status_code = HTTPStatus.UNAUTHORIZED
    session_mock.post.return_value.json.return_value = {"access_token": "token"}
    client = DataStageApiHttpClient("", "", authentication_type="cloud-iam-auth")
    client.get_session = MagicMock(return_value=session_mock)
    client._make_http_request(method="GET", url="")
    mock_get_response.raise_for_status.assert_called()
    data = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={client.api_key}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    # call refresh token
    session_mock.post.assert_called_with(
        "https://iam.cloud.ibm.com/identity/token", data=data, headers=headers
    )
    # retry on get with new token
    session_mock.request.assert_called_with(
        method="GET",
        url="",
        headers={
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "Bearer token",
        },
        json=None,
        verify=False,
    )


@mock.patch("requests.session")
def test_token_refresh_post(mock_session):
    session_mock = mock_session.return_value
    mock_post_response = session_mock.request.return_value
    mock_post_response.status_code = HTTPStatus.UNAUTHORIZED
    session_mock.post.return_value.json.return_value = {"access_token": "token"}
    client = DataStageApiHttpClient("", "", authentication_type="cloud-iam-auth")
    client.get_session = MagicMock(return_value=session_mock)
    client._make_http_request(method="POST", url="", body={"a": "b"})
    mock_post_response.raise_for_status.assert_called()
    data = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={client.api_key}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    # call refresh token
    session_mock.post.assert_called_with(
        f"{client.DEFAULT_AUTHENTICATION_URL}/{client.IDENTITY_TOKEN_API_PATH}",
        data=data,
        headers=headers,
    )
    # retry on post with new token
    session_mock.request.assert_called_with(
        method="POST",
        url="",
        json={"a": "b"},
        headers={
            "accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": "Bearer token",
        },
        verify=False,
    )


@mock.patch("requests.session")
@pytest.mark.parametrize(
    "host_name, called_host, auth_type",
    [
        [None, DataStageApiHttpClient.DEFAULT_HOST, CLOUD_IAM_AUTH],
        ["https://myhost.com", "https://myhost.com", ON_PREM_BASIC_AUTH],
        ["https://myhost.com", "https://myhost.com", "on-prem-iam-auth"],
        ["https://myhost.com/", "https://myhost.com", "on-prem-iam-auth"],
    ],
)
def test_get_job(mock_session, host_name, called_host, auth_type):
    session_mock = mock_session.return_value
    mock_get_job_response = session_mock.request.return_value
    mock_get_job_response.json.return_value = {"job_info": "data", "href": "link"}
    mock_get_job_response.status_code = HTTPStatus.OK

    project_id = "project"
    client = DataStageApiHttpClient(
        host_name=host_name,
        project_id=project_id,
        authentication_type=auth_type,
        api_key="abc",
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    job_id = "job"
    client.get_job(job_id)
    session_mock.request.assert_any_call(
        method="GET",
        url=f"{called_host}/{client.DATASTAGE_CAMS_API_ASSETS_PATH}/{job_id}?project_id={project_id}",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json=None,
        verify=False,
    )


@mock.patch("requests.session")
@pytest.mark.parametrize(
    "host_name, called_host, auth_type",
    [
        [None, DataStageApiHttpClient.DEFAULT_API_HOST, "cloud-iam-auth"],
        ["https://myhost.com", "https://myhost.com", "on-prem-iam-auth"],
        ["https://myhost.com/", "https://myhost.com", "on-prem-iam-auth"],
    ],
)
def test_get_flow(mock_session, host_name, called_host, auth_type):
    session_mock = mock_session.return_value
    mock_get_flow_response = session_mock.request.return_value
    mock_get_flow_response.json.return_value = {"flow": "data"}
    mock_get_flow_response.status_code = HTTPStatus.OK
    project_id = "project"
    client = DataStageApiHttpClient(
        "", project_id=project_id, host_name=host_name, authentication_type=auth_type
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    flow_id = "flow"
    response = client.get_flow(flow_id)
    session_mock.request.assert_called_with(
        method="GET",
        url=f"{called_host}/{client.FLOW_API_PATH}/{flow_id}/?project_id={project_id}",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json=None,
        verify=False,
    )
    assert response == {"flow": "data"}


@mock.patch("requests.session")
@pytest.mark.parametrize(
    "host_name, called_host, auth_type",
    [
        [None, DataStageApiHttpClient.DEFAULT_HOST, "cloud-iam-auth"],
        ["https://myhost.com", "https://myhost.com", "on-prem-iam-auth"],
        ["https://myhost.com/", "https://myhost.com", "on-prem-iam-auth"],
    ],
)
def test_get_run_logs(mock_session, host_name, called_host, auth_type):
    session_mock = mock_session.return_value
    mock_get_logs_response = session_mock.request.return_value
    mock_get_logs_response.json.return_value = {
        "results": ['[{"eventID": "0", "occurredAt": 1664719211000}]']
    }
    mock_get_logs_response.status_code = HTTPStatus.OK
    project_id = "project"
    client = DataStageApiHttpClient(
        "", project_id=project_id, host_name=host_name, authentication_type=auth_type
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    job_id = "job"
    run_id = "run"
    response = client.get_run_logs(job_id, run_id)
    session_mock.request.assert_called_with(
        method="GET",
        url=f"{called_host}/{client.DATASTAGE_JOBS_API_PATH}/{job_id}/runs/{run_id}/logs?project_id={project_id}&limit=200&userfs=false",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json=None,
        verify=False,
    )
    assert response == [{"eventID": "0", "occurredAt": 1664719211000}]


@mock.patch("requests.session")
def test_get_run_logs_fails(mock_session, caplog):
    host_name = "http://www.host.com"
    session_mock = mock_session.return_value
    mock_get_logs_response = session_mock.request.return_value
    mock_get_logs_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    mock_get_logs_response.raise_for_status.side_effect = Exception(
        "Internal server error"
    )
    project_id = "project"
    client = DataStageApiHttpClient(
        "",
        project_id=project_id,
        host_name=host_name,
        authentication_type="on-prem-iam-auth",
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    job_id = "job"
    run_id = "run"

    with caplog.at_level(logging.INFO):
        response = client.get_run_logs(job_id, run_id)
        session_mock.request.assert_called_with(
            method="GET",
            url=f"{host_name}/{client.DATASTAGE_JOBS_API_PATH}/{job_id}/runs/{run_id}/logs?project_id={project_id}&limit=200&userfs=false",
            headers={"accept": "application/json", "Content-Type": "application/json"},
            json=None,
            verify=False,
        )
        mock_get_logs_response.raise_for_status.assert_called()
        expected_log_message = "Error occurred during fetching DataStage logs for run id: run, Exception: Internal server error"
        assert response == []
        assert expected_log_message in caplog.messages


@mock.patch("requests.session")
@pytest.mark.parametrize(
    "host_name, called_host, auth_type",
    [
        [None, DataStageApiHttpClient.DEFAULT_HOST, "cloud-iam-auth"],
        ["https://myhost.com", "https://myhost.com", "on-prem-basic-auth"],
    ],
)
def test_get_connections_filter_senstive_data(
    mock_session, host_name, called_host, auth_type
):
    session_mock = mock_session.return_value
    mock_get_connections_response = session_mock.request.return_value
    mock_get_connections_response.json.return_value = {
        "resources": [
            {
                "metadata": {"asset_id": 123},
                "entity": {
                    "properties": {
                        "username": "user",
                        "password": "123",
                        "name": "datasource",
                    }
                },
            }
        ]
    }
    mock_get_connections_response.status_code = HTTPStatus.OK
    project_id = "project"
    client = DataStageApiHttpClient(
        "", project_id=project_id, host_name=host_name, authentication_type=auth_type
    )
    client.get_session = MagicMock(return_value=session_mock)
    client.refresh_access_token = MagicMock()
    response = client.get_connections()
    session_mock.request.assert_called_with(
        method="GET",
        url=f"{called_host}/{client.DATASTAGE_CONNECTIONS_API_PATH}?project_id={project_id}&userfs=false",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json=None,
        verify=False,
    )
    assert response == {
        123: {
            "entity": {"properties": {"name": "datasource"}},
            "metadata": {"asset_id": 123},
        }
    }