#!/usr/bin/env python3
"""Company job-application secrets in Apple Keychain (macOS).

Stores and reuses per-company login secrets so Workday / SuccessFactors /
portal credentials are not re-prompted and not kept only in plaintext env files.

Keychain layout (generic password items):
  service:  job-apps/<company-slug>[/<kind>]
  account:  username or email
  password: secret (password / token)
  comment:  human note (optional)

Examples:
  job-apps/sap                 → SAP SuccessFactors
  job-apps/criteo              → Criteo Workday
  job-apps/criteo/workday      → kind override
  job-apps/hensoldt            → HENSOLDT career portal

Usage:
  from keychain_secrets import get_company_secret, set_company_secret, list_company_secrets

  # Retrieve (may show macOS Keychain UI; never print the password)
  creds = get_company_secret("Criteo")
  # {"company": "Criteo", "username": "...", "password": "...", "service": "job-apps/criteo"}

  # Store (updates if exists)
  set_company_secret("Criteo", username="you@mail.com", password="…")

CLI:
  python3 keychain_secrets.py list
  python3 keychain_secrets.py get criteo          # prints username only unless --show
  python3 keychain_secrets.py set criteo --user u --password-env CRITEO_PW
  python3 keychain_secrets.py migrate-env         # copy credentials_local.env → Keychain

Security:
  - Never log or print password values by default.
  - Prefer the user login keychain. If access fails, call with ask_sudo=True
    and the helper will print a clear request for sudo (does not auto-sudo).
  - sudo is only for locked/system keychain edge cases; normal login keychain
    uses the macOS authorization prompt instead.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent
ENV_FILE = W / "credentials_local.env"
SERVICE_PREFIX = "job-apps"
KEYCHAIN = os.environ.get("JOB_APPS_KEYCHAIN", "").strip()  # empty = default search list


def company_slug(company: str) -> str:
    s = (company or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unknown"


def service_name(company: str, kind: str = "") -> str:
    slug = company_slug(company)
    kind = (kind or "").strip().lower().replace(" ", "-")
    if kind and kind not in ("login", "default", "password"):
        return f"{SERVICE_PREFIX}/{slug}/{kind}"
    return f"{SERVICE_PREFIX}/{slug}"


def _run_security(args: list[str], *, input_text: str | None = None) -> tuple[int, str, str]:
    cmd = ["security", *args]
    if KEYCHAIN:
        cmd.append(KEYCHAIN)
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)


def set_company_secret(
    company: str,
    *,
    username: str,
    password: str,
    kind: str = "",
    comment: str = "",
    update: bool = True,
) -> bool:
    """Store or update a company secret in Apple Keychain. Returns True on success."""
    if not username or not password:
        raise ValueError("username and password required")
    svc = service_name(company, kind)
    # -U updates if exists
    args = [
        "add-generic-password",
        "-U" if update else "",
        "-s",
        svc,
        "-a",
        username,
        "-w",
        password,
        "-l",
        f"Job apps: {company}" + (f" ({kind})" if kind else ""),
        "-D",
        "job application login",
    ]
    if comment:
        args.extend(["-j", comment[:200]])
    args = [a for a in args if a != ""]
    code, out, err = _run_security(args)
    if code == 0:
        return True
    # item exists without -U edge case
    if "already exists" in (err + out).lower():
        args2 = [
            "add-generic-password",
            "-U",
            "-s",
            svc,
            "-a",
            username,
            "-w",
            password,
            "-l",
            f"Job apps: {company}",
            "-D",
            "job application login",
        ]
        code2, _, err2 = _run_security(args2)
        return code2 == 0
    raise RuntimeError(f"keychain store failed for {svc}: {err or out}")


def get_company_secret(
    company: str,
    *,
    kind: str = "",
    ask_sudo: bool = False,
) -> dict | None:
    """Load company secret. Does not print the password.

    Returns dict with company, username, password, service — or None if missing.

    If Keychain access is denied, raises PermissionError with instructions.
    Set ask_sudo=True only after the user explicitly grants sudo permission;
    this still does NOT run sudo automatically — it raises with the exact command.
    """
    svc = service_name(company, kind)
    # Find account (username)
    code, out, err = _run_security(["find-generic-password", "-s", svc, "-g"])
    blob = out + "\n" + err
    if code != 0 or "could not be found" in blob.lower():
        # try kind-less / alternate
        if kind:
            return get_company_secret(company, kind="", ask_sudo=ask_sudo)
        return None

    # Parse account
    username = ""
    m = re.search(r'"acct"<blob>="([^"]*)"', blob)
    if m:
        username = m.group(1)
    if not username:
        m = re.search(r'"acct"<blob>=0x([0-9A-Fa-f]+)\s+', blob)
        if m:
            try:
                username = bytes.fromhex(m.group(1)).decode("utf-8", errors="replace")
            except Exception:
                username = ""

    # Password via -w (stdout only)
    code_w, pw, err_w = _run_security(["find-generic-password", "-s", svc, "-w"])
    if code_w != 0 or not pw:
        # access denied / locked
        if any(
            x in (err_w + err + blob).lower()
            for x in ("denied", "user interaction", "authorization", "authenticate")
        ):
            msg = (
                f"Keychain access denied for service '{svc}'.\n"
                "macOS may show a Keychain prompt — allow access for this terminal.\n"
            )
            if ask_sudo:
                msg += (
                    "You granted sudo permission. Run this in your terminal (enter password when asked):\n"
                    f"  sudo security find-generic-password -s '{svc}' -w\n"
                    "Then re-run the apply step. This helper does not auto-run sudo.\n"
                )
            else:
                msg += (
                    "If the item is in a locked keychain, say: "
                    "\"you may use sudo to retrieve job-apps keychain secrets\" "
                    "and re-try with ask_sudo=True.\n"
                )
            raise PermissionError(msg)
        return None

    return {
        "company": company,
        "username": username,
        "email": username if "@" in username else "",
        "password": pw,
        "service": svc,
        "kind": kind or "login",
    }


def delete_company_secret(company: str, *, kind: str = "") -> bool:
    svc = service_name(company, kind)
    code, _, err = _run_security(["delete-generic-password", "-s", svc])
    return code == 0


def list_company_secrets() -> list[dict]:
    """List job-apps/* items (service + account only — never passwords)."""
    code, out, err = _run_security(["dump-keychain"])
    text = out or err or ""
    items: list[dict] = []
    # Parse dump blocks — best-effort
    current: dict = {}
    for line in text.splitlines():
        if '0x00000007 <blob>="job-apps/' in line or 'svce"<blob>="job-apps/' in line:
            m = re.search(r'job-apps/[^"]+', line)
            if m:
                if current.get("service"):
                    items.append(current)
                current = {"service": m.group(0), "username": ""}
        if current.get("service") and '"acct"<blob>="' in line:
            m = re.search(r'"acct"<blob>="([^"]*)"', line)
            if m:
                current["username"] = m.group(1)
    if current.get("service"):
        items.append(current)

    # Prefer find via known companies from env migration map too
    # Dedupe
    seen = set()
    uniq = []
    for it in items:
        k = it.get("service")
        if k and k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq


def resolve_company_aliases(company: str) -> list[str]:
    """Possible keychain slugs / names for a company string from a job row."""
    c = (company or "").strip()
    if not c:
        return []
    aliases = [c, company_slug(c)]
    low = c.lower()
    # common ATS / employer aliases
    table = {
        "sap": ["sap", "SAP", "SAP SF", "SuccessFactors"],
        "criteo": ["criteo", "Criteo"],
        "hensoldt": ["hensoldt", "HENSOLDT"],
        "infineon": ["infineon", "Infineon", "Infineon Technologies AG"],
        "veeva": ["veeva", "Veeva", "Veeva Systems"],
        "cisco": ["cisco", "Cisco", "Technical Leader Cisco"],
        "amazon": ["amazon", "Amazon"],
        "google": ["google", "Google"],
        "microsoft": ["microsoft", "Microsoft"],
        "apple": ["apple", "Apple"],
        "nvidia": ["nvidia", "NVIDIA"],
        "workday": ["workday", "Workday"],
    }
    for slug, names in table.items():
        if any(n.lower() in low or low in n.lower() for n in names) or slug in company_slug(c):
            aliases.extend(names)
            aliases.append(slug)
    # unique preserve order
    out, seen = [], set()
    for a in aliases:
        k = a.lower()
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out


def get_secret_for_company(company: str, *, ask_sudo: bool = False) -> dict | None:
    """Try aliases until a keychain item is found."""
    for name in resolve_company_aliases(company):
        try:
            cred = get_company_secret(name, ask_sudo=ask_sudo)
        except PermissionError:
            raise
        if cred:
            cred["matched_as"] = name
            return cred
    return None


def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_credentials_merged(company: str = "", *, ask_sudo: bool = False) -> dict[str, str]:
    """Env file + Keychain for a company.

    Precedence: Keychain company secret > credentials_local.env keys.
    For SAP, maps SAP_SF_EMAIL / SAP_SF_PASSWORD.
    """
    env = load_env_file()
    out = dict(env)
    if company:
        try:
            kc = get_secret_for_company(company, ask_sudo=ask_sudo)
        except PermissionError:
            raise
        if kc:
            out["USERNAME"] = kc.get("username") or out.get("USERNAME", "")
            out["PASSWORD"] = kc.get("password") or ""
            if kc.get("email"):
                out["EMAIL"] = kc["email"]
            # SAP convention
            slug = company_slug(company)
            if slug in ("sap", "successfactors") or "sap" in company.lower():
                out["SAP_SF_EMAIL"] = kc.get("username") or kc.get("email") or out.get("SAP_SF_EMAIL", "")
                out["SAP_SF_PASSWORD"] = kc.get("password") or out.get("SAP_SF_PASSWORD", "")
            out["_keychain_service"] = kc.get("service", "")
            out["_from_keychain"] = "1"
    else:
        # global SAP from keychain if present
        try:
            kc = get_company_secret("sap", ask_sudo=ask_sudo)
        except PermissionError:
            kc = None
        if kc:
            out["SAP_SF_EMAIL"] = kc.get("username") or out.get("SAP_SF_EMAIL", "")
            out["SAP_SF_PASSWORD"] = kc.get("password") or out.get("SAP_SF_PASSWORD", "")
            out["_from_keychain"] = "1"
    return out


def migrate_env_to_keychain(*, dry_run: bool = False) -> list[str]:
    """Copy known pairs from credentials_local.env into Keychain."""
    env = load_env_file()
    migrated: list[str] = []
    # SAP
    email = env.get("SAP_SF_EMAIL") or env.get("SAP_EMAIL") or ""
    password = env.get("SAP_SF_PASSWORD") or env.get("SAP_PASSWORD") or ""
    if email and password:
        if not dry_run:
            set_company_secret(
                "SAP",
                username=email,
                password=password,
                comment="Migrated from credentials_local.env SAP_SF_*",
            )
        migrated.append("SAP (SAP_SF_EMAIL/PASSWORD)")
    # Generic COMPANY_USER / COMPANY_PASSWORD pattern
    for k, v in env.items():
        if k.endswith("_PASSWORD") and v:
            prefix = k[: -len("_PASSWORD")]
            user = env.get(f"{prefix}_EMAIL") or env.get(f"{prefix}_USER") or env.get(f"{prefix}_USERNAME") or ""
            if user and prefix not in ("SAP_SF", "SAP"):
                if not dry_run:
                    set_company_secret(
                        prefix.replace("_", " "),
                        username=user,
                        password=v,
                        comment=f"Migrated from credentials_local.env {prefix}_*",
                    )
                migrated.append(prefix)
    return migrated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Job-apps Apple Keychain secrets")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List job-apps/* keychain items (no passwords)")

    p_get = sub.add_parser("get", help="Get secret metadata for a company")
    p_get.add_argument("company")
    p_get.add_argument("--kind", default="")
    p_get.add_argument("--show", action="store_true", help="Also print password (dangerous)")
    p_get.add_argument(
        "--ask-sudo",
        action="store_true",
        help="If access denied, print sudo instructions (does not auto-run sudo)",
    )

    p_set = sub.add_parser("set", help="Store/update a company secret")
    p_set.add_argument("company")
    p_set.add_argument("--user", "--username", dest="username", required=True)
    p_set.add_argument("--password", default="", help="Prefer --password-env")
    p_set.add_argument("--password-env", default="", help="Env var holding password")
    p_set.add_argument("--kind", default="")
    p_set.add_argument("--comment", default="")

    p_del = sub.add_parser("delete", help="Delete a company secret")
    p_del.add_argument("company")
    p_del.add_argument("--kind", default="")

    p_mig = sub.add_parser("migrate-env", help="Copy credentials_local.env into Keychain")
    p_mig.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        items = list_company_secrets()
        if not items:
            print("(no job-apps/* items found in default keychain)")
            env = load_env_file()
            if env:
                print(f"credentials_local.env has keys: {', '.join(sorted(env))}")
                print("Run: python3 keychain_secrets.py migrate-env")
            return 0
        for it in items:
            print(f"{it.get('service',''):40}  account={it.get('username','')}")
        return 0

    if args.cmd == "get":
        try:
            cred = get_company_secret(args.company, kind=args.kind, ask_sudo=args.ask_sudo)
        except PermissionError as e:
            print(str(e), file=sys.stderr)
            return 2
        if not cred:
            print(f"not found: {service_name(args.company, args.kind)}", file=sys.stderr)
            return 1
        print(f"service:  {cred['service']}")
        print(f"username: {cred['username']}")
        if args.show:
            print(f"password: {cred['password']}")
        else:
            print("password: (hidden — pass --show to print)")
        return 0

    if args.cmd == "set":
        pw = args.password
        if args.password_env:
            pw = os.environ.get(args.password_env, "")
        if not pw:
            print("Provide --password or --password-env", file=sys.stderr)
            return 1
        set_company_secret(
            args.company,
            username=args.username,
            password=pw,
            kind=args.kind,
            comment=args.comment,
        )
        print(f"stored {service_name(args.company, args.kind)} account={args.username}")
        return 0

    if args.cmd == "delete":
        ok = delete_company_secret(args.company, kind=args.kind)
        print("deleted" if ok else "not found / failed")
        return 0 if ok else 1

    if args.cmd == "migrate-env":
        m = migrate_env_to_keychain(dry_run=args.dry_run)
        if not m:
            print("nothing to migrate")
            return 0
        for x in m:
            print(("would migrate: " if args.dry_run else "migrated: ") + x)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
