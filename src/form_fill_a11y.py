"""Accessibility / label-graph form filler (Playwright).

Builds a control→label map from:
  - aria-label / aria-labelledby
  - <label for=id>
  - nearest wrapping label / fieldset legend
  - placeholder + name/id as weak signals

Then assigns PROFILE / prefs values by scored keyword match.
Safer than name-only heuristics for React ATS widgets.
"""
from __future__ import annotations

import re
from typing import Any

from candidate_profile import PROFILE, pick_first_name, salary_for_field


# (value_key, patterns, score_weight)
# value_key resolved in _value_for()
_RULES: list[tuple[str, re.Pattern[str], int]] = [
    ("email", re.compile(r"e-?mail|correo|courriel", re.I), 100),
    ("phone", re.compile(r"phone|tel|mobile|handy|celular|telefon", re.I), 95),
    ("first", re.compile(r"first\s*name|vorname|pr[eé]nom|given\s*name|\bnombre\b(?!.*apellid)", re.I), 90),
    ("last", re.compile(r"last\s*name|surname|family\s*name|nachname|apellido|nom\s*de\s*famille", re.I), 90),
    ("full", re.compile(r"full\s*name|complete\s*name|your\s*name|^name$|nombre\s*completo", re.I), 70),
    ("street", re.compile(r"street|address\s*line\s*1|address1|strasse|straße|calle|adresse", re.I), 85),
    ("postal", re.compile(r"postal|zip|plz|post\s*code|c[oó]digo\s*postal", re.I), 85),
    ("city", re.compile(r"\bcity\b|\bort\b|\bville\b|\bstadt\b|town|wohnort|residence", re.I), 80),
    ("country", re.compile(r"country|land|pays|pa[ií]s|country\s*of\s*residence", re.I), 75),
    ("school", re.compile(r"school|university|college|uni|hochschule|universidad|école", re.I), 80),
    ("degree_year", re.compile(r"graduat|degree\s*year|year\s*(of\s*)?(grad|completion)|abschlussjahr", re.I), 75),
    ("gpa", re.compile(r"\bgpa\b|grade\s*point|notendurchschnitt", re.I), 70),
    ("title", re.compile(r"job\s*title|current\s*title|headline|professional\s*title|position", re.I), 70),
    ("salary", re.compile(r"salary|compensation|gehalt|expect|remunerat|pay|sueldo|salario|wunschgehalt", re.I), 85),
    ("linkedin", re.compile(r"linkedin|linked\s*in", re.I), 60),
    ("website", re.compile(r"website|portfolio|github|personal\s*site|url", re.I), 40),
    ("cover", re.compile(r"cover\s*letter|motivation|anschreiben|message|additional\s*info|why\s*(do\s*)?you", re.I), 55),
    ("gender_male", re.compile(r"gender|geschlecht|sexo|sexe|sex\b", re.I), 90),
    ("work_auth_yes", re.compile(r"authoriz|work\s*permit|right\s*to\s*work|eligible\s*to\s*work|arbeitserlaubnis", re.I), 90),
    ("sponsorship_no", re.compile(r"sponsor|visa\s*sponsor|need\s*sponsor", re.I), 90),
    ("veteran_no", re.compile(r"veteran|military|protected\s*veteran", re.I), 85),
    ("disability_no", re.compile(r"disabilit|handicap|behinderung", re.I), 85),
    ("race_white", re.compile(r"race|ethnicity|ethnic", re.I), 80),
]


