"""Prefer Technology Lead & Software Architect roles over plain Senior SWE.

Priority (high → low):
  1. Technology Lead / Tech Lead / Technical Lead
  2. Software Architect / Solutions Architect / Enterprise Architect (software)
  3. Staff / Principal Software Engineer, Engineering Manager
  4. Senior Software Engineer (still allowed, lower queue rank)

Also allows technical PhD tracks. Skips retail, pure sales, facilities, internships.
"""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

# Career-site / JSearch query phrases (preferred first)
SEARCH_QUERY_PHRASE = "technology lead OR software architect"
SEARCH_QUERY_PHRASES = [
    "technology lead",
    "tech lead software",
    "software architect",
    "solution architect software",
    "principal software engineer",
    "staff software engineer",
    "senior software engineer",
]
SEARCH_QUERY_URL = quote(SEARCH_QUERY_PHRASE)
SEARCH_QUERY_PLUS = quote_plus(SEARCH_QUERY_PHRASE)

# Always skip — retail, service, non-tech, student/academic tracks
# (candidate is already a graduate — no university programmes / internships)
HARD_EXCLUDE = re.compile(
    r"retail|apple retail|genius bar|store manager|store employee|"
    r"customer service|customer support|customer care|call center|call centre|"
    r"help\s*desk|helpdesk agent|technical support agent|support agent|"
    r"cashier|warehouse operative|flight attendant|"
    r"recruiter|talent acquisition|human resources|\bHR\b|people operations|"
    r"marketing manager|content market|social media manager|copywriter|"
    r"account executive|business development manager|"
    r"sales area manager|area sales manager|regional sales|"
    r"specialist:\s*seasonal|seasonal,\s*full-time|retail specialist|"
    r"genius\b|store specialist|part[- ]?time sales|"
    r"customer success manager(?!.*engineer)|"
    # Never apply — facilities / site operations (not software)
    r"facility\s*manager|facilities\s*manager|facility\s*management|"
    r"facilities\s*management|facility\s*ops|facilities\s*ops|"
    r"building\s*manager|property\s*manager|site\s*facility|"
    r"immobilien\s*manager|hausmeister|gebaeude\s*manager|gebäude\s*manager|"
    r"internship|intern\b|interns\b|werkstudent|working\s*student|"
    r"\bpraktikum\b|\bpraktikant\b|\bpraktikantin\b|\bstage\b|"
    r"apprentice|apprenticeship|\bausbildung\b|"
    r"graduate (programme|program|scheme|internship|job|role|position)|"
    r"grad (programme|program|scheme)|new graduate|campus (hire|recruit)|"
    # PhD/doctoral roles are ALLOWED (see is_phd_role) — still exclude pure teaching-only
    r"lecturer|teaching assistant|scholarship|"
    r"msc programme|m\.sc\. programme|bachelor programme|"
    r"online\.|abertay",
    re.I,
)

# Absolute ban — always skip even when APPLY_ALL=1
# Professional only: never facility management; never student / internship tracks
NEVER_APPLY = re.compile(
    r"facility\s*manager|facilities\s*manager|facility\s*management|"
    r"facilities\s*management|facility\s*ops|facilities\s*ops|"
    r"building\s*manager(?!.*software)|property\s*manager|"
    r"immobilien\s*manager|hausmeister|gebaeude\s*manager|gebäude\s*manager|"
    r"facility\s*services|facilities\s*services|facility\s*coordinator|"
    r"facilities\s*coordinator|facility\s*technician|facilities\s*technician|"
    # Student / internship / Praktikum / dual study — NEVER (professional only)
    r"\bpraktikum\b|\bpraktikant\b|\bpraktikantin\b|"
    r"\binternship\b|\binternships\b|\bintern\b|\binterns\b|\bstage\b|"
    r"\bwerkstudent\b|\bworking\s*student\b|\bstudent\s*assistant\b|"
    r"\bstudent\b|\bstudents\b|\bstudierend|"
    r"\bduales?\s*studium\b|\bdual\s*study\b|\bco-?op\b|"
    r"\bapprentice\b|\bapprenticeship\b|\bausbildung\b|"
    r"\btrainee\b(?!.*(?:engineer|architect|lead|manager))|"
    r"graduate\s+(programme|program|scheme|internship|job|role|position|trainee)|"
    r"grad\s+(programme|program|scheme)|new\s+graduate|campus\s+(hire|recruit)|"
    r"entry[- ]level\s+graduate|university\s+(programme|program|scheme)|"
    r"\bbecario\b|\bpr[aá]cticas\b|\bstagiaire\b|"
    r"summer\s+intern|winter\s+intern|year[- ]in[- ]industry|"
    r"teaching\s+assistant|\bscholarship\b|"
    # PhD positions are allowed via is_phd_role() — do NOT ban phd/doctoral here
    # Junior / non-senior tracks — target senior/professional only
    r"\bjunior\b|\bjr\.?\b|"
    r"entry[- ]level|\bearly\s*career\b|"
    r"associate\s+(software|engineer|developer)(?!.*senior)|"
    r"\bwerkstudent\b|\bworking\s*student\b|"
    # User ban — never apply (company / site)
    r"abacus[- ]?nachhilfe|abacus-nachhilfe\.de",
    re.I,
)

