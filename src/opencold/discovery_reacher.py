"""Email pattern guessing and verification with Reacher."""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Email pattern guessing with reacher verification
# ---------------------------------------------------------------------------

_REACHER_VERSION = "0.11.7"
_REACHER_BIN_DIR = Path(__file__).resolve().parents[2] / "vendor" / "bin"
_REACHER_BIN_NAME = "check_if_email_exists"

# Cache for reacher binary availability
_REACHER_BIN: str | None | bool = None  # None = unchecked, False = not found


def _reacher_target_triple() -> str | None:
    """Return the GitHub release target triple for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        # No arm64 macOS build — x86_64 works under Rosetta 2
        return "x86_64-apple-darwin"
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
    return None


def _download_reacher() -> str | None:
    """Download the check-if-email-exists binary into vendor/bin/."""
    triple = _reacher_target_triple()
    if not triple:
        return None
    url = (
        f"https://github.com/reacherhq/check-if-email-exists/releases/download/"
        f"v{_REACHER_VERSION}/check_if_email_exists-{triple}.tar.gz"
    )
    _REACHER_BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = _REACHER_BIN_DIR / _REACHER_BIN_NAME
    try:
        tar_path = _REACHER_BIN_DIR / f"reacher-{triple}.tar.gz"
        req = urllib.request.Request(url, headers={"User-Agent": "opencold/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tar_path, "wb") as f:
            f.write(resp.read())
        with tarfile.open(tar_path, "r:gz") as tar:
            # Security: only extract the expected binary name
            members = [m for m in tar.getmembers() if os.path.basename(m.name) == _REACHER_BIN_NAME]
            if not members:
                return None
            member = members[0]
            member.name = _REACHER_BIN_NAME  # flatten path
            tar.extract(member, path=_REACHER_BIN_DIR, filter="data")
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        tar_path.unlink(missing_ok=True)
        return str(dest)
    except Exception:
        return None


def _find_reacher_binary() -> str | None:
    """Find the check-if-email-exists binary: vendor/bin → PATH → auto-download."""
    global _REACHER_BIN
    if _REACHER_BIN is None:
        # 1. Check vendor/bin (bundled with project)
        vendor_path = _REACHER_BIN_DIR / _REACHER_BIN_NAME
        if vendor_path.is_file():
            _REACHER_BIN = str(vendor_path)
        else:
            # 2. Check PATH
            on_path = shutil.which("check_if_email_exists") or shutil.which("check-if-email-exists")
            if on_path:
                _REACHER_BIN = on_path
            else:
                # 3. Auto-download
                downloaded = _download_reacher()
                _REACHER_BIN = downloaded if downloaded else False
    return _REACHER_BIN if _REACHER_BIN else None


def _reacher_check(email: str, from_email: str = "noreply@opencold.dev") -> dict | None:
    """Call check-if-email-exists CLI to verify an email address.

    Returns the parsed JSON result, or None if the binary is unavailable or errors.
    """
    binary = _find_reacher_binary()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--from-email", from_email, email],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def _generate_email_patterns(first: str, last: str, domain: str) -> list[str]:
    """Generate common email address patterns from first/last name."""
    patterns = [
        f"{first}.{last}@{domain}",  # jane.smith@
        f"{first}@{domain}",  # jane@
        f"{first}{last}@{domain}",  # janesmith@
        f"{first[0]}{last}@{domain}",  # jsmith@
        f"{first}{last[0]}@{domain}",  # janes@
        f"{first[0]}.{last}@{domain}",  # j.smith@
        f"{last}.{first}@{domain}",  # smith.jane@
        f"{first}_{last}@{domain}",  # jane_smith@
        f"{first}-{last}@{domain}",  # jane-smith@
    ]
    return patterns


def _guess_email_from_name(name: str, domain: str) -> str | None:
    """Try multiple email patterns for a person and validate with reacher.

    Falls back to first.last@domain with MX-only check if reacher is not installed.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    first = parts[0].lower()
    last = parts[-1].lower()

    # Quick MX check first — no point trying patterns if domain doesn't accept mail
    try:
        from opencold.verifier import _check_mx

        if not _check_mx(domain):
            return None
    except Exception:
        pass

    # If reacher binary is available, try all patterns
    if _find_reacher_binary():
        candidates = _generate_email_patterns(first, last, domain)
        reacher_failed = False
        all_invalid = True
        for email in candidates:
            result = _reacher_check(email)
            if result is None:
                reacher_failed = True
                break  # binary failed, fall back
            reachable = result.get("is_reachable", "unknown")
            if reachable == "safe":
                return email
            if reachable == "risky":
                # Catch-all domains accept everything — return first.last as best guess
                smtp = result.get("smtp", {})
                if smtp.get("is_catch_all"):
                    return candidates[0]  # first.last@ is most common
                return email
            if reachable != "invalid":
                all_invalid = False
            # "invalid" or "unknown" — try next pattern
        if not reacher_failed:
            if all_invalid:
                # Reacher confirmed no pattern exists — person likely doesn't work here
                return None
            # Mix of unknown/invalid — domain might block SMTP probes
            # Don't guess — return None to avoid sending to bad addresses
            return None

    # No reacher binary — don't guess, email verification is required
    return None
