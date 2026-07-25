"""Canonical candidate identity for all job-application scripts.

Last name: Lastname (single field — do not split).
First name: First (preferred) or First when forms reject diacritics.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

W = Path(__file__).resolve().parent
PREFS = W / "candidate_prefs.json"
# Default CV: 0020_raw; override with APPLY_CV_FILE=... (e.g. Desktop 021_cc)
CV_FILE = (
    (os.environ.get("APPLY_CV_FILE") or "").strip()
    or "cv.pdf"
)
CV_FILE_RAW = "cv.pdf"
CV_FILE_CC = "cv_cc.pdf"
CERTS_FILE = "First__Bayo_Alemany_certificates_2020_compressed.pdf"  # work certificates 2020
# Prefer uncompressed Desktop copy when present in workspace
if (W / "First__Bayo_Alemany_certificates_2020.pdf").is_file() and not (
    os.environ.get("APPLY_CERTS_FILE") or ""
).strip():
    # keep compressed as default unless full Desktop PDF preferred via env
    pass
_certs_override = (os.environ.get("APPLY_CERTS_FILE") or "").strip()
if _certs_override:
    CERTS_FILE = _certs_override
ACADEMIC_CERTS_FILE = "academic_certs.pdf"  # academic ETSETB
CV = str((W / CV_FILE).resolve())
CV_RAW = str((W / CV_FILE_RAW).resolve())
CV_CC = str((W / CV_FILE_CC).resolve())
CERTS = str((W / CERTS_FILE).resolve())
ACADEMIC_CERTS = str((W / ACADEMIC_CERTS_FILE).resolve())
# Extra supporting docs uploaded after primary work certs when forms allow more files
EXTRA_CERTS = [ACADEMIC_CERTS] if (W / ACADEMIC_CERTS_FILE).is_file() else []
CV_STEM = Path(CV_FILE).stem[:40]

FIRST = "First"
FIRST_ASCII = "First"
FIRST_ALT = "First"
LAST = "Lastname"
FULL = f"{FIRST} {LAST}"
FULL_ALT = f"{FIRST_ASCII} {LAST}"

_ES_CA_RE = re.compile(
    r"\.es\b|spain|españa|espana|barcelona|madrid|valencia|sevilla|"
    r"cataluña|catalunya|apellido|nombre|\.cat\b",
    re.I,
)


def _load_prefs() -> dict:
    if PREFS.exists():
        try:
            return json.loads(PREFS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_prefs = _load_prefs()
_contact = _prefs.get("contact") or {}
_salary = _prefs.get("salary_target_eur") or {}
_residence = _prefs.get("residence") or {}
_addr = _prefs.get("address") or {}
_edu = _prefs.get("education") or {}

# Prefer prefs; fall back to user-specified identity
PROFILE = {
    "first": FIRST,
    "first_ascii": FIRST_ASCII,
    "first_alt": FIRST_ALT,
    "last": LAST,
    "full": FULL,
    "full_alt": FULL_ALT,
    "email": _contact.get("email")
    or _prefs.get("email")
    or "you@example.com",
    "phone": _prefs.get("phone") or _contact.get("phone") or "+490000000000",
    "title": _prefs.get("professional_title") or "Telecommunications Engineer",
    "level": _prefs.get("education_level") or _edu.get("level") or "Master",
    "city": _residence.get("city") or "City",
    "country": _residence.get("country") or "Germany",
    "residence": _residence.get("city") or "City",
    "residence_country": _residence.get("country") or "Germany",
    "address_street": _addr.get("street") or "Street 1",
    "address_postal": _addr.get("postal_code") or "00000",
    "address_city": _addr.get("city") or "City",
    "address_country": _addr.get("country") or "Germany",
    "address_full": _addr.get("full")
    or "Street 1, 00000 City, Germany",
    "school": _prefs.get("university")
    or "Universitat Politècnica de Catalunya",
    "school_aliases": _prefs.get("university_aliases")
    or [
        "BarcelonaTech",
        "Polytechnical University of Catalonia",
        "Universitat Politècnica de Catalunya",
        "Universitat Politecnica de Catalunya",
        "UPC",
        "ETSETB",
    ],
    "school_fallback": "Purdue University",
    "school_fallback_years": "2001 (one year)",
    # University degree notes: year 2003 (user 2026-07-25)
    "degree_year": str(_edu.get("degree_year") or "2003"),
    "degree_year_start": str(_edu.get("degree_year_start") or "2003"),
    "degree_year_end": str(_edu.get("degree_year_end") or "2003"),
    "graduation_year": str(_edu.get("graduation_year") or _edu.get("degree_year") or "2003"),
    # Company certificates: 2020 compressed pack; academic ETSETB separate
    "certificates_year": "2020",
    "certificates_label": "Company certificates 2020 (compressed)",
    "academic_certificates": ACADEMIC_CERTS_FILE,
    "academic_certificates_label": "ETSETB academic certificates + equivalences / government register",
    "gpa": _edu.get("gpa") or "2.6/4.0",
    "gpa_value": "2.6",
    "gpa_scale": "4.0",
    # Salary expectations (user): €70,400–€120,000 annual gross
    "salary_min": int(_salary.get("min") or 70400),
    "salary_max": int(_salary.get("max") or 120000),
    "salary_currency": "EUR",
    "salary": (
        f"{_salary.get('min', 70400)}-{_salary.get('max', 120000)} EUR"
        if _salary
        else "70400-120000 EUR"
    ),
    "salary_display": (
        f"€{int(_salary.get('min') or 70400):,}–€{int(_salary.get('max') or 120000):,}"
        .replace(",", ",")
    ),
    "salary_mid": str(int((_salary.get("min") or 70400) + (_salary.get("max") or 120000)) // 2),
    "cover": (
        "CV (0020_raw), ETSETB academic certificates, and company certificates 2020 attached. "
        "Telecommunications Engineer / Technology Lead / Software Architect (L5) — professional roles only "
        "(not Praktikum / internship / Werkstudent; not facility management). "
        "Open to remote, hybrid, onsite, permanent, and short-term / fixed-term contracts. "
        "Universities: UPC / BarcelonaTech / ETSETB / Polytechnical University of Catalonia "
        "(degree notes year 2003); fallback Purdue University (2001, one year). GPA 2.6/4.0. "
        "Salary expectations: €70,400–€120,000 gross per year. "
        "Gender: Male / Man. "
        "EU work authorization: Yes. "
        "EEO: race/ethnicity White; not a veteran; no disability. "
        "Based in City, Germany."
    ),
    "gender": _prefs.get("gender") or "Male",
    "gender_aliases": _prefs.get("gender_aliases")
    or ["Male", "Man", "Männlich", "Homme", "Masculino"],
    "work_authorization_eu": "Yes",
    "eeo": {
        "race": "White",
        "protected_veteran": "No",
        "disability": "No",
    },
}


def salary_for_field(field_name: str = "") -> str:
    """Pick the best salary string for a form field (min/max/range)."""
    name = (field_name or "").lower()
    smin = str(PROFILE.get("salary_min") or 70400)
    smax = str(PROFILE.get("salary_max") or 120000)
    if any(k in name for k in ("min", "from", "lower", "minimum", "base_min")):
        return smin
    if any(k in name for k in ("max", "to", "upper", "maximum", "ceiling", "top")):
        return smax
    if any(k in name for k in ("mid", "target", "desired", "expect", "wunsch", "expectation")):
        return PROFILE.get("salary") or f"{smin}-{smax} EUR"
    return PROFILE.get("salary") or f"{smin}-{smax} EUR"


def load_employment_snippets() -> dict:
    p = W / "employment_snippets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def employment_textbox(employer: str) -> str:
    """Single textbox content for Infosys or Accenture consolidated experience."""
    sn = load_employment_snippets()
    key = (employer or "").lower()
    if "infosys" in key:
        return sn.get("infosys_single_textbox") or ""
    if "accenture" in key:
        return sn.get("accenture_single_textbox") or ""
    return ""


def pick_first_name(context: str = "", *, ascii_ok: bool = False) -> str:
    """Use First by default; First when forms need ASCII."""
    if ascii_ok:
        return FIRST_ASCII
    if context and re.search(r"ascii|without accent|latin1", context, re.I):
        return FIRST_ASCII
    return FIRST


def name_for_field(field_hint: str = "", page_context: str = "") -> str | None:
    """Map a form field hint to the correct name part."""
    h = (field_hint or "").lower()
    if any(k in h for k in ("first", "vorname", "prenom", "given", "nombre", "fname")):
        if "last" in h or "apellido" in h or "surname" in h or "family" in h:
            return None
        return pick_first_name(page_context or h)
    if any(
        k in h
        for k in (
            "last",
            "nachname",
            "surname",
            "family",
            "apellido",
            "lname",
        )
    ):
        if "first" in h or "nombre" in h or "given" in h:
            return None
        return LAST
    return None


def university_search_order() -> list[str]:
    aliases = list(PROFILE.get("school_aliases") or [])
    primary = PROFILE.get("school") or ""
    order = []
    for u in [primary] + aliases + [PROFILE.get("school_fallback") or "Purdue University"]:
        if u and u not in order:
            order.append(u)
    return order
