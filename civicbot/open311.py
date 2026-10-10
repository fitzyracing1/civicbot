"""Open311 GeoReport v2 client (https://wiki.open311.org/GeoReport_v2/).

Reads are live. ``create_request`` is DRY-RUN BY DEFAULT: it builds and
validates the exact POST form payload and returns it without sending.
Actually filing a request needs all three of ``dry_run=False``, an
``api_key`` and ``confirm="SEND"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Union

from .http import HttpTransport
from .registry import Endpoint

MAX_DESCRIPTION = 4000  # GeoReport v2 limit
CONFIRM_TOKEN = "SEND"


class Open311Error(Exception):
    pass


class ValidationError(Open311Error):
    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class PreparedRequest:
    """The exact HTTP call that *would* be (or was) made."""
    endpoint_id: str
    method: str
    url: str
    form: Dict[str, Any]
    dry_run: bool = True
    warnings: List[str] = field(default_factory=list)
    response: Any = None

    def redacted_form(self) -> Dict[str, Any]:
        f = dict(self.form)
        if "api_key" in f:
            f["api_key"] = "***"
        return f

    def as_dict(self) -> Dict[str, Any]:
        return {"endpoint": self.endpoint_id, "method": self.method, "url": self.url,
                "form": self.redacted_form(), "dry_run": self.dry_run,
                "warnings": self.warnings, "response": self.response}


class Open311Client:
    def __init__(self, endpoint: Endpoint, transport: Optional[HttpTransport] = None,
                 jurisdiction_id: Optional[str] = None, fmt: str = "json"):
        self.endpoint = endpoint
        self.http = transport or HttpTransport()
        self.jurisdiction_id = jurisdiction_id
        self.fmt = fmt
        self._services_cache: Dict[Any, List[dict]] = {}

    # ---- helpers -------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.endpoint.base_url.rstrip('/')}/{path}.{self.fmt}"

    def _params(self, lat: Optional[float] = None, lng: Optional[float] = None, **extra) -> dict:
        p: Dict[str, Any] = {"jurisdiction_id": self.jurisdiction_id}
        if self.endpoint.geo_scoped and lat is not None and lng is not None:
            p["lat"], p["long"] = lat, lng
        p.update(extra)
        return {k: v for k, v in p.items() if v is not None}

    # ---- reads ---------------------------------------------------------
    def list_services(self, lat: Optional[float] = None, lng: Optional[float] = None) -> List[dict]:
        key = (lat, lng) if self.endpoint.geo_scoped else None
        if key not in self._services_cache:
            data = self.http.get_json(self._url("services"), self._params(lat, lng))
            if not isinstance(data, list):
                raise Open311Error(f"unexpected services response: {str(data)[:200]}")
            self._services_cache[key] = data
        return self._services_cache[key]

    def get_service_definition(self, service_code: Union[str, int], lat: Optional[float] = None,
                               lng: Optional[float] = None) -> dict:
        return self.http.get_json(self._url(f"services/{service_code}"), self._params(lat, lng))

    def list_requests(self, *, service_code: Optional[str] = None, status: Optional[str] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None,
                      service_request_ids: Optional[List[str]] = None, page_size: Optional[int] = None,
                      lat: Optional[float] = None, lng: Optional[float] = None) -> List[dict]:
        params = self._params(lat, lng, service_code=service_code, status=status,
                              start_date=start_date, end_date=end_date, page_size=page_size,
                              service_request_id=",".join(map(str, service_request_ids)) if service_request_ids else None)
        return self.http.get_json(self._url("requests"), params)

    def get_request(self, service_request_id: Union[str, int]) -> Optional[dict]:
        data = self.http.get_json(self._url(f"requests/{service_request_id}"), self._params())
        if isinstance(data, list):
            return data[0] if data else None
        return data

    def get_token(self, token: str) -> Any:
        return self.http.get_json(self._url(f"tokens/{token}"), self._params())

    # ---- write (dry-run by default) -------------------------------------
    def build_request(self, service_code: Union[str, int], *, lat: Optional[float] = None,
                      lng: Optional[float] = None, address_string: Optional[str] = None,
                      address_id: Optional[str] = None, description: Optional[str] = None,
                      attributes: Optional[Mapping[str, Any]] = None, media_url: Optional[str] = None,
                      email: Optional[str] = None, first_name: Optional[str] = None,
                      last_name: Optional[str] = None, phone: Optional[str] = None,
                      device_id: Optional[str] = None, account_id: Optional[str] = None,
                      api_key: Optional[str] = None, definition: Optional[dict] = None,
                      known_services: Optional[List[dict]] = None) -> PreparedRequest:
        """Build + validate the POST /requests form. Never touches the network."""
        problems: List[str] = []
        warnings: List[str] = []
        if lat is None and address_string is None and address_id is None:
            problems.append("a location is required: lat+lng, address_string or address_id")
        if (lat is None) != (lng is None):
            problems.append("lat and lng must be given together")
        if lat is not None and lng is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
            problems.append("lat/lng out of range")
        if description and len(description) > MAX_DESCRIPTION:
            problems.append(f"description longer than {MAX_DESCRIPTION} chars")
        if known_services is not None:
            codes = {str(s.get("service_code")) for s in known_services}
            if str(service_code) not in codes:
                problems.append(f"service_code {service_code!r} not offered by {self.endpoint.id}")
        attributes = dict(attributes or {})
        if definition:
            for attr in definition.get("attributes", []):
                if not attr.get("variable", True):
                    continue
                code = str(attr.get("code"))
                if attr.get("required") and code not in attributes:
                    problems.append(f"required attribute {code!r} missing ({attr.get('description', '')[:60]})")
                vals = attr.get("values")
                if code in attributes and vals and attr.get("datatype") in ("singlevaluelist", "multivaluelist"):
                    allowed = {str(v.get("key")) for v in vals}
                    given = attributes[code] if isinstance(attributes[code], list) else [attributes[code]]
                    bad = [g for g in given if str(g) not in allowed]
                    if bad:
                        problems.append(f"attribute {code!r}: {bad} not in {sorted(allowed)}")
        if not self.endpoint.write:
            warnings.append(f"{self.endpoint.id} is not known to accept writes")
        if problems:
            raise ValidationError(problems)

        form: Dict[str, Any] = {"service_code": str(service_code)}
        optional = {"jurisdiction_id": self.jurisdiction_id, "lat": lat, "long": lng,
                    "address_string": address_string, "address_id": address_id,
                    "description": description, "media_url": media_url, "email": email,
                    "first_name": first_name, "last_name": last_name, "phone": phone,
                    "device_id": device_id, "account_id": account_id, "api_key": api_key}
        form.update({k: v for k, v in optional.items() if v is not None})
        for code, value in attributes.items():
            key = f"attribute[{code}]" + ("[]" if isinstance(value, list) else "")
            form[key] = value
        return PreparedRequest(self.endpoint.id, "POST", self._url("requests"), form, True, warnings)

    def create_request(self, service_code: Union[str, int], *, dry_run: bool = True,
                       confirm: Optional[str] = None, api_key: Optional[str] = None,
                       validate_remote: bool = False, **kwargs) -> PreparedRequest:
        """Prepare (and only if explicitly confirmed, send) a service request.

        validate_remote=True fetches the service list + definition (read-only GETs)
        so the payload is checked against the city's live schema.
        """
        if validate_remote:
            lat, lng = kwargs.get("lat"), kwargs.get("lng")
            services = self.list_services(lat, lng)
            kwargs.setdefault("known_services", services)
            svc = next((s for s in services if str(s.get("service_code")) == str(service_code)), None)
            if svc and svc.get("metadata"):
                kwargs.setdefault("definition", self.get_service_definition(service_code, lat, lng))
        prepared = self.build_request(service_code, api_key=api_key, **kwargs)
        if dry_run:
            return prepared
        if confirm != CONFIRM_TOKEN:
            raise Open311Error(f'refusing to send: pass confirm="{CONFIRM_TOKEN}" to file a real request')
        if self.endpoint.api_key_required_for_write and not api_key:
            raise Open311Error(f"refusing to send: {self.endpoint.id} requires an api_key for writes")
        prepared.dry_run = False
        prepared.response = self.http.post_form(prepared.url, prepared.form)
        return prepared
