"""Dominio geografico indipendente dalla GUI e dai crawler."""
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import csv
import math
from pathlib import Path
import re
import unicodedata


def key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().split())


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Municipality:
    code: str
    name: str
    province_code: str
    province: str
    region_code: str
    region: str
    latitude: float | None = None
    longitude: float | None = None

    @property
    def label(self):
        return f"{self.name} ({self.province_code}) [{self.code}]"


class Gazetteer:
    def __init__(self, municipalities):
        self.cities = {c.code: c for c in municipalities}
        self.labels = {c.label: c.code for c in self.cities.values()}
        self.names = {}
        for c in self.cities.values():
            # Bilingual official denominations also searchable separately.
            for name in {c.name, *c.name.split("/")}:
                self.names.setdefault(key(name), set()).add(c.code)

    @classmethod
    def bundled(cls):
        path = Path(__file__).parent / "data" / "municipalities.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = []
            for r in csv.DictReader(f):
                for column in ("latitude", "longitude"):
                    r[column] = float(r[column]) if r[column] else None
                rows.append(Municipality(**r))
        return cls(rows)

    def resolve(self, text: str, province: str | None = None) -> list[Municipality]:
        if text in self.labels:
            return [self.cities[self.labels[text]]]
        if text in self.cities:
            return [self.cities[text]]
        # Only exact names, with optional province qualification; never guess from substrings.
        match = re.fullmatch(r"\s*(.*?)\s*\(([A-Za-z]{2})\)\s*", text)
        if match:
            text, province = match.groups()
        ids = self.names.get(key(text), set())
        return sorted((self.cities[i] for i in ids if not province or key(province) in
                       (key(self.cities[i].province_code), key(self.cities[i].province))), key=lambda c: c.label)


def validate_coordinates(lat, lon):
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (lat, lon)):
        raise ValueError("Coordinate mancanti o non finite")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Coordinate WGS84 fuori intervallo")


def haversine(lat1, lon1, lat2, lon2):
    """Distanza in km in linea d'aria, NON percorso stradale."""
    validate_coordinates(lat1, lon1)
    validate_coordinates(lat2, lon2)
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1., max(0., h))))


@dataclass(frozen=True)
class Radius:
    label: str
    latitude: float
    longitude: float
    km: float
    municipality_code: str | None = None

    def __post_init__(self):
        validate_coordinates(self.latitude, self.longitude)
        if not math.isfinite(self.km) or self.km <= 0:
            raise ValueError("Il raggio deve essere positivo e finito")


@dataclass
class GeoProfile:
    cities: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    radii: list[Radius] = field(default_factory=list)
    national: bool = False
    remote_only: bool = False
    include_remote: bool = True
    include_hybrid: bool = True
    include_onsite: bool = True
    include_unknown_mode: bool = False
    include_unknown_location: bool = False
    excluded_cities: list[str] = field(default_factory=list)
    excluded_provinces: list[str] = field(default_factory=list)

    def validate(self, gazetteer):
        if self.remote_only and not self.include_remote:
            raise ValueError("La ricerca solo remota richiede di includere il remoto")
        if not (self.remote_only or self.national or self.cities or self.provinces or self.regions or self.radii):
            raise ValueError("Selezionare almeno un'area o Solo remoto")
        known_provinces = {c.province_code for c in gazetteer.cities.values()}
        known_regions = {c.region_code for c in gazetteer.cities.values()}
        if set(self.cities + self.excluded_cities) - gazetteer.cities.keys():
            raise ValueError("Comune non presente nell'archivio territoriale")
        if set(self.provinces + self.excluded_provinces) - known_provinces or set(self.regions) - known_regions:
            raise ValueError("Provincia o regione non presente nell'archivio territoriale")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["radii"] = [Radius(**r) for r in data.get("radii", [])]
        return cls(**data)


@dataclass
class Listing:
    source: str
    url: str
    title: str
    original_location: str | None = None
    municipality_code: str | None = None
    municipality: str | None = None
    province_code: str | None = None
    province: str | None = None
    region_code: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    work_mode: WorkMode = WorkMode.UNKNOWN
    remote_restrictions: str | None = None
    remote_italy_eligible: bool | None = None
    eligibility_evidence: str | None = None
    location_status: str = "unknown"

    def __post_init__(self):
        self.work_mode = WorkMode(self.work_mode)
        if self.remote_italy_eligible is not None and type(self.remote_italy_eligible) is not bool:
            raise ValueError("L'accessibilità dall'Italia deve essere true, false o null")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Fornire entrambe le coordinate o nessuna")
        if self.latitude is not None:
            validate_coordinates(self.latitude, self.longitude)


