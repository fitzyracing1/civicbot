"""civicbot: let robots and agents call city-operated APIs.

Safety first: anything that would *do* something in the real world
(filing a 311 request) is dry-run by default.
"""
from .http import HttpTransport, HttpError
from .registry import Endpoint, Registry
from .open311 import Open311Client, Open311Error, PreparedRequest, ValidationError
from .geocode import Geocoder, GeocodeResult
from .resolver import JurisdictionResolver, Resolution
from .transit import TransitFeed

__version__ = "0.4.0"
__all__ = [
    "HttpTransport", "HttpError", "Endpoint", "Registry", "Open311Client",
    "Open311Error", "PreparedRequest", "ValidationError", "Geocoder",
    "GeocodeResult", "JurisdictionResolver", "Resolution", "TransitFeed",
]
