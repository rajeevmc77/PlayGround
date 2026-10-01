"""The JIRA Cloud REST v3 calls from JIRA.postman_collection.json, over basic
auth (account email + API token)."""

from contextlib import contextmanager

import httpx

_HEADERS = {"Accept": "application/json"}


class JiraError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, http: httpx.Client):
        self._http = http

    def projects(self) -> list[dict]:
        return self._send("GET", "/rest/api/3/project/")

    def assignable_users(self, project_key: str) -> list[dict]:
        return self._send(
            "GET", "/rest/api/3/user/assignable/search", params={"project": project_key}
        )

    def create_issue(self, fields: dict) -> str:
        return self._send("POST", "/rest/api/3/issue", json={"fields": fields})["key"]

    def _send(self, method: str, path: str, **kwargs):
        response = self._http.request(method, path, **kwargs)
        if response.is_error:
            raise JiraError(f"{method} {path} failed ({response.status_code}): {_reason(response)}")
        return response.json()


@contextmanager
def open_client(url: str, username: str, api_token: str, transport=None):
    with httpx.Client(
        base_url=url, auth=(username, api_token), headers=_HEADERS, timeout=30, transport=transport
    ) as http:
        yield JiraClient(http)


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    messages = list(body.get("errorMessages", []))
    messages += [f"{name}: {text}" for name, text in body.get("errors", {}).items()]
    return "; ".join(messages) or response.text
