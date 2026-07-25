#!/usr/bin/env python3
"""Map company names → careers site URLs. Never apply on eFinancialCareers.

Pipeline:
  1) Known CAREERS_MAP (curated)
  2) Simple domain heuristics (company.com/careers, jobs.company.com, …)
  3) Optional DuckDuckGo HTML search for "{company} careers" / "{company} jobs"
  4) Caller searches the job *title* on that careers site and applies there
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

W = Path(__file__).resolve().parent
CACHE = W / "company_careers_cache.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Curated careers hubs (employer sites / ATS — NOT eFinancialCareers)
CAREERS_MAP: dict[str, str] = {

    # Airlines / aviation groups
    "lufthansa": "https://www.be-lufthansa.com/en",
    "lufthansa group": "https://www.be-lufthansa.com/en",
    "lufthansa technik": "https://www.lufthansa-technik.com/en/career",
    "air france": "https://recrutement.airfrance.com/en",
    "air france-klm": "https://www.airfranceklm.com/en/careers",
    "klm": "https://careers.klm.com/en",
    "easyjet": "https://careers.easyjet.com/",
    "ryanair": "https://careers.ryanair.com/",
    "british airways": "https://careers.ba.com/",
    "iberia": "https://www.iberia.com/es/empleos/",
    "vueling": "https://careers.vueling.com/",
    "iag": "https://www.iairgroup.com/en/careers",
    "wizz air": "https://careers.wizzair.com/",
    "swiss": "https://www.swiss.com/corporate/en/careers",
    "austrian airlines": "https://www.austrian.com/us/en/careers",
    "emirates": "https://www.emiratesgroupcareers.com/",
    "qatar airways": "https://careers.qatarairways.com/",
    "delta": "https://www.delta.com/us/en/careers/overview",
    "united airlines": "https://careers.united.com/",
    # Banking / fintech
    "scalable": "https://jobs.smartrecruiters.com/ScalableGmbH",
    "scalable gmbh": "https://jobs.smartrecruiters.com/ScalableGmbH",
    "scalable capital": "https://jobs.smartrecruiters.com/ScalableGmbH",
    "deutsche bank": "https://careers.db.com/",
    "db": "https://careers.db.com/",
    "commerzbank": "https://jobs.commerzbank.com/",
    "dz bank": "https://karriere.dzbank.de/",
    "ing": "https://www.ing.jobs/",
    "n26": "https://n26.com/en-eu/careers",
    "trade republic": "https://traderepublic.com/careers",
    "solaris": "https://www.solarisgroup.com/en/careers/",
    # Pharma / industry
    "merck": "https://careers.merckgroup.com/global/en/search-results",
    "merck healthcare": "https://careers.merckgroup.com/global/en/search-results",
    "merck group": "https://careers.merckgroup.com/global/en/search-results",
    "merck kgaa": "https://careers.merckgroup.com/global/en/search-results",
    "p3": "https://p3-group.com/en/career/",
    "p3 group": "https://p3-group.com/en/career/",
    "p3 automotive": "https://p3-group.com/en/career/",
    "bosch": "https://www.bosch.com/careers/",
    "siemens": "https://jobs.siemens.com/",
    "sap": "https://jobs.sap.com/",
    "sap se": "https://jobs.sap.com/",
    "infineon": "https://www.infineon.com/cms/en/careers/",
    "infineon technologies": "https://www.infineon.com/cms/en/careers/",
    "continental": "https://www.continental.com/en/career/",
    "zf": "https://jobs.zf.com/",
    "zf friedrichshafen": "https://jobs.zf.com/",
    # Tech / consulting
    "accenture": "https://www.accenture.com/us-en/careers",
    "capgemini": "https://www.capgemini.com/careers/",
    "thoughtworks": "https://www.thoughtworks.com/careers",
    "zalando": "https://jobs.zalando.com/",
    "delivery hero": "https://careers.deliveryhero.com/",
    "hellofresh": "https://careers.hellofresh.com/",
    "auto1": "https://www.auto1-group.com/jobs/",
    "auto1 group": "https://www.auto1-group.com/jobs/",
    "personio": "https://www.personio.com/about-personio/careers/",
    "celonis": "https://www.celonis.com/careers/",
    "contentful": "https://www.contentful.com/careers/",
    "adjust": "https://www.adjust.com/company/careers/",
    "getyourguide": "https://www.getyourguide.careers/",
    "klarna": "https://www.klarna.com/careers/",
    "wise": "https://wise.jobs/",
    "revolut": "https://www.revolut.com/careers/",
    "stripe": "https://stripe.com/jobs",
    "google": "https://www.google.com/about/careers/",
    "microsoft": "https://careers.microsoft.com/",
    "amazon": "https://www.amazon.jobs/",
    "meta": "https://www.metacareers.com/",
    "apple": "https://jobs.apple.com/",
    "ibm": "https://www.ibm.com/careers",
    "oracle": "https://careers.oracle.com/",
    "cisco": "https://jobs.cisco.com/",
    "atlassian": "https://www.atlassian.com/company/careers",
    "spotify": "https://www.lifeatspotify.com/",
    "booking": "https://careers.booking.com/",
    "booking.com": "https://careers.booking.com/",
    "mozilla": "https://www.mozilla.org/en-US/careers/listings/",
    "criteo": "https://careers.criteo.com/search/",
    "grab": "https://www.grab.careers/",
    "tencent": "https://careers.tencent.com/",
    "cloudflare": "https://www.cloudflare.com/careers/jobs/",
    "dynatrace": "https://careers.dynatrace.com/",
    "telefonica": "https://jobs.telefonica.com/",
    "telefónica": "https://jobs.telefonica.com/",
    "schneider": "https://www.se.com/ww/en/about-us/careers/",
    "schneider electric": "https://www.se.com/ww/en/about-us/careers/",
    "nttdata": "https://www.nttdata.com/global/en/careers",
    "ntt data": "https://www.nttdata.com/global/en/careers",
    "shoplevers": "https://www.shoplevers.com/",
    "veeva": "https://careers.veeva.com/",
    "veeva systems": "https://careers.veeva.com/",
    "adesso": "https://www.adesso.de/de/jobs-karriere/",
    "msg": "https://www.msg.group/en/career",
    "msg systems": "https://www.msg.group/en/career",
    "bechtle": "https://www.bechtle.com/de-en/career",
    "cancom": "https://www.cancom.com/career/",
    "datev": "https://www.datev.de/web/de/karriere/",
    "atruvia": "https://www.atruvia.de/karriere",
    "fiducia": "https://www.atruvia.de/karriere",
}

BOARD_HOSTS = re.compile(
    r"efinancialcareers|spmailtechnolo|eurotechjobs|euroengineerjobs|"
    r"space-careers|stepstone|indeed\.|linkedin\.com/jobs|glassdoor|"
    r"xing\.com/jobs|join\.com",
    re.I,
)


def _norm_company(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\b(gmbh|ag|se|sa|ltd|llc|inc|plc|co\.?|group|holding)\b\.?", "", s)
    s = re.sub(r"[^\w\s&\-\.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_board_url(url: str) -> bool:
    return bool(BOARD_HOSTS.search(url or ""))


def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def lookup_known(company: str) -> str | None:
    raw = (company or "").strip().lower()
    if raw in CAREERS_MAP:
        return CAREERS_MAP[raw]
    n = _norm_company(company)
    if n in CAREERS_MAP:
        return CAREERS_MAP[n]
    # substring match longest key first
    for key in sorted(CAREERS_MAP.keys(), key=len, reverse=True):
        if key in raw or key in n or n in key:
            return CAREERS_MAP[key]
    return None


def _http_ok(url: str, timeout: float = 8.0) -> bool:
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 400
    except Exception:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= getattr(r, "status", 200) < 400
        except Exception:
            return False


def heuristic_careers_urls(company: str) -> list[str]:
    """Guess careers URLs from company name."""
    n = _norm_company(company)
    if not n:
        return []
    slug = re.sub(r"[^a-z0-9]+", "", n.split()[0] if n else "")
    multi = re.sub(r"[^a-z0-9]+", "", n)
    names = []
    if slug:
        names.append(slug)
    if multi and multi != slug:
        names.append(multi)
    # second word if present (e.g. deutsche bank → deutschebank)
    parts = n.split()
    if len(parts) >= 2:
        names.append(re.sub(r"[^a-z0-9]+", "", "".join(parts[:2])))

    urls: list[str] = []
    seen: set[str] = set()
    for name in names:
        if len(name) < 3:
            continue
        candidates = [
            f"https://careers.{name}.com/",
            f"https://jobs.{name}.com/",
            f"https://www.{name}.com/careers",
            f"https://www.{name}.com/career",
            f"https://www.{name}.de/karriere",
            f"https://www.{name}.de/careers",
            f"https://{name}.com/careers",
            f"https://jobs.lever.co/{name}",
            f"https://boards.greenhouse.io/{name}",
            f"https://jobs.ashbyhq.com/{name}",
            f"https://jobs.smartrecruiters.com/{name}",
            f"https://{name}.jobs.personio.de/",
            f"https://{name}.wd1.myworkdayjobs.com/",
            f"https://{name}.wd3.myworkdayjobs.com/",
        ]
        for u in candidates:
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def ddg_careers_search(company: str, title: str = "") -> str | None:
    """Best-effort DuckDuckGo HTML search for company careers page."""
    q = f'{company} careers jobs site:jobs OR site:careers OR "workday" OR greenhouse OR smartrecruiters'
    if title:
        # also try title-specific later; first find careers hub
        pass
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    # extract uddg redirects
    hrefs = re.findall(r'uddg=([^&"]+)', html)
    decoded = []
    for h in hrefs:
        try:
            decoded.append(urllib.parse.unquote(h))
        except Exception:
            continue
    # also plain hrefs
    decoded += re.findall(r'href="(https?://[^"]+)"', html)
    scored: list[tuple[int, str]] = []
    for h in decoded:
        if is_board_url(h):
            continue
        if any(x in h.lower() for x in ("duckduckgo", "google.", "bing.", "youtube", "wikipedia")):
            continue
        score = 0
        low = h.lower()
        if re.search(r"career|karriere|jobs?\.|/jobs|/job/", low):
            score += 5
        if re.search(
            r"greenhouse|lever\.co|smartrecruiters|ashby|myworkday|personio|teamtailor|workable|icims",
            low,
        ):
            score += 8
        if re.search(r"careers\.|jobs\.", low):
            score += 3
        if score:
            scored.append((score, h.split("&")[0]))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else None


def resolve_careers_url(
    company: str,
    title: str = "",
    *,
    use_web: bool = True,
    probe: bool = False,
) -> tuple[str | None, str]:
    """Return (careers_url, source_note)."""
    if not (company or "").strip():
        return None, "no_company"

    cache = load_cache()
    key = _norm_company(company) or company.strip().lower()
    if key in cache and cache[key].get("url") and not is_board_url(cache[key]["url"]):
        return cache[key]["url"], f"cache:{cache[key].get('source', 'known')}"

    known = lookup_known(company)
    if known:
        cache[key] = {"url": known, "source": "map", "ts": time.time()}
        save_cache(cache)
        return known, "careers_map"

    # Heuristic probes (optional — can be slow)
    if probe:
        for u in heuristic_careers_urls(company)[:12]:
            if _http_ok(u):
                cache[key] = {"url": u, "source": "heuristic", "ts": time.time()}
                save_cache(cache)
                return u, "heuristic_ok"

    if use_web:
        found = ddg_careers_search(company, title)
        if found and not is_board_url(found):
            cache[key] = {"url": found, "source": "ddg", "ts": time.time()}
            save_cache(cache)
            return found, "duckduckgo"

    # Do NOT invent fake careers.company.com URLs without verification —
    # those 404 and waste apply budget. Require map, cache, or live web hit.
    return None, "unresolved"


def search_query_from_title(title: str) -> str:
    """Short search phrase for careers site search box."""
    t = (title or "").strip()
    # strip gender markers and noise: (m/f/x), (f/m/d), m/w/d, etc.
    t = re.sub(r"\([^)]*[mfwdix][^)]*\)", " ", t, flags=re.I)
    t = re.sub(r"\b[mfwd](?:/[mfwd]){1,3}\b", " ", t, flags=re.I)
    t = re.sub(r"\ball genders\b|\ball genders welcome\b", " ", t, flags=re.I)
    t = re.sub(r"[,;:]+", " ", t)
    t = re.sub(r"[^\w\s\+\.#\-/]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    # keep first ~6 meaningful tokens (drop pure punctuation leftovers)
    words = [w for w in t.split() if len(w) > 1 and re.search(r"[a-zA-Z]", w)][:8]
    return " ".join(words) if words else "software engineer"


def careers_search_url(careers_url: str, query: str) -> str:
    """Append common search query params when possible."""
    if not careers_url:
        return careers_url
    q = urllib.parse.quote(query)
    low = careers_url.lower()
    # already has query
    if "keywords=" in low or "q=" in low or "search=" in low or "query=" in low:
        return careers_url
    if "smartrecruiters.com" in low:
        sep = "&" if "?" in careers_url else "?"
        return f"{careers_url.rstrip('/')}{sep}search={q}"
    if "myworkdayjobs.com" in low:
        # Workday often needs path; leave hub
        return careers_url
    if "merckgroup.com" in low or "search-results" in low:
        sep = "&" if "?" in careers_url else "?"
        return f"{careers_url}{sep}keywords={q}"
    if "greenhouse.io" in low or "lever.co" in low or "ashbyhq.com" in low:
        sep = "&" if "?" in careers_url else "?"
        return f"{careers_url}{sep}q={q}" if "lever" not in low else careers_url
    # generic
    sep = "&" if "?" in careers_url else "?"
    return f"{careers_url}{sep}q={q}"


if __name__ == "__main__":
    import sys

    cos = sys.argv[1:] or ["Scalable GmbH", "Deutsche Bank", "Merck Healthcare", "P3 Group"]
    for c in cos:
        u, src = resolve_careers_url(c, use_web=True, probe=False)
        print(f"{c:30} → {u}  ({src})")