def _value_for(key: str, field_hint: str = "") -> str | None:
    first = pick_first_name(field_hint)
    last = PROFILE["last"]
    if key == "email":
        return PROFILE["email"]
    if key == "phone":
        return PROFILE["phone"]
    if key == "first":
        return first
    if key == "last":
        return last
    if key == "full":
        return f"{first} {last}"
    if key == "street":
        return PROFILE.get("address_street") or "Street 1"
    if key == "postal":
        return PROFILE.get("address_postal") or "00000"
    if key == "city":
        return PROFILE.get("city") or "City"
    if key == "country":
        return PROFILE.get("country") or "Germany"
    if key == "school":
        return PROFILE.get("school") or "Universitat Politècnica de Catalunya"
    if key == "degree_year":
        return str(PROFILE.get("degree_year") or "2003")
    if key == "gpa":
        return PROFILE.get("gpa") or "2.6/4.0"
    if key == "title":
        return PROFILE.get("title") or "Telecommunications Engineer"
    if key == "salary":
        return salary_for_field(field_hint)
    if key == "cover":
        return (PROFILE.get("cover") or "")[:1500]
    if key == "linkedin":
        return ""  # leave empty unless known
    if key == "website":
        return ""
    # select-ish keys handled separately
    return None


def _score_label(text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for key, rx, weight in _RULES:
        if rx.search(text or ""):
            hits.append((weight, key))
    hits.sort(reverse=True)
    return hits


async def _control_label(page, el) -> str:
    """Best-effort human label for a control."""
    try:
        data = await el.evaluate(
            """(e) => {
              const parts = [];
              const push = (s) => { if (s && String(s).trim()) parts.push(String(s).trim()); };
              push(e.getAttribute('aria-label'));
              push(e.getAttribute('placeholder'));
              push(e.getAttribute('name'));
              push(e.getAttribute('id'));
              push(e.getAttribute('data-automation-id'));
              push(e.getAttribute('data-testid'));
              // aria-labelledby
              const lb = e.getAttribute('aria-labelledby');
              if (lb) {
                for (const id of lb.split(/\\s+/)) {
                  const n = document.getElementById(id);
                  if (n) push(n.innerText || n.textContent);
                }
              }
              // label[for=id]
              if (e.id) {
                const lab = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
                if (lab) push(lab.innerText || lab.textContent);
              }
              // wrapping label
              const wrap = e.closest('label');
              if (wrap) push(wrap.innerText || wrap.textContent);
              // fieldset legend
              const fs = e.closest('fieldset');
              if (fs) {
                const leg = fs.querySelector('legend');
                if (leg) push(leg.innerText || leg.textContent);
              }
              // previous sibling text
              let p = e.previousElementSibling;
              if (p && (p.tagName === 'LABEL' || p.tagName === 'SPAN' || p.tagName === 'DIV')) {
                push((p.innerText || p.textContent || '').slice(0, 120));
              }
              // parent text limited
              const parent = e.parentElement;
              if (parent) {
                const clone = parent.cloneNode(true);
                for (const c of clone.querySelectorAll('input,select,textarea,button')) c.remove();
                push((clone.innerText || '').slice(0, 160));
              }
              return parts.join(' | ').slice(0, 400);
            }"""
        )
        return data or ""
    except Exception:
        return ""


async def _select_best_option(el, key: str) -> bool:
    """Pick option for select-type fields by semantic key."""
    try:
        tag = (await el.evaluate("e => (e.tagName||'').toLowerCase()")).lower()
        if tag != "select":
            return False
        opts = await el.locator("option").all_inner_texts()
        want_patterns: list[re.Pattern[str]] = []
        if key == "gender_male":
            want_patterns = [re.compile(r"^(Male|Man|Männlich|Homme|Masculino)$", re.I)]
        elif key == "work_auth_yes":
            want_patterns = [re.compile(r"^(Yes|Ja|Oui|Sí|Si)\b", re.I), re.compile(r"authorized|eligible", re.I)]
        elif key == "sponsorship_no":
            want_patterns = [re.compile(r"^(No|Nein|Non)\b", re.I), re.compile(r"do not require|not require", re.I)]
        elif key == "veteran_no":
            want_patterns = [
                re.compile(r"I am not a protected veteran", re.I),
                re.compile(r"I am not a veteran", re.I),
                re.compile(r"not a protected veteran", re.I),
                re.compile(r"^No\b", re.I),
            ]
        elif key == "disability_no":
            want_patterns = [
                re.compile(r"do not have a disability", re.I),
                re.compile(r"No, I don'?t have a disability", re.I),
                re.compile(r"^No\b", re.I),
            ]
        elif key == "race_white":
            want_patterns = [
                re.compile(r"White \(Not Hispanic", re.I),
                re.compile(r"^White$", re.I),
                re.compile(r"Caucasian", re.I),
            ]
        elif key == "country":
            want_patterns = [
                re.compile(r"^Germany$", re.I),
                re.compile(r"Deutschland", re.I),
                re.compile(r"^DE$", re.I),
            ]
        for pat in want_patterns:
            for o in opts:
                ot = (o or "").strip()
                if not ot:
                    continue
                # Female trap
                if key == "gender_male" and re.search(r"female|woman", ot, re.I):
                    continue
                if pat.search(ot):
                    await el.select_option(label=o)
                    return True
    except Exception:
        return False
    return False


async def fill_a11y(page, log_fn=None, limit: int = 60) -> dict[str, Any]:
    """Fill form using accessibility/label graph. Returns metrics dict."""
    n_filled = 0
    n_total = 0
    n_file = 0
    n_file_set = 0
    details: list[str] = []

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    # Collect controls
    try:
        controls = page.locator(
            "input:visible, textarea:visible, select:visible"
        )
        n_total = min(await controls.count(), limit)
    except Exception as e:
        return {
            "fields_total": 0,
            "fields_filled": 0,
            "file_inputs": 0,
            "file_set": 0,
            "error": str(e),
            "details": [],
        }

    for i in range(n_total):
        el = controls.nth(i)
        try:
            typ = (await el.get_attribute("type") or "text").lower()
            tag = (await el.evaluate("e => (e.tagName||'').toLowerCase()")).lower()
            if typ in ("hidden", "submit", "button", "image", "reset"):
                continue
            if typ == "file":
                n_file += 1
                continue  # file handled by caller/upload helpers
            if typ in ("checkbox", "radio"):
                # leave to form_eeo / dedicated handlers for safety
                continue

            label = await _control_label(page, el)
            scores = _score_label(label)
            if not scores:
                continue
            _weight, key = scores[0]

            # Already filled?
            try:
                if tag in ("input", "textarea"):
                    cur = (await el.input_value()).strip()
                    if cur and len(cur) > 1:
                        continue
            except Exception:
                pass

            if key in (
                "gender_male",
                "work_auth_yes",
                "sponsorship_no",
                "veteran_no",
                "disability_no",
                "race_white",
                "country",
            ):
                if tag == "select" or typ == "select-one":
                    if await _select_best_option(el, key):
                        n_filled += 1
                        details.append(f"{key}←select ({label[:40]})")
                        _log(f"  a11y select {key}: {label[:50]}")
                continue

            val = _value_for(key, label)
            if not val:
                continue
            if tag == "select":
                # try match option containing value
                try:
                    opts = await el.locator("option").all_inner_texts()
                    for o in opts:
                        if val.lower() in (o or "").lower():
                            await el.select_option(label=o)
                            n_filled += 1
                            details.append(f"{key}←{o[:30]}")
                            break
                except Exception:
                    pass
                continue

            await el.fill(val, timeout=1200)
            n_filled += 1
            details.append(f"{key}←{val[:30]}")
            _log(f"  a11y fill {key}: {label[:40]}")
        except Exception:
            continue

    # EEO + residence helpers on top
    try:
        from form_eeo import fill_eeo

        n_filled += await fill_eeo(page, log_fn=log_fn)
    except Exception:
        pass
    try:
        from form_residence import fill_residence

        n_filled += await fill_residence(page, log_fn=log_fn)
    except Exception:
        pass
    try:
        from form_availability import fill_availability

        n_filled += await fill_availability(page, log_fn=log_fn)
    except Exception:
        pass

    return {
        "fields_total": n_total,
        "fields_filled": n_filled,
        "file_inputs": n_file,
        "file_set": n_file_set,
        "error": None,
        "details": details[:40],
    }
