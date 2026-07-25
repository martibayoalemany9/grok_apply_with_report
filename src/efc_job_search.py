#!/usr/bin/env python3
"""Fetch real eFinancialCareers job posts with keyword **software**.

Search expands from City in 200 km rings up to 5000 km (priority: closer first).
Only keeps senior/professional roles that fit the 0020_raw CV (cv_fit).
"""
from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from candidate_profile import CERTS, CV
from cv_fit import job_fit_score
from role_filter import is_junior_or_student_track, is_never_apply

W = Path(__file__).resolve().parent
BASE = "https://job-search-api.efinancialcareers.com/v1/efc/jobs/search"
SITE = "https://www.efinancialcareers.de"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

KA = (49.0069, 8.4037)  # City

# Rings from City (km)
RINGS_KM = [200, 400, 600, 800, 1000, 1500, 2000, 2500, 3000, 4000, 5000]

# City seeds per ring for eFC location search (API radius is weak)
# Includes user cities: Spain provinces + Frankfurt, Berlin, Munich, Paris, Luxembourg, Amsterdam, London
RING_CITIES: dict[int, list[str]] = {
    200: [
        "City",
        "Stuttgart",
        "Mannheim",
        "Heidelberg",
        "Frankfurt",
        "Strasbourg",
        "Baden-Baden",
        "Darmstadt",
        "Luxembourg",  # ~200–220 km
    ],
    400: [
        "Munich",
        "Cologne",
        "Düsseldorf",
        "Basel",
        "Zurich",
        "Nuremberg",
        "Freiburg",
        "Amsterdam",  # ~450 km — also listed under 600
    ],
    600: [
        "Hamburg",
        "Berlin",
        "Amsterdam",
        "Paris",
        "Brussels",
        "Lyon",
        "Vienna",
        "Milan",
    ],
    800: [
        "London",
        "Prague",
        "Warsaw",
        "Copenhagen",
        "Barcelona",
        "Girona",
        "Tarragona",
        "Lleida",
        "Castellón",
        "Valencia",
        "Alicante",
    ],
    1000: [
        "Madrid",
        "Rome",
        "Stockholm",
        "Dublin",
        "Oslo",
        "Murcia",
        "Granada",
        "Almería",
        "Málaga",
        "Sevilla",
        "Salamanca",
        "Pamplona",
        "Logroño",
        "Álava",
        "Vitoria-Gasteiz",
        "Gipuzkoa",
        "San Sebastián",
        "Vizcaya",
        "Bilbao",
        "Oviedo",
        "La Coruña",
        "A Coruña",
        "Pontevedra",
        "Islas Baleares",
        "Palma",
    ],
    1500: [
        "Helsinki",
        "Lisbon",
        "Athens",
        "Bucharest",
        "Islas Canarias",
        "Las Palmas",
        "Santa Cruz de Tenerife",
    ],
    2000: ["Istanbul", "Moscow"],
    2500: ["Tel Aviv"],
    3000: ["Dubai"],
    4000: ["New York", "Boston"],
    5000: ["Toronto", "Chicago", "Singapore"],
}

# Extra always-searched cities (user list) even if also in rings
USER_SEARCH_CITIES: list[str] = [
    # Spain
    "Álava",
    "Vitoria-Gasteiz",
    "Alicante",
    "Almería",
    "Barcelona",
    "Castellón",
    "Gipuzkoa",
    "San Sebastián",
    "Girona",
    "Granada",
    "Islas Baleares",
    "Palma",
    "Islas Canarias",
    "Las Palmas",
    "La Coruña",
    "A Coruña",
    "Logroño",
    "Lleida",
    "Madrid",
    "Málaga",
    "Murcia",
    "Oviedo",
    "Pamplona",
    "Pontevedra",
    "Salamanca",
    "Sevilla",
    "Tarragona",
    "Valencia",
    "Vizcaya",
    "Bilbao",
    # Core EU hubs
    "Frankfurt",
    "Berlin",
    "Munich",
    "Paris",
    "Luxembourg",
    "Amsterdam",
    "London",
]

