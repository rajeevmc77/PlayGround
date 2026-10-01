"""JiraClient wraps the three calls in JIRA.postman_collection.json (list
projects, assignable users of a project, create issue) over basic auth with an
API token; these tests answer them with an httpx.MockTransport."""

import base64
import json

import httpx
import pytest

from jira_backlog.jira.client import JiraClient, JiraError, open_client


def _client(handler):
    http = httpx.Client(base_url="https://x.atlassian.net", transport=httpx.MockTransport(handler))
    return JiraClient(http)


def test_projects_gets_the_project_list():
    def handler(request):
        assert (request.method, request.url.path) == ("GET", "/rest/api/3/project/")
        return httpx.Response(200, json=[{"key": "AUBM", "name": "AOT Pulse"}])

    assert _client(handler).projects() == [{"key": "AUBM", "name": "AOT Pulse"}]


def test_assignable_users_queries_by_project():
    def handler(request):
        assert request.url.path == "/rest/api/3/user/assignable/search"
        assert request.url.params["project"] == "AUBM"
        return httpx.Response(200, json=[{"accountId": "1", "displayName": "R"}])

    assert _client(handler).assignable_users("AUBM") == [{"accountId": "1", "displayName": "R"}]


def test_create_issue_posts_the_fields_and_returns_the_new_key():
    def handler(request):
        assert (request.method, request.url.path) == ("POST", "/rest/api/3/issue")
        assert json.loads(request.content) == {"fields": {"summary": "S"}}
        return httpx.Response(201, json={"id": "10001", "key": "AUBM-12"})

    assert _client(handler).create_issue({"summary": "S"}) == "AUBM-12"


def test_a_rejected_request_raises_with_jira_s_error_messages():
    def handler(request):
        body = {"errorMessages": ["Bad"], "errors": {"priority": "Priority is not valid"}}
        return httpx.Response(400, json=body)

    with pytest.raises(JiraError, match="400.*Bad.*priority: Priority is not valid"):
        _client(handler).create_issue({})


def test_a_rejected_request_with_a_non_json_body_raises_with_its_text():
    with pytest.raises(JiraError, match="401.*Unauthorized"):
        _client(lambda request: httpx.Response(401, text="Unauthorized")).projects()


def test_open_client_sends_basic_auth_and_json_accept_headers():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json=[])

    with open_client(
        "https://x.atlassian.net", "me@x.com", "tok", httpx.MockTransport(handler)
    ) as c:
        c.projects()

    assert seen["authorization"] == "Basic " + base64.b64encode(b"me@x.com:tok").decode()
    assert seen["accept"] == "application/json"
