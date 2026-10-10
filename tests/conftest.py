import json
import pathlib
import re

import pytest

from civicbot.http import HttpError, HttpTransport

FIX = pathlib.Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


class FakeTransport(HttpTransport):
    """Routes GETs by regex to canned JSON; records every call; POSTs are captured, never sent."""

    def __init__(self, routes=None, post_response=None):
        super().__init__()
        self.routes = list((routes or {}).items())
        self.calls, self.posts, self.headers = [], [], []
        self.post_routes = []  # (regex, response or callable(url, data, headers))
        self.post_response = post_response if post_response is not None else [{"service_request_id": "999"}]

    def add(self, pattern, response):
        self.routes.insert(0, (pattern, response))

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        self.headers.append(dict(headers or {}))
        for pat, resp in self.routes:
            if re.search(pat, url):
                return resp(url, params or {}) if callable(resp) else resp
        raise HttpError(404, url, "no fake route")

    def get_bytes(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        for pat, resp in self.routes:
            if re.search(pat, url):
                return resp
        raise HttpError(404, url, "no fake route")

    def add_post(self, pattern, response):
        self.post_routes.insert(0, (pattern, response))

    def _post(self, url, data, headers):
        self.posts.append((url, data))
        self.headers.append(dict(headers or {}))
        for pat, resp in self.post_routes:
            if re.search(pat, url):
                return resp(url, data, headers or {}) if callable(resp) else resp
        return self.post_response

    def post_form(self, url, data, headers=None):
        return self._post(url, dict(data), headers)

    def post_json(self, url, payload, headers=None):
        return self._post(url, payload, headers)


def census_hit(lat, lng, label="MATCHED"):
    return {"result": {"addressMatches": [{"coordinates": {"x": lng, "y": lat}, "matchedAddress": label}]}}


@pytest.fixture
def bloomington_services():
    return load("bloomington_services.json")


@pytest.fixture
def scf_services():
    return load("scf_services.json")


@pytest.fixture
def boston_services():
    return load("boston_services.json")


@pytest.fixture
def fake(bloomington_services, scf_services, boston_services):
    return FakeTransport({
        r"geocoding\.geo\.census\.gov": census_hit(39.16957, -86.536198, "401 N MORTON ST, BLOOMINGTON, IN, 47404"),
        r"nominatim": [],
        r"bloomington\.in\.gov/crm/open311/v2/services\.json": bloomington_services,
        r"bloomington\.in\.gov/crm/open311/v2/services/69\.json": {"service_code": "69", "attributes": [
            {"variable": True, "code": "issue", "datatype": "singlevaluelist", "required": False,
             "description": "Light in question",
             "values": [{"key": "City Maintained Light", "name": "City Maintained Light"},
                        {"key": "Private Light", "name": "Private Light"}]}]},
        r"bloomington\.in\.gov/crm/open311/v2/services/\w+\.json": {"attributes": []},
        r"311\.boston\.gov/open311/v2/services\.json": boston_services,
        r"seeclickfix\.com/open311/v2/services\.json":
            lambda u, p: scf_services if 41.2 < float(p.get("lat", 0)) < 41.4 else [],
        r"seeclickfix\.com/open311/v2/services/116\.json": {"service_code": 116, "attributes": [
            {"code": "189", "required": True, "variable": True, "datatype": "string",
             "description": "Please list the address/intersection/block range at which the pothole is located."}]},
        r"seeclickfix\.com/open311/v2/services/\w+\.json": {"attributes": []},
    })
