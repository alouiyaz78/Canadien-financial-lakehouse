"""Shared HTTP session and the contract every source client follows.

A source client exposes two pure-ish functions:

* ``fetch(spec) -> RawPayload``: download the raw response, untouched (Bronze).
* ``parse(payload, spec) -> DataFrame[date, value]``: turn a raw payload into a
  tidy two-column frame (Silver). Parsing never hits the network, so it can be
  unit-tested on recorded fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "canadian-financial-lakehouse/0.2 (portfolio research project)"
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class RawPayload:
    content: bytes
    url: str
    extension: str  # "json" or "csv"


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
