"""Capability-aware native query fan-out followed by mandatory local filtering.

Adapters must map structured source fields to Listing. No inference of remote
eligibility from office location, and no unconfigured network sources.
"""
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from .geo import GeoProfile, Listing, evaluate, normalize_listing


@dataclass(frozen=True)
class NativeQuery:
    kind: str
    value: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None


class Source(Protocol):
    name: str
    capabilities: set[str]  # city, province, region, radius, national, remote

    def search(self, query: NativeQuery) -> Iterable[Listing]: ...


def native_queries(profile: GeoProfile, source: Source):
    queries = []
    if not profile.remote_only:
        if profile.national:
            queries.append(NativeQuery("national", "IT"))
        else:
            queries.extend(NativeQuery("city", c) for c in profile.cities)
            queries.extend(NativeQuery("province", p) for p in profile.provinces)
            queries.extend(NativeQuery("region", r) for r in profile.regions)
            queries.extend(NativeQuery("radius", r.label, r.latitude, r.longitude, r.km) for r in profile.radii)
    if profile.include_remote:
        queries.append(NativeQuery("remote", "IT"))
    # Fallback must be a superset. Never narrow an unsupported region/radius to one city.
    if profile.include_unknown_location or any(q.kind not in source.capabilities for q in queries):
        return [NativeQuery("all")]
    return list(dict.fromkeys(queries))


@dataclass
class CrawlReport:
    analyzed: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


def crawl(sources, profile, gazetteer, store):
    profile.validate(gazetteer)
    report = CrawlReport()
    seen = set()
    for source in sources:
        for query in native_queries(profile, source):
            try:
                for listing in source.search(query):
                    identity = listing.source, listing.url
                    if identity in seen:
                        report.duplicates += 1
                        continue
                    seen.add(identity)
                    listing = normalize_listing(listing, gazetteer)
                    decision = evaluate(listing, profile)
                    store.save_listing(listing, profile, decision)
                    report.analyzed += 1
                    report.accepted += decision.accepted
                    report.rejected += not decision.accepted
            except Exception as exc:
                # Do not record source payloads, credentials or personal information.
                report.errors.append(f"{source.name}: {type(exc).__name__}")
    return report
