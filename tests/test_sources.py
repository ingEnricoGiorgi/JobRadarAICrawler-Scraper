from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest

from jobradar.crawlers import NativeQuery
from jobradar.geo import GeoProfile, WorkMode, evaluate
from jobradar.sources import JsonApiSource, parse_listing
from jobradar.storage import Store


@pytest.mark.parametrize("scope,expected", [
    ({"allowed_countries": ["IT", "FR"], "evidence": "Fixture allowedCountries field"}, True),
    ({"allowed_countries": ["US"], "evidence": "Fixture US only"}, False),
    ({"worldwide": True, "evidence": "Fixture worldwide"}, True),
    ({"worldwide": True, "excluded_countries": ["IT"], "evidence": "Fixture exclusion"}, False),
    ({"worldwide": True}, None),
    ({"evidence": "Fixture remote with no country scope"}, None),
])
def test_remote_scope_verified_from_explicit_fields(scope, expected):
    listing = parse_listing({"source": "fixture", "url": "url", "title": "Fixture", "work_mode": "remote", "remote_scope": scope})
    assert listing.remote_italy_eligible is expected
    assert evaluate(listing, GeoProfile(remote_only=True)).accepted is (expected is True)


def test_remote_scope_does_not_infer_work_mode():
    listing = parse_listing({"source": "fixture", "url": "url", "title": "Fixture", "remote_scope": {
        "worldwide": True, "evidence": "Fixture country scope only"}})
    assert listing.work_mode == WorkMode.UNKNOWN
    assert not evaluate(listing, GeoProfile(remote_only=True)).accepted


def test_remote_roundtrip_sqlite(tmp_path):
    store = Store(tmp_path / "remote.sqlite3")
    profile = GeoProfile(remote_only=True)
    job = parse_listing({"source": "fixture", "url": "url", "title": "Fixture", "work_mode": "remote", "remote_scope": {
        "allowed_countries": ["IT"], "evidence": "Fixture explicit IT"}})
    store.save_listing(job, profile, evaluate(job, profile))
    assert evaluate(store.listings()[0], profile).accepted
    with pytest.raises(ValueError):
        replace(job, remote_italy_eligible="true")


def test_native_http_parameters():
    source = JsonApiSource("fixture", "https://example.invalid/jobs?lang=it", {
        "radius": {"lat": "{latitude}", "lng": "{longitude}", "distance": "{radius_km}"},
        "city": {"istat": "{value}"}, "remote": {"work_mode": "remote", "country": "IT"},
    })
    query = NativeQuery("radius", "Fixture", 43, 13, 25)
    assert parse_qs(urlsplit(source.query_url(query)).query) == {
        "lang": ["it"], "lat": ["43"], "lng": ["13"], "distance": ["25"]}
    assert "radius" in source.capabilities


def test_json_http_source_consumes_and_validates_response(monkeypatch):
    from io import BytesIO
    import jobradar.sources as module

    received = []

    def fake_urlopen(request, **kwargs):
        received.append(request.full_url)
        return BytesIO(b'{"jobs":[{"url":"https://example.invalid/job","title":"Fixture","work_mode":"hybrid"}]}')

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    source = JsonApiSource("fixture", "https://example.invalid/jobs", {"province": {"province": "{value}"}}, "jobs")
    listings = list(source.search(NativeQuery("province", "PU")))
    assert received == ["https://example.invalid/jobs?province=PU"]
    assert listings[0].source == "fixture" and listings[0].work_mode == WorkMode.HYBRID