# --- Title preference tiers (user: prefer tech lead & software architect) ---
# Tier A — highest priority
TECH_LEAD_SIGNAL = re.compile(
    r"technology\s+lead|"
    r"tech(?:nical)?\s+lead|"
    r"lead\s+technolog|"
    r"software\s+tech(?:nical)?\s+lead|"
    r"tech(?:nical)?\s+lead\s+(?:software|engineer)|"
    r"lead\s+software\s+(?:engineer|developer)|"
    r"software\s+lead|"
    r"lead\s+engineer|"
    r"engineering\s+lead|"
    r"team\s+lead(?:er)?\s+(?:software|engineering)|"
    r"head\s+of\s+(?:software|engineering|technology)|"
    r"engineering\s+manager|"
    r"manager[, ]+\s*software\s+engineering",
    re.I,
)

# Tier A — software / solutions architect
ARCHITECT_SIGNAL = re.compile(
    r"software\s+architect|"
    r"solution[s]?\s+architect|"
    r"systems?\s+architect|"
    r"enterprise\s+architect|"
    r"application\s+architect|"
    r"cloud\s+architect|"
    r"platform\s+architect|"
    r"technical\s+architect|"
    r"it\s+architect|"
    r"domain\s+architect|"
    r"\barchitect\b.*\b(software|solution|system|cloud|platform|application)\b|"
    r"\b(software|solution|system|cloud|platform|application)\b.*\barchitect\b",
    re.I,
)

# Tier B — staff / principal (above plain senior)
STAFF_PRINCIPAL_SIGNAL = re.compile(
    r"\bstaff\s+(?:software\s+)?(?:engineer|developer)\b|"
    r"\bprincipal\s+(?:software\s+)?(?:engineer|developer|architect)\b|"
    r"\bfellow\b|"
    r"\bdistinguished\s+engineer\b",
    re.I,
)

# Tier C — plain senior software engineer (allowed, lower rank)
PLAIN_SENIOR_SWE = re.compile(
    r"\bsenior\s+software\s+engineer\b|"
    r"\bsr\.?\s*software\s+engineer\b|"
    r"\bsenior\s+software\s+developer\b|"
    r"\bsenior\s+entwickler\b|"
    r"\bsoftware\s+engineer\s+(?:senior|sr)\b",
    re.I,
)

# Senior / professional seniority signal (any preferred+ok target)
SENIOR_SIGNAL = re.compile(
    r"\bsenior\b|\bsr\.?\b|"
    r"\bstaff\b|\bprincipal\b|\blead\b|"
    r"tech(?:nical)?\s+lead|team\s+lead|engineering\s+lead|"
    r"engineering\s+manager|head\s+of|"
    r"director|architect|fellow|"
    r"technology\s+lead",
    re.I,
)

# Skip unless clearly technical engineering
NON_ENG_EXCLUDE = re.compile(
    r"^project manager$|^program manager$|^product manager$|"
    r"^account manager$|^office manager$|^administrative assistant|"
    r"^executive assistant$|^receptionist$|^internship in marketing|"
    r"^graduate\b|^intern\b",
    re.I,
)

# University / degree-programme employers and URLs (blocked unless PhD track)
ACADEMIC_URL = re.compile(
    r"\.edu(/|$)|\.ac\.uk(/|$)|uni-|university|hochschule|/students?/|"
    r"/intern(ship)?s?(/|$)|/graduate|/campus|/phd|/postdoc|/faculty|"
    r"/programmes?/|/msc-|/mba-|online\.[a-z0-9-]+\.(ac\.uk|edu)|"
    r"euraxess|academics\.de|jobs\.ac\.uk",
    re.I,
)

