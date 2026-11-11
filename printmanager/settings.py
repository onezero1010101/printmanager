"""Settings page. Values saved here override the environment defaults."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db

bp = Blueprint("settings", __name__)

KEYS = (
    "SPOOLMAN_URL",
    "SPOOLMAN_LOCATION",
    "LOW_SPOOL_GRAMS",
    "BED_X",
    "BED_Y",
    "BED_Z",
    "BED_MARGIN",
)
DEFAULT_MARGIN = 5.0


def _positive(raw, high):
    """A number above 0 and at most `high`, or ValueError."""
    value = float(raw)
    if not 0 < value <= high:
        raise ValueError
    return value


def bed():
    """((x, y, z), margin) in mm, or None when no bed size is set."""
    try:
        dims = tuple(_positive(get_setting(k), 10000) for k in ("BED_X", "BED_Y", "BED_Z"))
    except (TypeError, ValueError):
        return None
    try:
        margin = float(get_setting("BED_MARGIN"))
        if not 0 <= margin <= 100:
            raise ValueError
    except (TypeError, ValueError):
        margin = DEFAULT_MARGIN
    return dims, margin


def get_setting(key):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return row["value"]
    return current_app.config.get(key, "") or ""


def low_spool_grams():
    """The "low" threshold in grams (falls back to 100 if the value is unusable)."""
    try:
        return max(0, min(int(float(get_setting("LOW_SPOOL_GRAMS"))), 100000))
    except (TypeError, ValueError):
        return 100


def spoolman_enabled():
    return bool(get_setting("SPOOLMAN_URL").strip())


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def index():
    from . import spoolman

    db = get_db()
    if request.method == "POST":
        if request.form.get("reset"):
            db.execute(
                f"DELETE FROM settings WHERE key IN ({','.join('?' * len(KEYS))})", KEYS
            )
            flash("Settings reset to the environment defaults.")
        else:
            url = request.form.get("spoolman_url", "").strip()[:300]
            if url and not url.lower().startswith(("http://", "https://")):
                flash("The Spoolman URL must start with http:// or https://")
                return redirect(url_for("settings.index"))
            # "any" is a saved empty location, so it beats an environment default.
            if request.form.get("location_mode") == "any":
                location = ""
            else:
                location = request.form.get("location", "").strip()[:100]
            raw_low = request.form.get("low_spool_grams", "").strip()
            try:
                low = int(raw_low) if raw_low else low_spool_grams()
                if not 0 <= low <= 100000:
                    raise ValueError
            except ValueError:
                flash("The low-stock level must be a whole number of grams from 0 to 100000.")
                return redirect(url_for("settings.index"))
            # Bed size: a field that isn't in the form is left as it was.
            bed_updates = []
            sizes = {}
            for key, field in (("BED_X", "bed_x"), ("BED_Y", "bed_y"), ("BED_Z", "bed_z")):
                raw = request.form.get(field)
                sizes[key] = get_setting(key) if raw is None else raw.strip()
                if raw is not None:
                    bed_updates.append((key, sizes[key]))
            filled = [v for v in sizes.values() if v]
            try:
                if filled:
                    if len(filled) != 3:
                        raise ValueError
                    for v in filled:
                        _positive(v, 10000)
                raw_margin = request.form.get("bed_margin")
                if raw_margin is not None:
                    raw_margin = raw_margin.strip()
                    margin_value = float(raw_margin) if raw_margin else DEFAULT_MARGIN
                    if not 0 <= margin_value <= 100:
                        raise ValueError
                    bed_updates.append(("BED_MARGIN", f"{margin_value:g}"))
                    if filled and 2 * margin_value >= min(float(sizes["BED_X"]), float(sizes["BED_Y"])):
                        raise ValueError
            except ValueError:
                flash(
                    "Bed size: enter all three sizes in mm (or leave all empty), and a margin "
                    "from 0 to 100 mm that is smaller than half the bed."
                )
                return redirect(url_for("settings.index"))
            bed_updates = [(k, f"{float(v):g}" if v and k != "BED_MARGIN" else v) for k, v in bed_updates]
            for key, value in (
                ("SPOOLMAN_URL", url),
                ("SPOOLMAN_LOCATION", location),
                ("LOW_SPOOL_GRAMS", str(low)),
                *bed_updates,
            ):
                db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            flash("Settings saved.")
        db.commit()
        spoolman.clear_cache()
        return redirect(url_for("settings.index"))

    url = get_setting("SPOOLMAN_URL")
    location = get_setting("SPOOLMAN_LOCATION")
    spools, error = spoolman.fetch_spools(url) if url.strip() else (None, "")
    options = spoolman.build_options(spools, location) if spools is not None else []
    return render_template(
        "settings.html",
        url=url,
        location=location,
        error=error,
        connected=spools is not None,
        locations=spoolman.locations(spools),
        option_count=len(options),
        low_grams=low_spool_grams(),
        bed_x=get_setting("BED_X"),
        bed_y=get_setting("BED_Y"),
        bed_z=get_setting("BED_Z"),
        bed_margin=get_setting("BED_MARGIN") or f"{DEFAULT_MARGIN:g}",
    )
