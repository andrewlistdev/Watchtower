"""Shared HTTP session with timeouts and retries on transient failures."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import USER_AGENT

DEFAULT_TIMEOUT = 30


class APIError(Exception):
    def __init__(self, service: str, method: str, url: str, status: int | None, body: str):
        self.service = service
        self.status = status
        self.body = body
        super().__init__(f"{service} {method} {url} -> {status}: {body[:500]}")


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        # Retry reads only. Writes (create/close/note) are not retried automatically
        # so a timeout can never produce a duplicate SDP request or AW comment.
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    # Identifies Watchtower in the vendors' API logs.
    session.headers["User-Agent"] = USER_AGENT
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def check(service: str, resp: requests.Response) -> requests.Response:
    if resp.status_code >= 400:
        raise APIError(service, resp.request.method or "?", resp.url, resp.status_code, resp.text)
    return resp
