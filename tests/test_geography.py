"""All synthetic listings and coordinates here are explicit test fixtures."""
from dataclasses import replace
import math

import pytest

from jobradar.geo import (
    Gazetteer, Municipality, GeoProfile, Listing, Radius, WorkMode,
    evaluate, haversine, normalize_listing,
)


@pytest.fixture
def gazetteer():
    return Gazetteer([
        Municipality("a", "Alfa", "AA", "Provincia Alfa", "01", "Regione Uno", 43., 13.),
        Municipality("b", "Beta", "AA", "Provincia Alfa", "01", "Regione Uno", 43.1, 13.),
        Municipality("c", "Gamma", "BB", "Provincia Beta", "02", "Regione Due", 45., 9.),
        Municipality("d", "Omonimo", "AA", "Provincia Alfa", "01", "Regione Uno"),
        Municipality("e", "Omonimo", "BB", "Provincia Beta", "02", "Regione Due"),
    ])


@pytest.fixture
def job(gazetteer):
    return normalize_listing(Listing("test-fixture", "https://example.invalid/job", "Test fixture",
                                     original_location="Beta", work_mode=WorkMode.ONSITE), gazetteer)


@pytest.mark.parametrize("profile,accepted", [
    (GeoProfile(radii=[Radius("Alfa", 43, 13, 12)]), True),
    (GeoProfile(radii=[Radius("Alfa", 43, 13, 10)]), False),
    (GeoProfile(cities=["b"]), True),
    (GeoProfile(cities=["a"]), False),
    (GeoProfile(provinces=["AA"]), True),
    (GeoProfile(provinces=["BB"]), False),
    (GeoProfile(regions=["01"]), True),
    (GeoProfile(regions=["02"]), False),
    (GeoProfile(national=True), True),
    (GeoProfile(cities=["c"], provinces=["AA"]), True),
    (GeoProfile(radii=[Radius("Alfa", 43, 13, 1)], regions=["01"]), True),
    (GeoProfile(national=True, excluded_cities=["b"]), False),
    (GeoProfile(national=True, excluded_provinces=["AA"]), False),
    (GeoProfile(remote_only=True), False),
])
def test_search_modes(job, profile, accepted):
    assert evaluate(job, profile).accepted is accepted


def test_haversine_boundary(job):
    distance = haversine(43, 13, 43.1, 13)
    assert distance == pytest.approx(11.1195, abs=.001)
    profile = GeoProfile(radii=[Radius("boundary", 43, 13, distance)])
    result = evaluate(job, profile)
    assert result.accepted and result.distance_km == distance
    assert haversine(0, 0, 0, 0) == 0
    assert haversine(0, 0, 0, 180) == pytest.approx(math.pi * 6371.0088)


@pytest.mark.parametrize("coords", [(float("nan"), 0), (91, 0), (0, 181), (None, 0)])
def test_invalid_coordinates(coords):
    with pytest.raises(ValueError):
        Radius("invalid", *coords, 10)


def test_multiple_radii_and_nearest_reference(job):
    result = evaluate(job, GeoProfile(radii=[Radius("far", 45, 9, 1), Radius("near", 43, 13, 20)]))
    assert result.accepted and result.reference == "near"


@pytest.mark.parametrize("eligibility,evidence,accepted", [
    (True, "Source explicitly allows IT", True), (False, "US residents only", False),
    (None, None, False), (True, None, False),
])
def test_remote_italy_verification(job, eligibility, evidence, accepted):
    remote = replace(job, work_mode=WorkMode.REMOTE, remote_italy_eligible=eligibility,
                     eligibility_evidence=evidence)
    assert evaluate(remote, GeoProfile(remote_only=True)).accepted is accepted


def test_remote_outside_area_and_exclusions(job):
    remote = replace(job, work_mode=WorkMode.REMOTE, remote_italy_eligible=True,
                     eligibility_evidence="Fixture: Italy explicitly permitted")
    assert evaluate(remote, GeoProfile(cities=["c"])).accepted
    assert not evaluate(remote, GeoProfile(cities=["c"], excluded_provinces=["AA"])).accepted
    assert not evaluate(remote, GeoProfile(national=True, include_remote=False)).accepted


def test_modes_are_distinct(job):
    assert not evaluate(replace(job, work_mode=WorkMode.HYBRID), GeoProfile(remote_only=True)).accepted
    assert not evaluate(replace(job, work_mode=WorkMode.HYBRID), GeoProfile(national=True, include_hybrid=False)).accepted
    unknown = replace(job, work_mode=WorkMode.UNKNOWN)
    assert not evaluate(unknown, GeoProfile(national=True)).accepted
    assert evaluate(unknown, GeoProfile(national=True, include_unknown_mode=True)).accepted
    assert not evaluate(unknown, GeoProfile(remote_only=True, include_unknown_mode=True)).accepted


def test_unknown_and_ambiguous_locations(gazetteer):
    job = normalize_listing(Listing("fixture", "url", "Fixture", work_mode=WorkMode.ONSITE), gazetteer)
    assert job.municipality is None and job.latitude is None
    assert not evaluate(job, GeoProfile(national=True)).accepted
    assert evaluate(job, GeoProfile(national=True, include_unknown_location=True)).accepted
    job.original_location = "Omonimo"
    normalize_listing(job, gazetteer)
    assert job.location_status == "ambiguous" and job.municipality_code is None
    assert not evaluate(job, GeoProfile(national=True, include_unknown_location=True)).accepted
    assert len(gazetteer.resolve("Omonimo")) == 2
    assert gazetteer.resolve("Omonimo (BB)")[0].code == "e"


def test_foreign_location_not_national(job):
    assert not evaluate(replace(job, country_code="FR"), GeoProfile(national=True)).accepted


def test_no_coordinates_no_distance(gazetteer):
    job = normalize_listing(Listing("fixture", "url", "Fixture", original_location="Omonimo (AA)",
                                     work_mode=WorkMode.ONSITE), gazetteer)
    result = evaluate(job, GeoProfile(cities=["d"], radii=[Radius("test", 43, 13, 25)]))
    assert result.accepted and result.distance_km is None


def test_profile_serialization_and_validation(gazetteer):
    profile = GeoProfile(cities=["b"], radii=[Radius("test", 43, 13, 5)])
    assert GeoProfile.from_dict(profile.to_dict()) == profile
    profile.validate(gazetteer)
    with pytest.raises(ValueError):
        GeoProfile(cities=["not-real"]).validate(gazetteer)
    with pytest.raises(ValueError):
        GeoProfile().validate(gazetteer)


def test_official_bundled_dataset():
    gazetteer = Gazetteer.bundled()
    assert len(gazetteer.cities) >= 7800
    assert len({c.region_code for c in gazetteer.cities.values()}) == 20
    fano = gazetteer.resolve("Fano")[0]
    assert fano.province_code == "PU" and fano.region == "Marche"
    assert 43 < fano.latitude < 45 and 12 < fano.longitude < 14


@pytest.mark.parametrize("location,profile", [
    ("Marche", GeoProfile(regions=["11"])),
    ("Pesaro e Urbino", GeoProfile(provinces=["PU"])),
    ("PU", GeoProfile(provinces=["PU"])),
    ("Italia", GeoProfile(national=True)),
])
def test_partial_territorial_locations(location, profile):
    listing = normalize_listing(Listing("fixture", "url", "Fixture", location, work_mode=WorkMode.ONSITE), Gazetteer.bundled())
    assert evaluate(listing, profile).accepted
    assert listing.latitude is None and listing.municipality is None