# --- PhD / doctoral research positions (ALLOWED when technical) ---
PHD_SIGNAL = re.compile(
    r"\bph\.?\s*d\.?\b|\bphd\b|"
    r"doctoral\s+(researcher|candidate|student|position|fellow|research)|"
    r"doctorate|"
    r"doktorand|doktorandin|"
    r"wissenschaftliche[rn]?\s+mitarbeiter(?:in)?|"
    r"research\s+(associate|assistant|fellow)|"
    r"industrial\s+ph\.?\s*d|"
    r"marie\s+(?:sk.?odowska.?curie|curie)|msca\b|"
    r"promotionsstelle|promovieren",
    re.I,
)

# Technical fields aligned with candidate (telecom / software / AI / systems)
PHD_TECH_FIELD = re.compile(
    r"software|computer\s*science|informatics|informatik|information\s*technology|"
    r"telecommunication|telecommunications|electrical|electronics|electronic|"
    r"\bai\b|artificial\s*intelligence|machine\s*learning|deep\s*learning|"
    r"data\s*science|cyber|security|network|networking|systems?\s*engineering|"
    r"signal\s*processing|cloud|distributed|robotics|embedded|5g|6g|wireless|"
    r"communications?|digital|algorithm|optimization|optimisation|"
    r"autonomous|sensor|iot\b|edge\s*computing|high[- ]performance\s*computing|"
    r"quantum|semiconductor|vlsi|fpga|rf\b|radar|optics|"
    r"ingenieur|engineering|forschung|research",
    re.I,
)


def is_phd_role(title: str = "", url: str = "", company: str = "", description: str = "") -> bool:
    """True for PhD / doctoral research positions in technical fields.

    User request: also apply to PhD positions (still not bachelor internships).
    """
    blob = f"{title or ''} {company or ''} {url or ''} {description or ''}"
    if not PHD_SIGNAL.search(blob):
        return False
    # Reject pure non-tech PhD (e.g. pure humanities / marketing PhD)
    if re.search(
        r"\b(history|philosophy|literature|theology|law\s+phd|nursing|medicine\b|"
        r"marketing\s+phd|finance\s+phd|accounting\s+phd|hr\s+phd)\b",
        blob,
        re.I,
    ) and not PHD_TECH_FIELD.search(blob):
        return False
    # Prefer technical field signal; if title is clearly "PhD in X" allow when X tech-ish
    if PHD_TECH_FIELD.search(blob):
        return True
    # Explicit PhD + engineer/scientist still OK
    if re.search(r"engineer|scientist|researcher|informatik|computer", blob, re.I):
        return True
    # Bare "PhD position" on tech company careers page
    if re.search(
        r"sap|siemens|bosch|infineon|ericsson|nokia|airbus|thales|continental|"
        r"bmw|mercedes|google|microsoft|amazon|ibm|intel|qualcomm|huawei|"
        r"kit\.edu|tum\.de|ethz|epfl|upc\.edu|fraunhofer|max.?planck|dfki",
        blob,
        re.I,
    ):
        return True
    return False

# Title must contain **software** and a **lead**/architect signal
SOFTWARE_SIGNAL = re.compile(r"software|architect|technology\s+lead|tech\s+lead", re.I)
LEAD_SIGNAL = re.compile(
    r"\blead\b|"
    r"tech(?:nical)?\s+lead|team\s+lead|engineering\s+lead|"
    r"technology\s+lead|"
    r"lead\s+(?:software|engineer|developer|architect)|"
    r"software\s+lead|lead\s+software|"
    r"staff\s+(?:software|engineer)|principal\s+(?:software|engineer|architect)|"
    r"\barchitect\b|"
    r"head\s+of\s+(?:software|engineering|technology)|"
    r"engineering\s+manager|manager.*software|software.*manager|"
    r"director\s+of\s+(?:software|engineering)|"
    r"vp\s+(?:of\s+)?engineering",
    re.I,
)


def title_preference_score(title: str = "", company: str = "") -> int:
    """Higher = apply sooner. Technology Lead / Software Architect beat Senior SWE."""
    blob = f"{title or ''} {company or ''}".strip()
    if not blob:
        return 0
    score = 0
    # Tier A (highest)
    if TECH_LEAD_SIGNAL.search(blob):
        score += 100
    if ARCHITECT_SIGNAL.search(blob):
        score += 100
    # Tier B
    if STAFF_PRINCIPAL_SIGNAL.search(blob):
        score += 55
    # Generic lead/manager without "tech lead" wording
    if re.search(r"engineering\s+manager|head\s+of\s+engineering", blob, re.I):
        score += 70
    # Tier C — plain senior SWE (still ok, demoted vs lead/architect)
    if PLAIN_SENIOR_SWE.search(blob):
        score += 15
    elif re.search(r"\bsenior\b.*\b(software|engineer|developer)\b", blob, re.I):
        score += 20
    # Soft bonus for software/architect keywords
    if re.search(r"\bsoftware\b", blob, re.I):
        score += 5
    if re.search(r"\barchitect\b", blob, re.I):
        score += 10
    if re.search(r"technology\s+lead|tech\s+lead", blob, re.I):
        score += 15
    return score