CITY_COORDS: dict[str, tuple[float, float]] = {
    "karlsruhe": (49.0069, 8.4037),
    "stuttgart": (48.7758, 9.1829),
    "mannheim": (49.4875, 8.466),
    "heidelberg": (49.3988, 8.6724),
    "frankfurt": (50.1109, 8.6821),
    "strasbourg": (48.5734, 7.7521),
    "baden-baden": (48.7606, 8.2397),
    "darmstadt": (49.8728, 8.6512),
    "munich": (48.1351, 11.582),
    "münchen": (48.1351, 11.582),
    "cologne": (50.9375, 6.9603),
    "köln": (50.9375, 6.9603),
    "düsseldorf": (51.2277, 6.7735),
    "dusseldorf": (51.2277, 6.7735),
    "basel": (47.5596, 7.5886),
    "zurich": (47.3769, 8.5417),
    "luxembourg": (49.6116, 6.1319),
    "luxemburg": (49.6116, 6.1319),
    "nuremberg": (49.4521, 11.0767),
    "freiburg": (47.999, 7.8421),
    "hamburg": (53.5511, 9.9937),
    "berlin": (52.52, 13.405),
    "amsterdam": (52.3676, 4.9041),
    "paris": (48.8566, 2.3522),
    "brussels": (50.8503, 4.3517),
    "lyon": (45.764, 4.8357),
    "vienna": (48.2082, 16.3738),
    "milan": (45.4642, 9.19),
    "london": (51.5074, -0.1278),
    "prague": (50.0755, 14.4378),
    "warsaw": (52.2297, 21.0122),
    "copenhagen": (55.6761, 12.5683),
    # Spain (user list)
    "áava": (42.8467, -2.6716),  # typo guard unused
    "álava": (42.8467, -2.6716),
    "alava": (42.8467, -2.6716),
    "vitoria-gasteiz": (42.8467, -2.6716),
    "vitoria": (42.8467, -2.6716),
    "alicante": (38.3452, -0.4810),
    "almería": (36.8340, -2.4637),
    "almeria": (36.8340, -2.4637),
    "barcelona": (41.3874, 2.1686),
    "castellón": (39.9864, -0.0513),
    "castellon": (39.9864, -0.0513),
    "castelló": (39.9864, -0.0513),
    "gipuzkoa": (43.3183, -1.9812),
    "san sebastián": (43.3183, -1.9812),
    "san sebastian": (43.3183, -1.9812),
    "donostia": (43.3183, -1.9812),
    "girona": (41.9794, 2.8214),
    "gerona": (41.9794, 2.8214),
    "granada": (37.1773, -3.5986),
    "islas baleares": (39.5696, 2.6502),
    "baleares": (39.5696, 2.6502),
    "palma": (39.5696, 2.6502),
    "palma de mallorca": (39.5696, 2.6502),
    "islas canarias": (28.1235, -15.4363),
    "canarias": (28.1235, -15.4363),
    "las palmas": (28.1235, -15.4363),
    "las palmas de gran canaria": (28.1235, -15.4363),
    "santa cruz de tenerife": (28.4636, -16.2518),
    "la coruña": (43.3623, -8.4115),
    "a coruña": (43.3623, -8.4115),
    "coruña": (43.3623, -8.4115),
    "coruna": (43.3623, -8.4115),
    "logroño": (42.4627, -2.4449),
    "logrono": (42.4627, -2.4449),
    "lleida": (41.6176, 0.6200),
    "lérida": (41.6176, 0.6200),
    "madrid": (40.4168, -3.7038),
    "málaga": (36.7213, -4.4214),
    "malaga": (36.7213, -4.4214),
    "murcia": (37.9922, -1.1307),
    "oviedo": (43.3619, -5.8494),
    "pamplona": (42.8125, -1.6458),
    "pontevedra": (42.4310, -8.6444),
    "salamanca": (40.9701, -5.6635),
    "sevilla": (37.3891, -5.9845),
    "seville": (37.3891, -5.9845),
    "tarragona": (41.1189, 1.2445),
    "valencia": (39.4699, -0.3763),
    "vizcaya": (43.2630, -2.9350),
    "bizkaia": (43.2630, -2.9350),
    "bilbao": (43.2630, -2.9350),
    # Rest of Europe / world
    "rome": (41.9028, 12.4964),
    "stockholm": (59.3293, 18.0686),
    "dublin": (53.3498, -6.2603),
    "oslo": (59.9139, 10.7522),
    "helsinki": (60.1699, 24.9384),
    "lisbon": (38.7223, -9.1393),
    "athens": (37.9838, 23.7275),
    "bucharest": (44.4268, 26.1025),
    "istanbul": (41.0082, 28.9784),
    "moscow": (55.7558, 37.6173),
    "tel aviv": (32.0853, 34.7818),
    "dubai": (25.2048, 55.2708),
    "new york": (40.7128, -74.006),
    "boston": (42.3601, -71.0589),
    "toronto": (43.6532, -79.3832),
    "chicago": (41.8781, -87.6298),
    "singapore": (1.3521, 103.8198),
    "bonn": (50.7374, 7.0982),
    "bad homburg": (50.2268, 8.618),
}