def normalize_listing(listing: Listing, gazetteer: Gazetteer) -> Listing:
    # Do not map foreign homonyms to Italy.
    if listing.country_code and listing.country_code.upper() != "IT":
        listing.location_status = "foreign"
        return listing
    matches = gazetteer.resolve(listing.municipality_code or listing.original_location or "", listing.province_code)
    if len(matches) == 1:
        city = matches[0]
        for name in ("province_code", "province", "region_code", "region"):
            setattr(listing, name, getattr(city, name))
        listing.municipality_code, listing.municipality = city.code, city.name
        # Preserve real source coordinates when supplied; otherwise use documented municipal point.
        if listing.latitude is None:
            listing.latitude, listing.longitude = city.latitude, city.longitude
        listing.country_code, listing.location_status = "IT", "resolved"
    else:
        listing.location_status = "ambiguous" if matches else "unknown"
        if not matches and not listing.municipality_code:
            location = key(listing.original_location or "")
            provinces = {(c.province_code, c.province, c.region_code, c.region) for c in gazetteer.cities.values()
                         if location and location in (key(c.province_code), key(c.province))}
            regions = {(c.region_code, c.region) for c in gazetteer.cities.values()
                       if location and location == key(c.region)}
            if len(provinces) == 1 and not regions:
                listing.province_code, listing.province, listing.region_code, listing.region = provinces.pop()
                listing.country_code, listing.location_status = "IT", "province_only"
            elif len(regions) == 1 and not provinces:
                listing.region_code, listing.region = regions.pop()
                listing.country_code, listing.location_status = "IT", "region_only"
            elif location in ("italia", "italy"):
                listing.country_code, listing.location_status = "IT", "country_only"
    return listing


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    distance_km: float | None = None
    reference: str | None = None


def evaluate(job: Listing, profile: GeoProfile) -> Decision:
    distances = []
    if job.latitude is not None and job.longitude is not None:
        distances = [(haversine(r.latitude, r.longitude, job.latitude, job.longitude), r) for r in profile.radii]
    nearest = min(distances, key=lambda p: p[0]) if distances else None
    distance, reference = (nearest[0], nearest[1].label) if nearest else (None, None)

    def result(ok, reason):
        return Decision(ok, reason, distance, reference)

    if job.municipality_code in profile.excluded_cities or job.province_code in profile.excluded_provinces:
        return result(False, "Area esclusa")
    mode = WorkMode(job.work_mode)
    if profile.remote_only and mode != WorkMode.REMOTE:
        return result(False, "Richiesto remoto completo")
    allowed = {WorkMode.REMOTE: profile.include_remote, WorkMode.HYBRID: profile.include_hybrid,
               WorkMode.ONSITE: profile.include_onsite, WorkMode.UNKNOWN: profile.include_unknown_mode}
    if not allowed[mode]:
        return result(False, "Modalità lavorativa esclusa o non specificata")
    if mode == WorkMode.REMOTE:
        if job.remote_italy_eligible is not True or not job.eligibility_evidence:
            return result(False, "Accessibilità del remoto dall'Italia non verificata o negata")
        return result(True, "Remoto completo accessibile dall'Italia; " + job.eligibility_evidence)
    if job.country_code and job.country_code.upper() != "IT":
        return result(False, "Località estera")
    if job.location_status == "ambiguous":
        return result(False, "Località ambigua: richiede disambiguazione")
    area_match = (job.municipality_code is not None and job.municipality_code in profile.cities or
                  job.province_code is not None and job.province_code in profile.provinces or
                  job.region_code is not None and job.region_code in profile.regions or
                  any(d <= r.km for d, r in distances) or
                  profile.national and job.country_code == "IT")
    if area_match:
        return result(True, "Area geografica inclusa")
    if not any((job.municipality_code, job.province_code, job.region_code, job.latitude is not None)):
        return result(profile.include_unknown_location, "Località non specificata")
    return result(False, "Fuori dalle aree selezionate o precisione insufficiente")
