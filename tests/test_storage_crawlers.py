from dataclasses import replace

from sqlalchemy import text

from jobradar.crawlers import crawl, native_queries
from jobradar.geo import Gazetteer, GeoProfile, Listing, WorkMode, evaluate, normalize_listing
from jobradar.storage import Store


class FixtureSource:
    """Synthetic source used only in tests; no production/demo data."""
    name = "fixture"
    capabilities = {"city", "province", "region", "radius", "remote", "national"}

    def __init__(self, jobs):
        self.jobs = jobs
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return iter(self.jobs)


def test_profile_and_listing_persistence(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    gazetteer = Gazetteer.bundled()
    profile = GeoProfile(national=True)
    job = normalize_listing(Listing("fixture", "https://example.invalid/a", "Fixture", "Fano",
                                     work_mode=WorkMode.HYBRID), gazetteer)
    first = Store(path)
    first.seed_gazetteer(gazetteer)
    first.save_profile("Italia", profile)
    first.save_profile("Remoto", GeoProfile(remote_only=True))
    first.save_profile("Italia", GeoProfile(national=True, include_hybrid=False))
    first.save_listing(job, profile, evaluate(job, profile))
    first.save_listing(replace(job, title="Updated fixture"), profile, evaluate(job, profile))
    first.engine.dispose()
    second = Store(path)
    assert len(second.profiles()) == 2
    assert second.profiles()["Italia"].include_hybrid is False
    assert second.profiles()["Remoto"].remote_only
    assert len(second.listings()) == 1
    saved = second.listings()[0]
    assert saved.title == "Updated fixture" and saved.original_location == "Fano"
    assert saved.latitude == job.latitude and saved.work_mode == WorkMode.HYBRID
    with second.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM geographic_evaluations")).scalar_one() == 2
        assert conn.execute(text("SELECT max(version) FROM schema_migrations")).scalar_one() == 1


def test_native_filters_then_local_filter(tmp_path):
    gazetteer = Gazetteer.bundled()
    fano = gazetteer.resolve("Fano")[0]
    jobs = [Listing("fixture", "one", "Fano fixture", "Fano", work_mode=WorkMode.ONSITE),
            Listing("fixture", "two", "Roma fixture", "Roma", work_mode=WorkMode.ONSITE)]
    source = FixtureSource(jobs)
    store = Store(tmp_path / "test.sqlite3")
    profile = GeoProfile(cities=[fano.code], provinces=["PU"], include_remote=False)
    report = crawl([source], profile, gazetteer, store)
    assert [q.kind for q in source.queries] == ["city", "province"]
    assert report.analyzed == 2 and report.accepted == 1 and report.rejected == 1
    assert report.duplicates == 2 and not report.errors
    assert len(store.listings()) == 2  # rejected listings retained with their reasons


def test_unsupported_native_filter_uses_superset():
    source = FixtureSource([])
    source.capabilities = {"city"}
    assert [q.kind for q in native_queries(GeoProfile(regions=["11"]), source)] == ["all"]


def test_failure_is_reported_and_other_sources_continue(tmp_path):
    class Broken(FixtureSource):
        def search(self, query):
            raise OSError("synthetic fixture error")

    report = crawl([Broken([]), FixtureSource([Listing("fixture", "one", "Fixture", "Fano", work_mode=WorkMode.ONSITE)])],
                   GeoProfile(national=True, include_remote=False), Gazetteer.bundled(), Store(tmp_path / "test.sqlite3"))
    assert report.accepted == 1 and report.errors == ["fixture: OSError"]
