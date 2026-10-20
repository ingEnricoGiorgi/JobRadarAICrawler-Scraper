"""Configurable JSON HTTP source for structured feeds under the user's control.

Source-native geographic parameter names/templates are configured explicitly.
Other providers can implement the Source protocol without changing the domain.
"""
import json
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import truststore

from .geo import Listing


def apply_remote_scope(listing, scope):
    """Require explicit, source-derived eligibility evidence, never office country.

    `scope` is structured evidence extracted by the adapter from the original
    posting: country allow/deny lists, explicit worldwide access, and a quote or
    field reference. Free text that cannot be resolved remains unverified.
    """
    evidence = scope.get("evidence")
    allowed = scope.get("allowed_countries")
    denied = scope.get("excluded_countries", [])
    if not isinstance(denied, list) or allowed is not None and not isinstance(allowed, list):
        raise ValueError("Le restrizioni remote richiedono liste di codici paese")
    denied = {str(c).upper() for c in denied}
    allowed = {str(c).upper() for c in allowed} if allowed is not None else None
    listing.eligibility_evidence = evidence
    listing.remote_restrictions = scope.get("original_text") or listing.remote_restrictions
    if not evidence:
        listing.remote_italy_eligible = None
    elif "IT" in denied:
        listing.remote_italy_eligible = False
    elif allowed is not None:
        listing.remote_italy_eligible = "IT" in allowed
    elif scope.get("worldwide") is True:
        listing.remote_italy_eligible = True
    else:
        listing.remote_italy_eligible = None
    return listing


def parse_listing(row):
    row = dict(row)
    scope = row.pop("remote_scope", None)
    listing = Listing(**row)
    return apply_remote_scope(listing, scope) if scope is not None else listing


class JsonApiSource:
    """One HTTP JSON response per native query; no bypass, login or invented jobs.

    Response contains a list, optionally under `results_key`. Each object follows
    Listing's schema (plus optional remote_scope). Parameters use ISTAT codes or
    configured source values; source adapters handle provider-specific mappings.
    """
    def __init__(self, name, endpoint, parameters=None, results_key=None):
        if urlsplit(endpoint).scheme != "https":
            raise ValueError("La fonte deve usare HTTPS")
        self.name, self.endpoint, self.results_key = name, endpoint, results_key
        self.parameters = parameters or {}
        self.capabilities = set(self.parameters) - {"all"}
        if self.capabilities - {"city", "province", "region", "radius", "national", "remote"}:
            raise ValueError("Capacità geografica sconosciuta")

    def query_url(self, query):
        values = dict(vars(query))
        parameters = {name: str(template).format(**values) for name, template in self.parameters.get(query.kind, {}).items()}
        parts = urlsplit(self.endpoint)
        pairs = list(parse_qsl(parts.query, keep_blank_values=True))
        pairs = [(k, v) for k, v in pairs if k not in parameters] + list(parameters.items())
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))

    def search(self, query):
        request = Request(self.query_url(query), headers={"Accept": "application/json", "User-Agent": "JobRadarAICrawler/0.1"})
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=30, context=context) as response:
            data = json.load(response)
        rows = data[self.results_key] if self.results_key else data
        if not isinstance(rows, list):
            raise ValueError("La risposta della fonte deve contenere una lista")
        for row in rows:
            row = dict(row)
            row.setdefault("source", self.name)
            yield parse_listing(row)