BAN = re.compile(
    r"werkstudent|working\s*student|\bstudent\b|praktikum|internship|\bintern\b|"
    r"duales?\s*studium|junior|\bjr\.?\b|entry[- ]level|ausbildung|apprentice|"
    r"graduate\s+(programme|program|scheme)|stagiaire|becario",
    re.I,
)
# User: keyword software before applying
SOFTWARE_RE = re.compile(r"\bsoftware\b", re.I)
SENIOR = re.compile(
    r"senior|staff|principal|\blead\b|architect|director|manager|head\s+of|"
    r"tech(?:nical)?\s+lead|technology\s+lead",
    re.I,
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def city_distance_km(city: str) -> float | None:
    if not city:
        return None
    key = city.strip().lower().split(",")[0].strip()
    if key in CITY_COORDS:
        la, lo = CITY_COORDS[key]
        return haversine_km(KA[0], KA[1], la, lo)
    # fuzzy: first word
    for name, (la, lo) in CITY_COORDS.items():
        if name in key or key in name:
            return haversine_km(KA[0], KA[1], la, lo)
    return None


def ring_of(dist: float | None) -> int:
    if dist is None:
        return 5000
    for r in RINGS_KM:
        if dist <= r:
            return r
    return 5000


def fetch_page(q: str, location: str, page: int = 1, page_size: int = 40) -> dict:
    params = {
        "q": q,
        "location": location,
        "page": page,
        "pageSize": page_size,
        "locale": "en-DE",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Origin": SITE,
            "Referer": SITE + "/en/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def search_software_jobs_rings(
    *,
    max_ring_km: int = 5000,
    max_pages_per_city: int = 2,
    queries: list[str] | None = None,
) -> list[dict]:
    """Search with keyword software, expanding City rings 200→max_ring_km."""
    # Always include bare "software" plus senior software variants
    queries = queries or [
        "software",
        "software engineer",
        "senior software engineer",
        "software architect",
        "software lead",
        "software developer",
    ]
    # Ensure every query contains software
    queries = [q if SOFTWARE_RE.search(q) else f"software {q}" for q in queries]

    seen: set[str] = set()
    jobs: list[dict] = []

    # Build ordered city list: rings first (closer first), then any user cities not already included
    ordered_cities: list[tuple[str, int]] = []  # (city, ring_km)
    seen_city: set[str] = set()
    for ring in RINGS_KM:
        if ring > max_ring_km:
            break
        for city in RING_CITIES.get(ring) or []:
            key = city.lower()
            if key in seen_city:
                continue
            seen_city.add(key)
            ordered_cities.append((city, ring))
    for city in USER_SEARCH_CITIES:
        key = city.lower()
        if key in seen_city:
            continue
        seen_city.add(key)
        dist = city_distance_km(city)
        ordered_cities.append((city, ring_of(dist)))

    def _location_query(city: str) -> str:
        """Country suffix for eFC location search."""
        c = city.lower()
        spain_markers = (
            "áava",
            "álava",
            "alava",
            "alicante",
            "almería",
            "almeria",
            "barcelona",
            "castellón",
            "castellon",
            "gipuzkoa",
            "girona",
            "granada",
            "baleares",
            "palma",
            "canarias",
            "las palmas",
            "coruña",
            "coruna",
            "logroño",
            "logrono",
            "lleida",
            "madrid",
            "málaga",
            "malaga",
            "murcia",
            "oviedo",
            "pamplona",
            "pontevedra",
            "salamanca",
            "sevilla",
            "seville",
            "tarragona",
            "valencia",
            "vizcaya",
            "bilbao",
            "vitoria",
            "san sebastián",
            "san sebastian",
            "islas ",
        )
        if any(m in c for m in spain_markers):
            return f"{city}, Spain"
        if c in ("luxembourg", "luxemburg"):
            return "Luxembourg"
        if c in ("london",):
            return "London, United Kingdom"
        if c in ("paris", "lyon"):
            return f"{city}, France"
        if c in ("amsterdam",):
            return "Amsterdam, Netherlands"
        if c in (
            "frankfurt",
            "berlin",
            "munich",
            "münchen",
            "hamburg",
            "stuttgart",
            "karlsruhe",
            "cologne",
            "düsseldorf",
            "dusseldorf",
        ):
            return f"{city}, Germany"
        return city

    for city, ring in ordered_cities:
        if ring > max_ring_km:
            continue
        for q in queries:
            for page in range(1, max_pages_per_city + 1):
                loc_q = _location_query(city)
                try:
                    data = fetch_page(q, loc_q, page=page)
                except Exception:
                    try:
                        data = fetch_page(q, city, page=page)
                    except Exception:
                        break
                batch = data.get("data") or []
                if not batch:
                    break
                for j in batch:
                    jid = str(j.get("jobId") or j.get("id") or "")
                    if not jid or jid in seen:
                        continue
                    title = j.get("title") or ""
                    company = j.get("companyName") or j.get("clientBrandName") or ""
                    path = j.get("detailsPageUrl") or ""
                    summary = (j.get("summary") or "") + " " + (j.get("description") or "")
                    if not path:
                        continue
                    blob = f"{title} {company} {path} {summary}"
                    # Keyword software mandatory
                    if not SOFTWARE_RE.search(blob):
                        continue
                    if BAN.search(blob):
                        continue
                    if is_never_apply(title, company, path) or is_junior_or_student_track(
                        title, path, company
                    ):
                        continue
                    # Prefer senior/professional; require software + (senior signal OR engineer)
                    if not SENIOR.search(title) and not re.search(
                        r"software\s+(engineer|architect|developer|lead)", title, re.I
                    ):
                        continue
                    # CV fit gate
                    fits, score, reason = job_fit_score(
                        title, summary, company, min_score=3
                    )
                    if not fits:
                        continue

                    loc = j.get("jobLocation") or {}
                    if isinstance(loc, dict):
                        city_name = loc.get("city") or loc.get("displayName") or city
                        location_s = loc.get("displayName") or city_name
                    else:
                        city_name = city
                        location_s = str(loc or city)
                    dist = city_distance_km(str(city_name))
                    if dist is None:
                        dist = city_distance_km(city)
                    # Keep jobs within current max ring (allow unknown as last priority)
                    if dist is not None and dist > max_ring_km:
                        continue

                    seen.add(jid)
                    url = path if path.startswith("http") else SITE + "/en" + (
                        path if path.startswith("/") else "/" + path
                    )
                    url = url.replace("/en/en/", "/en/")
                    jobs.append(
                        {
                            "job_id": jid,
                            "title": title,
                            "company": company,
                            "location": location_s,
                            "city": str(city_name),
                            "distance_km": round(dist, 1) if dist is not None else None,
                            "ring_km": ring_of(dist),
                            "url": url,
                            "is_external": j.get("isExternalApplication"),
                            "query": q,
                            "search_city": city,
                            "cv_fit_score": score,
                            "cv_fit_reason": reason,
                        }
                    )
                time.sleep(0.12)
        print(f"  searched {city} (ring~{ring}): jobs so far {len(jobs)}", flush=True)

    # Closest first, then higher CV fit
    jobs.sort(
        key=lambda j: (
            j.get("distance_km") if j.get("distance_km") is not None else 99999,
            -int(j.get("cv_fit_score") or 0),
        )
    )
    return jobs


def write_queue(jobs: list[dict], out: Path | None = None, limit: int = 100) -> Path:
    out = out or (W / "applications_software_rings_cvfit.csv")
    fields = [
        "app_id",
        "board",
        "company",
        "title",
        "location",
        "apply_url",
        "employer_url",
        "match_score",
        "cv_path",
        "certs_path",
        "salary_target",
        "status",
        "resolve",
        "source_note",
        "distance_km",
        "ring_km",
        "cv_fit_score",
    ]
    rows = []
    for i, j in enumerate(jobs[:limit], 1):
        rows.append(
            {
                "app_id": f"SWR-{i:04d}",
                "board": "efc_software_rings",
                "company": j.get("company") or "Unknown",
                "title": j.get("title") or "Senior Software Engineer",
                "location": f"{j.get('location') or ''} (~{j.get('distance_km')}km)"[:80],
                "apply_url": j.get("url"),
                "employer_url": j.get("url"),
                "match_score": j.get("cv_fit_score") or 0,
                "cv_path": CV,
                "certs_path": CERTS,
                "salary_target": "70400-120000 EUR",
                "status": "queued",
                "resolve": "ok",
                "source_note": (
                    f"software keyword; ring={j.get('ring_km')}; "
                    f"cv_fit={j.get('cv_fit_reason')}"
                ),
                "distance_km": j.get("distance_km") if j.get("distance_km") is not None else "",
                "ring_km": j.get("ring_km") or "",
                "cv_fit_score": j.get("cv_fit_score") or 0,
            }
        )
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    (W / "efc_software_rings_jobs.json").write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


def main() -> None:
    jobs = search_software_jobs_rings(max_ring_km=5000, max_pages_per_city=2)
    path = write_queue(jobs, limit=120)
    print(f"jobs={len(jobs)} queue={path} sample_dist={[j.get('distance_km') for j in jobs[:5]]}")


if __name__ == "__main__":
    main()
