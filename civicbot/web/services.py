"""Wiring shared by the web app and the worker: one place decides real X vs. the dev fake."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..http import HttpTransport
from ..resolver import JurisdictionResolver
from ..skills import Catalog, SafeFetcher
from ..x.oauth import DEFAULT_SCOPES, OAuthConfig, XOAuth2
from .budget import Budget
from .config import Settings
from .db import init_db
from .fakex import DevXOAuth2, FakeXTransport
from .stores import SqlPending, SqlTokenStore

OWNER_SCOPES = ("tweet.read", "users.read")  # sign-in only: identify the owner, then revoke


@dataclass
class Services:
    settings: Settings
    engine: Any
    sf: Any
    tokens: SqlTokenStore
    budget: Budget
    x_transport: HttpTransport
    oauth_owner: XOAuth2
    oauth_robot: XOAuth2
    resolver: JurisdictionResolver
    catalog: Catalog
    fetcher: SafeFetcher


def build_services(settings: Settings) -> Services:
    engine, sf = init_db(settings.database_url)
    if settings.dev_mode:
        from ..offline import OfflineTransport, offline_skill_fetcher
        x_http: HttpTransport = FakeXTransport(sf, settings.x_client_id, settings.x_client_secret)
        resolver = JurisdictionResolver(transport=OfflineTransport())
        fetcher = offline_skill_fetcher()
    else:
        x_http = HttpTransport()
        resolver = JurisdictionResolver()
        fetcher = SafeFetcher()

    def oauth(scopes):
        cfg = OAuthConfig(client_id=settings.x_client_id, client_secret=settings.x_client_secret,
                          redirect_uri=settings.redirect_uri, scopes=scopes)
        o = DevXOAuth2(cfg, x_http, settings.base_url) if settings.dev_mode else XOAuth2(cfg, x_http)
        o.pending = SqlPending(sf, settings.token_key)  # survives restarts / multiple web processes
        return o

    return Services(settings=settings, engine=engine, sf=sf, tokens=SqlTokenStore(sf, settings.token_key),
                    budget=Budget(sf, settings), x_transport=x_http, oauth_owner=oauth(OWNER_SCOPES),
                    oauth_robot=oauth(DEFAULT_SCOPES), resolver=resolver, catalog=Catalog(), fetcher=fetcher)
