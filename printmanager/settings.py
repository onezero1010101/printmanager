"""Settings page. Values saved here override the environment defaults."""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db

bp = Blueprint("settings", __name__)

KEYS = ("SPOOLMAN_URL", "SPOOLMAN_LOCATION", "LOW_SPOOL_GRAMS")


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
            db.execute("DELETE FROM settings WHERE key IN (?, ?, ?)", KEYS)
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
            for key, value in (
                ("SPOOLMAN_URL", url),
                ("SPOOLMAN_LOCATION", location),
                ("LOW_SPOOL_GRAMS", str(low)),
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
    )
