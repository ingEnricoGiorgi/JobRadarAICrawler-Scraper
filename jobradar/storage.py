"""SQLite persistence. Schema migrations are transactional and versioned."""
from datetime import datetime, timezone
import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine, text

from .geo import GeoProfile, Listing

MIGRATIONS = [
    ["""CREATE TABLE geographic_profiles (
       name TEXT PRIMARY KEY, config TEXT NOT NULL, updated_at TEXT NOT NULL)""",
     """CREATE TABLE municipalities (
       code TEXT PRIMARY KEY, name TEXT NOT NULL, province_code TEXT NOT NULL,
       province TEXT NOT NULL, region_code TEXT NOT NULL, region TEXT NOT NULL,
       latitude REAL, longitude REAL)""",
     "CREATE INDEX ix_municipalities_name ON municipalities(name)",
     "CREATE INDEX ix_municipalities_area ON municipalities(province_code, region_code)",
     """CREATE TABLE job_listings (
       id INTEGER PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL,
       title TEXT NOT NULL, original_location TEXT, municipality_code TEXT,
       municipality TEXT, province_code TEXT, province TEXT, region_code TEXT,
       region TEXT, latitude REAL, longitude REAL, country_code TEXT,
       work_mode TEXT NOT NULL, remote_restrictions TEXT, remote_italy_eligible BOOLEAN,
       eligibility_evidence TEXT, location_status TEXT NOT NULL,
       first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, UNIQUE(source, url))""",
     "CREATE INDEX ix_listings_area ON job_listings(province_code, region_code)",
     "CREATE INDEX ix_listings_mode ON job_listings(work_mode)",
     """CREATE TABLE geographic_evaluations (
       id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL REFERENCES job_listings(id),
       profile_snapshot TEXT NOT NULL, accepted BOOLEAN NOT NULL, reason TEXT NOT NULL,
       distance_km REAL, reference TEXT, evaluated_at TEXT NOT NULL)""",
     "CREATE INDEX ix_evaluations_listing ON geographic_evaluations(listing_id)"]
]


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine("sqlite:///" + str(path))
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"))
            version = conn.execute(text("SELECT coalesce(max(version), 0) FROM schema_migrations")).scalar_one()
            if version > len(MIGRATIONS):
                raise ValueError("Database creato da una versione più recente")
            for index, statements in enumerate(MIGRATIONS, 1):
                if index > version:
                    for statement in statements:
                        conn.execute(text(statement))
                    conn.execute(text("INSERT INTO schema_migrations VALUES (:v)"), {"v": index})

    def seed_gazetteer(self, gazetteer):
        rows = [asdict(city) for city in gazetteer.cities.values()]
        if not rows:
            return
        columns = list(rows[0])
        sql = f"INSERT INTO municipalities ({','.join(columns)}) VALUES ({','.join(':'+c for c in columns)}) ON CONFLICT(code) DO UPDATE SET "
        sql += ','.join(f"{c}=excluded.{c}" for c in columns if c != "code")
        with self.engine.begin() as conn:
            conn.execute(text(sql), rows)

    def save_profile(self, name, profile):
        if not name.strip():
            raise ValueError("Specificare il nome del profilo")
        with self.engine.begin() as conn:
            conn.execute(text("""INSERT INTO geographic_profiles VALUES (:n,:c,:t)
                ON CONFLICT(name) DO UPDATE SET config=excluded.config, updated_at=excluded.updated_at"""),
                         {"n": name.strip(), "c": json.dumps(profile.to_dict(), ensure_ascii=False), "t": now()})

    def profiles(self):
        with self.engine.connect() as conn:
            return {r.name: GeoProfile.from_dict(json.loads(r.config)) for r in
                    conn.execute(text("SELECT name, config FROM geographic_profiles ORDER BY name"))}

    def save_listing(self, listing, profile, decision):
        row = asdict(listing)
        row["work_mode"] = str(row["work_mode"])
        columns = list(row)
        row.update(first_seen=now(), last_seen=now())
        sql = f"INSERT INTO job_listings ({','.join(row)}) VALUES ({','.join(':'+c for c in row)}) ON CONFLICT(source,url) DO UPDATE SET "
        sql += ','.join(f"{c}=excluded.{c}" for c in columns + ["last_seen"] if c not in ("source", "url"))
        with self.engine.begin() as conn:
            conn.execute(text(sql), row)
            listing_id = conn.execute(text("SELECT id FROM job_listings WHERE source=:source AND url=:url"), row).scalar_one()
            conn.execute(text("""INSERT INTO geographic_evaluations
               (listing_id,profile_snapshot,accepted,reason,distance_km,reference,evaluated_at)
               VALUES (:id,:profile,:accepted,:reason,:distance_km,:reference,:at)"""),
                         {"id": listing_id, "profile": json.dumps(profile.to_dict()), "at": now(), **asdict(decision)})
        return listing_id

    def listings(self):
        with self.engine.connect() as conn:
            jobs = []
            for r in conn.execute(text("SELECT * FROM job_listings ORDER BY id DESC")).mappings():
                fields = {k: r[k] for k in Listing.__dataclass_fields__}
                if fields["remote_italy_eligible"] is not None:
                    fields["remote_italy_eligible"] = bool(fields["remote_italy_eligible"])
                jobs.append(Listing(**fields))
            return jobs
