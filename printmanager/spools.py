"""Spools page: what is on the shelf, read from Spoolman."""
from flask import Blueprint, render_template, request

from . import spoolman
from .auth import login_required
from .settings import get_setting, low_spool_grams, spoolman_enabled

bp = Blueprint("spools", __name__)

SORTS = {
    "material": lambda r: (r["material"].lower(), r["name"].lower(), r["id"] or 0),
    "remaining": lambda r: (r["remaining_g"] is None, r["remaining_g"] or 0, r["name"].lower()),
    "name": lambda r: (r["name"].lower(), r["material"].lower(), r["id"] or 0),
}


@bp.get("/spools")
@login_required
def index():
    sort = request.args.get("sort", "material")
    if sort not in SORTS:
        sort = "material"
    enabled = spoolman_enabled()
    rows, error = [], ""
    low = low_spool_grams()
    if enabled:
        spools, error = spoolman.fetch_spools(get_setting("SPOOLMAN_URL"))
        if spools is not None:
            rows = spoolman.build_spool_rows(spools, get_setting("SPOOLMAN_LOCATION"), low)
    rows.sort(key=SORTS[sort])
    return render_template(
        "spools.html",
        rows=rows,
        sort=sort,
        enabled=enabled,
        error=error,
        low_grams=low,
        location=get_setting("SPOOLMAN_LOCATION"),
        low_count=sum(1 for r in rows if r["low"] or r["empty"]),
    )
