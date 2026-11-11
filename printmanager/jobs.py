from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .auth import login_required, safe_path
from .db import get_db, utcnow
from .files import COVER_ID_SQL, FIRST_MODEL_ID_SQL
from . import spoolman

bp = Blueprint("jobs", __name__)

# queued -> printing -> ready (printed, waiting to be picked up) -> history.
# "ready" is a finished job whose picked_up_at is still empty.
STAGE_SQL = (
    "CASE WHEN j.status = 'completed' AND j.picked_up_at IS NULL THEN 'ready'"
    " ELSE j.status END"
)

JOB_SELECT = f"""
SELECT j.*, i.name AS item_name, {COVER_ID_SQL} AS cover_id,
       {FIRST_MODEL_ID_SQL} AS first_model_id,
       i.preview_name AS preview_name, i.preview_file_id AS preview_file_id,
       u.username AS queued_by_name,
       {STAGE_SQL} AS stage
FROM print_jobs j
JOIN items i ON i.id = j.item_id
LEFT JOIN users u ON u.id = j.queued_by
"""

# action -> stages it can be applied from
ACTIONS = {
    "start": {"queued"},
    "complete": {"queued", "printing"},          # finished: now ready for pickup
    "complete_pickup": {"queued", "printing"},   # finished and collected: straight to history
    "requeue": {"printing"},                     # "Back to queue"
    "pickup": {"ready"},                         # collected: moves to history
    "unready": {"ready"},                        # "Back to printing"
}


@bp.get("/queue")
@login_required
def queue():
    rows = get_db().execute(
        JOB_SELECT + " WHERE j.status != 'completed' OR j.picked_up_at IS NULL"
        " ORDER BY j.queued_at, j.id"
    ).fetchall()
    printing = [r for r in rows if r["stage"] == "printing"]
    queued = [r for r in rows if r["stage"] == "queued"]
    ready = sorted((r for r in rows if r["stage"] == "ready"), key=lambda r: (r["completed_at"] or "", r["id"]))
    return render_template("queue.html", printing=printing, queued=queued, ready=ready)


@bp.get("/history")
@login_required
def history():
    jobs = get_db().execute(
        JOB_SELECT + " WHERE j.status = 'completed' AND j.picked_up_at IS NOT NULL"
        " ORDER BY j.completed_at DESC, j.id DESC LIMIT 200"
    ).fetchall()
    return render_template("history.html", jobs=jobs)


@bp.post("/items/<int:item_id>/queue")
@login_required
def add_to_queue(item_id):
    db = get_db()
    item = db.execute("SELECT id, name FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)

    back = safe_path(
        request.form.get("next"), url_for("inventory.item_detail", item_id=item_id)
    )
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    if not 1 <= quantity <= 999:
        flash("Quantity must be a whole number from 1 to 999.", "error")
        return redirect(back)

    # Optional: queue one STL/3MF of the item instead of the whole item.
    file_id, file_name = None, ""
    raw_file = request.form.get("file_id", "").strip()
    if raw_file:
        row = None
        if raw_file.isdigit():
            row = db.execute(
                "SELECT id, original_name FROM item_files"
                " WHERE id = ? AND item_id = ? AND kind = 'model'",
                (int(raw_file), item_id),
            ).fetchone()
        if row is None:
            flash("That file isn't a 3D model of this item.", "error")
            return redirect(back)
        file_id, file_name = row["id"], row["original_name"]

    filament = {"name": "", "material": "", "color": ""}
    option_id = request.form.get("filament", "").strip()
    if option_id:
        option, error = spoolman.resolve(option_id)
        if option is None:
            flash(f"{error} Nothing was added; pick a color again.", "error")
            return redirect(back)
        filament = option

    notes = request.form.get("notes", "").strip()[:500]
    db.execute(
        "INSERT INTO print_jobs (item_id, quantity, notes, queued_by, queued_at,"
        " file_id, file_name, filament_name, filament_material, filament_color)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, quantity, notes, g.user["id"], utcnow(), file_id, file_name,
         filament["name"], filament["material"], filament["color"]),
    )
    db.commit()
    what = f"{item['name']} ({file_name})" if file_name else item["name"]
    flash(f"Added {quantity} x {what} to the queue.", "success")
    return redirect(back)


@bp.post("/jobs/<int:job_id>/again")
@login_required
def print_again(job_id):
    """Queue a new job like a finished one. The finished job stays in History."""
    db = get_db()
    job = db.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    back = safe_path(request.form.get("next"), url_for("jobs.history"))
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    if not 1 <= quantity <= 999:
        flash("Quantity must be a whole number from 1 to 999.", "error")
        return redirect(back)
    db.execute(
        "INSERT INTO print_jobs (item_id, quantity, notes, queued_by, queued_at,"
        " file_id, file_name, filament_name, filament_material, filament_color)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job["item_id"], quantity, job["notes"], g.user["id"], utcnow(), job["file_id"],
         job["file_name"], job["filament_name"], job["filament_material"],
         job["filament_color"]),
    )
    db.commit()
    what = f"{job['item_name']} ({job['file_name']})" if job["file_name"] else job["item_name"]
    flash(f"Added {quantity} x {what} to the queue.", "success")
    return redirect(back)