def is_preferred_title(title: str = "", company: str = "") -> bool:
    """True for Technology Lead or Software/Solutions Architect titles."""
    blob = f"{title or ''} {company or ''}"
    return bool(TECH_LEAD_SIGNAL.search(blob) or ARCHITECT_SIGNAL.search(blob))


def is_plain_senior_swe(title: str = "") -> bool:
    """True for generic Senior Software Engineer (allowed but lower priority)."""
    return bool(PLAIN_SENIOR_SWE.search(title or ""))

# Sales-heavy titles that are not software engineering
SALES_ONLY = re.compile(
    r"sales engineer|sales area|senior sales|\bsales\b(?!force)",
    re.I,
)


def is_student_or_academic(title: str = "", url: str = "", company: str = "") -> bool:
    """True for student roles, internships, graduate schemes, university programmes.

    PhD / doctoral technical positions are NOT treated as student tracks.
    """
    if is_phd_role(title, url, company):
        return False
    blob = f"{title or ''} {company or ''} {url or ''}"
    if NEVER_APPLY.search(blob) and re.search(
        r"student|intern|praktik|werkstudent|graduate\s+(programme|program|scheme)|"
        r"ausbildung|apprentice|stage\b|becario|stagiaire|duales?\s*studium",
        blob,
        re.I,
    ):
        # "PhD student" still allowed via is_phd_role above
        if re.search(r"\bphd\b|ph\.?\s*d|doctoral|doktorand", blob, re.I):
            return False
        return True
    if re.search(
        r"internship|internships|\bintern\b|\binterns\b|"
        r"graduate (programme|program|scheme|job|role|position)|"
        r"(?<!phd )(?<!ph\.d )(?<!ph.d )\bstudent\b|\bstudents\b|werkstudent|working\s*student|"
        r"\bpraktikum\b|\bpraktikant\b|apprentice|ausbildung|"
        r"duales?\s*studium|dual\s*study|\bstagiaire\b|"
        r"faculty|professor|"
        r"msc programme|scholarship|campus (hire|recruit)|new graduate",
        blob,
        re.I,
    ):
        return True
    if ACADEMIC_URL.search(url or "") and not is_phd_role(title, url, company):
        return True
    if re.search(
        r"\b(university|universit[aä]t|universidad|hochschule|polytechnic)\b",
        company or "",
        re.I,
    ) and not is_phd_role(title, url, company):
        return True
    return False


def has_software_and_lead(title: str, company: str = "") -> bool:
    """True when title/company contains both software and a lead-level signal."""
    blob = f"{title or ''} {company or ''}".strip()
    if not blob:
        return False
    return bool(SOFTWARE_SIGNAL.search(blob) and LEAD_SIGNAL.search(blob))


def is_never_apply(title: str, company: str = "", url: str = "") -> bool:
    """True for roles we must never apply to (facility, student, junior, internship).

    Technical PhD / doctoral positions are allowed.
    """
    if is_phd_role(title, url, company):
        return False
    blob = f"{title or ''} {company or ''} {url or ''}"
    return bool(NEVER_APPLY.search(blob))


def is_junior_or_student_track(title: str = "", url: str = "", company: str = "") -> bool:
    """True for junior/student tracks — not senior/professional.

    PhD positions are not junior tracks.
    """
    if is_phd_role(title, url, company):
        return False
    if is_student_or_academic(title, url, company):
        return True
    blob = f"{title or ''} {url or ''} {company or ''}"
    if re.search(
        r"\bjunior\b|\bjr\.?\b|entry[- ]level|early\s*career|"
        r"werkstudent|working\s*student|duales?\s*studium|"
        r"internship|\bintern\b|praktikum",
        blob,
        re.I,
    ):
        return True
    return False


def is_senior_or_professional(title: str = "") -> bool:
    """True when title looks senior/professional (senior, staff, lead, principal, …)."""
    t = (title or "").strip()
    if not t:
        return False
    if is_junior_or_student_track(t):
        return False
    return bool(SENIOR_SIGNAL.search(t))


