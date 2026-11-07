from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .auth import login_required, safe_path
from .db import get_db, utcnow
from .files import COVER_ID_SQL, FIRST_MODEL_ID_SQL

bp = Blueprint("jobs", __name__)

JOB_SELECT = f"""
SELECT j.*, i.name AS item_name, {COVER_ID_SQL} AS cover_id,
       {FIRST_MODEL_ID_SQL} AS first_model_id,
       i.preview_name AS preview_name, i.preview_file_id AS preview_file_id,
       u.username AS queued_by_name
FROM print_jobs j
JOIN items i ON i.id = j.item_id
LEFT JOIN users u ON u.id = j.queued_by
"""

# action -> (statuses it can be applied from, resulting status)
TRANSITIONS = {
    "start": ({"queued"}, "printing"),
    "complete": ({"queued", "printing"}, "completed"),
    "requeue": ({"printing", "completed"}, "queued"),
}


@bp.get("/queue")
@login_required
def queue():
    rows = get_db().execute(
        JOB_SELECT + " WHERE j.status IN ('queued', 'printing')"
        " ORDER BY CASE j.status WHEN 'printing' THEN 0 ELSE 1 END, j.queued_at, j.id"
    ).fetchall()
    printing = [r for r in rows if r["status"] == "printing"]
    queued = [r for r in rows if r["status"] == "queued"]
    return render_template("queue.html", printing=printing, queued=queued)


@bp.get("/history")
@login_required
def history():
    jobs = get_db().execute(
        JOB_SELECT + " WHERE j.status = 'completed'"
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

    notes = request.form.get("notes", "").strip()[:500]
    db.execute(
        "INSERT INTO print_jobs (item_id, quantity, notes, queued_by, queued_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (item_id, quantity, notes, g.user["id"], utcnow()),
    )
    db.commit()
    flash(f"Added {quantity} x {item['name']} to the queue.", "success")
    return redirect(back)


@bp.post("/jobs/<int:job_id>/<action>")
@login_required
def update_job(job_id, action):
    db = get_db()
    job = db.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if job is None or (action != "delete" and action not in TRANSITIONS):
        abort(404)

    if action == "delete":
        db.execute("DELETE FROM print_jobs WHERE id = ?", (job_id,))
        db.commit()
        flash(f"Removed {job['quantity']} x {job['item_name']} from the list.", "success")
    else:
        allowed_from, new_status = TRANSITIONS[action]
        if job["status"] not in allowed_from:
            flash("That job can't be moved there from its current status.", "error")
        else:
            now = utcnow()
            if action == "start":
                started, completed = now, None
            elif action == "complete":
                started, completed = job["started_at"] or now, now
            else:
                started, completed = None, None
            db.execute(
                "UPDATE print_jobs SET status = ?, started_at = ?, completed_at = ?"
                " WHERE id = ?",
                (new_status, started, completed, job_id),
            )
            db.commit()
            flash(f"{job['item_name']}: now {new_status}.", "success")

    return redirect(safe_path(request.form.get("next"), url_for("jobs.queue")))