@bp.post("/jobs/pickup")
@login_required
def pickup_many():
    """Pick up several ready jobs at once (the checkboxes on the Queue page)."""
    ids = []
    for raw in request.form.getlist("job"):
        if raw.isdigit() and int(raw) not in ids:
            ids.append(int(raw))
    back = safe_path(request.form.get("next"), url_for("jobs.queue"))
    if not ids:
        flash("Tick the jobs you've picked up first.", "error")
        return redirect(back)
    db = get_db()
    marks = ",".join("?" * len(ids))
    cur = db.execute(
        f"UPDATE print_jobs SET picked_up_at = ? WHERE id IN ({marks})"
        " AND status = 'completed' AND picked_up_at IS NULL",
        (utcnow(), *ids),
    )
    db.commit()
    if cur.rowcount:
        flash(f"Picked up {cur.rowcount} job{'s' if cur.rowcount != 1 else ''}.", "success")
    else:
        flash("Those jobs aren't waiting for pickup any more.", "error")
    return redirect(back)


@bp.post("/jobs/<int:job_id>/progress")
@login_required
def set_progress(job_id):
    """Mark some of a job's quantity done ("add"), or take some back ("undo")."""
    db = get_db()
    job = db.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    back = safe_path(request.form.get("next"), url_for("jobs.queue"))
    try:
        count = int(request.form.get("count", "1"))
    except ValueError:
        count = 0
    if job["status"] == "completed" or count < 1:
        flash("Enter a whole number of 1 or more.", "error")
        return redirect(back)

    if request.form.get("direction") == "undo":
        done = max(0, job["done_qty"] - count)
        db.execute("UPDATE print_jobs SET done_qty = ? WHERE id = ?", (done, job_id))
        db.commit()
        flash(f"{job['item_name']}: {done} of {job['quantity']} done.", "success")
        return redirect(back)

    left = job["quantity"] - job["done_qty"]
    if count > left:
        flash(f"Only {left} left to print on that job.", "error")
        return redirect(back)
    done = job["done_qty"] + count
    if done == job["quantity"]:
        now = utcnow()
        db.execute(
            "UPDATE print_jobs SET done_qty = ?, status = 'completed', completed_at = ?,"
            " started_at = ?, picked_up_at = NULL WHERE id = ?",
            (done, now, job["started_at"] or now, job_id),
        )
        flash(f"{job['item_name']}: all {done} done, ready for pickup.", "success")
    else:
        db.execute("UPDATE print_jobs SET done_qty = ? WHERE id = ?", (done, job_id))
        flash(f"{job['item_name']}: {done} of {job['quantity']} done.", "success")
    db.commit()
    return redirect(back)


@bp.post("/jobs/<int:job_id>/color")
@login_required
def set_color(job_id):
    db = get_db()
    job = db.execute("SELECT id FROM print_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    filament = {"name": "", "material": "", "color": ""}
    option_id = request.form.get("filament", "").strip()
    if option_id:
        option, error = spoolman.resolve(option_id)
        if option is None:
            flash(f"{error} The color wasn't changed.", "error")
            return redirect(safe_path(request.form.get("next"), url_for("jobs.queue")))
        filament = option
    db.execute(
        "UPDATE print_jobs SET filament_name = ?, filament_material = ?,"
        " filament_color = ? WHERE id = ?",
        (filament["name"], filament["material"], filament["color"], job_id),
    )
    db.commit()
    flash("Color updated.", "success")
    return redirect(safe_path(request.form.get("next"), url_for("jobs.queue")))


@bp.post("/jobs/<int:job_id>/<action>")
@login_required
def update_job(job_id, action):
    db = get_db()
    job = db.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if job is None or (action != "delete" and action not in ACTIONS):
        abort(404)
    back = safe_path(request.form.get("next"), url_for("jobs.queue"))
    name = job["item_name"]

    if action == "delete":
        db.execute("DELETE FROM print_jobs WHERE id = ?", (job_id,))
        db.commit()
        flash(f"Removed {job['quantity']} x {name} from the list.", "success")
        return redirect(back)
    if job["stage"] not in ACTIONS[action]:
        flash("That job can't be moved there from its current status.", "error")
        return redirect(back)

    now = utcnow()
    if action == "start":
        sql = ("status = 'printing', started_at = ?", (now,))
        message = f"{name}: now printing."
    elif action == "requeue":
        sql = ("status = 'queued', started_at = NULL", ())
        message = f"{name}: back in the queue."
    elif action in ("complete", "complete_pickup"):
        picked = now if action == "complete_pickup" else None
        sql = (
            "status = 'completed', started_at = ?, completed_at = ?, done_qty = ?,"
            " picked_up_at = ?",
            (job["started_at"] or now, now, job["quantity"], picked),
        )
        message = (
            f"{name}: done and picked up."
            if picked
            else f"{name}: done, ready for pickup."
        )
    elif action == "pickup":
        sql = ("picked_up_at = ?", (now,))
        message = f"{name}: picked up."
    else:  # unready: put it back to printing with the last copy still to do
        sql = (
            "status = 'printing', completed_at = NULL, picked_up_at = NULL, done_qty = ?",
            (max(0, job["quantity"] - 1),),
        )
        message = f"{name}: back to printing."
    db.execute(f"UPDATE print_jobs SET {sql[0]} WHERE id = ?", (*sql[1], job_id))
    db.commit()
    flash(message, "success")
    return redirect(back)