# Software-related engineering (aligned with cv_fit REQUIRE_SW_RELATED)
SOFTWARE_RELATED = re.compile(
    r"\bsoftware\b|"
    r"(java|kotlin|rust|python|devops|backend|frontend|fullstack|full[- ]stack|"
    r"platform|cloud|sre)\s*(engineer|developer|architect|engineering)|"
    r"(engineer|developer|architect).{0,20}(java|kotlin|rust|python|backend|devops)|"
    r"\bdevops\s*engineer\b|\bsite\s*reliability\b|"
    r"technology\s+lead|tech\s+lead|engineering\s+manager",
    re.I,
)


def is_target_role(title: str, company: str = "", url: str = "") -> bool:
    """True for preferred + acceptable professional software roles.

    Preferred: Technology Lead, Software/Solutions Architect.
    Also: staff/principal SWE, senior SWE, technical PhD.
    """
    blob = f"{title or ''} {company or ''}".strip()
    if not blob:
        return False
    # PhD track first (allowed even on university URLs)
    if is_phd_role(title, url, company):
        return True
    if is_never_apply(title, company, url):
        return False
    if is_student_or_academic(title, url, company):
        return False
    if is_junior_or_student_track(title, url, company):
        return False
    if HARD_EXCLUDE.search(blob) and not is_phd_role(title, url, company):
        return False
    if NON_ENG_EXCLUDE.search((title or "").strip()):
        return False
    if SALES_ONLY.search(title or ""):
        return False
    # Preferred titles
    if is_preferred_title(title, company):
        return True
    # Prefer software+lead, but also accept senior software-related engineering
    if has_software_and_lead(title, company):
        return True
    if SOFTWARE_RELATED.search(blob) and (
        is_senior_or_professional(title) or SENIOR_SIGNAL.search(blob)
    ):
        return True
    # Architect without the word "software" if clearly technical architect
    if ARCHITECT_SIGNAL.search(blob):
        return True
    # DevOps / SRE engineer is software-ops engineering (professional, non-junior)
    if re.search(r"\bdevops\s*engineer\b|\bsite\s*reliability\s*engineer\b|\bsre\b", blob, re.I):
        return True
    return False


def skip_reason(title: str, company: str = "", url: str = "") -> str | None:
    """Return why a role is skipped, or None if it is a target role."""
    if is_phd_role(title, url, company):
        return None
    if is_never_apply(title, company, url):
        blob = f"{title or ''} {company or ''} {url or ''}".lower()
        if re.search(
            r"student|praktikum|praktikant|internship|\bintern\b|werkstudent|"
            r"stage\b|ausbildung|apprentice|graduate\s+(programme|program|scheme)|"
            r"duales?\s*studium|stagiaire|becario|junior|entry[- ]level",
            blob,
            re.I,
        ):
            return "excluded_student_or_junior_never_apply"
        return "excluded_facility_manager_never_apply"
    if is_junior_or_student_track(title, url, company):
        return "excluded_student_or_junior_never_apply"
    if is_target_role(title, company, url):
        return None
    if is_student_or_academic(title, url, company):
        return "excluded_student_or_academic"
    blob = f"{title or ''} {company or ''}"
    if HARD_EXCLUDE.search(blob):
        return "excluded_non_engineering"
    if NON_ENG_EXCLUDE.search((title or "").strip()):
        return "excluded_non_swe_role"
    if SALES_ONLY.search(title or ""):
        return "excluded_sales"
    blob = f"{title or ''} {company or ''}"
    # Software-related senior engineering (relaxed vs literal "software"+"lead")
    if SOFTWARE_RELATED.search(blob) and (
        is_senior_or_professional(title) or SENIOR_SIGNAL.search(blob)
    ):
        return None
    if not SOFTWARE_SIGNAL.search(blob) and not SOFTWARE_RELATED.search(blob):
        return "excluded_missing_software_keyword"
    if not LEAD_SIGNAL.search(blob) and not SENIOR_SIGNAL.search(blob):
        return "excluded_missing_lead_keyword"
    return "excluded_not_software_lead"


def filter_rows(rows: list[dict], *, log_fn=None) -> list[dict]:
    """Drop rows that are not software + lead roles."""
    kept: list[dict] = []
    for r in rows:
        title = r.get("title") or r.get("job_title") or ""
        company = r.get("company") or ""
        reason = skip_reason(title, company)
        if reason:
            if log_fn:
                log_fn(f"  skip [{reason}] {title[:70]}")
            continue
        kept.append(r)
    return kept