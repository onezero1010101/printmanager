"""Read filament colors from a Spoolman instance.

Only GET /api/v1/spool is used. Results are cached briefly, and a failure is
cached too, so a Spoolman that is down doesn't slow every page.
"""
import json
import re
import time
import urllib.request

from .settings import get_setting

CACHE_SECONDS = 30
FAILURE_SECONDS = 15
TIMEOUT = 3
MAX_BYTES = 20 * 1024 * 1024

_cache = {}  # url -> (expires_at, spools or None, error or "")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_HEX = re.compile(r"^[0-9a-fA-F]{6}$")


def clear_cache():
    _cache.clear()


def clean_hex(value):
    """A bare 6-digit hex color (no #), lowercase, or ''."""
    value = (value or "").strip().lstrip("#")
    return value.lower() if _HEX.match(value) else ""


def clean_colors(value):
    """Comma separated hex colors; invalid parts are dropped."""
    parts = [clean_hex(p) for p in (value or "").split(",")]
    return ",".join(p for p in parts if p)


def _filament_colors(filament):
    multi = filament.get("multi_color_hexes")
    if isinstance(multi, str) and multi.strip():
        colors = clean_colors(multi)
        if colors:
            return colors
    return clean_hex(filament.get("color_hex"))


def fetch_spools(url):
    """Return (spools, error). Never raises."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return None, "No Spoolman URL set."
    now = time.monotonic()
    hit = _cache.get(url)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    spools, error = None, ""
    try:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("The URL must start with http:// or https://")
        req = urllib.request.Request(
            url + "/api/v1/spool", headers={"Accept": "application/json"}
        )
        with _opener.open(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Response too large")
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError("Unexpected response from Spoolman")
        spools = [s for s in data if isinstance(s, dict)]
    except Exception as exc:  # network, HTTP, JSON: all mean "unavailable"
        error = f"Couldn't reach Spoolman ({exc.__class__.__name__})."
    ttl = CACHE_SECONDS if spools is not None else FAILURE_SECONDS
    _cache[url] = (now + ttl, spools, error)
    return spools, error


def locations(spools):
    found = {
        (s.get("location") or "").strip()
        for s in spools or []
        if not s.get("archived")
    }
    return sorted((x for x in found if x), key=str.lower)


def build_options(spools, location=""):
    """Color choices from usable spools.

    Spools are skipped when archived, empty, or in another location. Spools of
    the same material, name and color become one option, whose id is the
    lowest filament id.
    """
    location = (location or "").strip().lower()
    groups = {}
    for spool in spools or []:
        filament = spool.get("filament")
        if not isinstance(filament, dict) or spool.get("archived"):
            continue
        remaining = spool.get("remaining_weight")
        if isinstance(remaining, (int, float)) and remaining <= 0:
            continue
        if location and (spool.get("location") or "").strip().lower() != location:
            continue
        fid = filament.get("id")
        if not isinstance(fid, int):
            continue
        vendor = filament.get("vendor")
        vendor_name = vendor.get("name", "") if isinstance(vendor, dict) else ""
        name = str(filament.get("name") or "").strip()
        material = str(filament.get("material") or "").strip()
        colors = _filament_colors(filament)
        key = (material.lower(), name.lower(), colors)
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "id": fid, "name": name, "material": material,
                "color": colors, "vendor": vendor_name,
            }
        else:
            group["id"] = min(group["id"], fid)
    return sorted(
        groups.values(), key=lambda o: (o["material"].lower(), o["name"].lower(), o["id"])
    )


def load_options():
    """(options, error) using the saved settings."""
    spools, error = fetch_spools(get_setting("SPOOLMAN_URL"))
    if spools is None:
        return [], error
    return build_options(spools, get_setting("SPOOLMAN_LOCATION")), ""


def resolve(option_id):
    """Find the current option with this id. (option, error)."""
    options, error = load_options()
    if error:
        return None, error
    for opt in options:
        if str(opt["id"]) == str(option_id):
            return opt, ""
    return None, "That filament isn't available any more."


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_spool_rows(spools, location="", low_grams=100):
    """One row per non-archived spool for the Spools page."""
    location = (location or "").strip().lower()
    rows = []
    for spool in spools or []:
        filament = spool.get("filament")
        if not isinstance(filament, dict) or spool.get("archived"):
            continue
        if location and (spool.get("location") or "").strip().lower() != location:
            continue
        vendor = filament.get("vendor")
        remaining = _number(spool.get("remaining_weight"))
        initial = _number(spool.get("initial_weight")) or _number(filament.get("weight"))
        length_mm = _number(spool.get("remaining_length"))
        density, diameter = _number(filament.get("density")), _number(filament.get("diameter"))
        if length_mm is None and remaining is not None and density and diameter:
            # grams / (g per cm3) = cm3 = 1000 mm3; divided by the filament's cross-section
            length_mm = remaining / density * 1000 / (3.14159265 * (diameter / 2) ** 2)
        percent = None
        if remaining is not None and initial:
            percent = max(0, min(100, round(remaining / initial * 100)))
        rows.append({
            "id": spool.get("id"),
            "vendor": vendor.get("name", "") if isinstance(vendor, dict) else "",
            "name": str(filament.get("name") or "").strip(),
            "material": str(filament.get("material") or "").strip(),
            "color": _filament_colors(filament),
            "location": (spool.get("location") or "").strip(),
            "remaining_g": remaining,
            "initial_g": initial,
            "remaining_m": None if length_mm is None else length_mm / 1000,
            "percent": percent,
            "empty": remaining is not None and remaining <= 0,
            "low": remaining is not None and 0 < remaining < low_grams,
        })
    return rows
