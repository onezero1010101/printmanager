import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, g, render_template, request, session

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def _load_or_create_secret(instance_path):
    path = Path(instance_path) / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    path.chmod(0o600)
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(app.instance_path, "printmanager.db")
        ),
        UPLOAD_FOLDER=os.environ.get(
            "UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")
        ),
        # Largest single upload request (STL files can be big). Set MAX_UPLOAD_MB to change.
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        APP_TIMEZONE=os.environ.get("APP_TIMEZONE", "America/New_York"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get(
            "SECRET_KEY"
        ) or _load_or_create_secret(app.instance_path)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import auth, db, files, inventory, jobs

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(jobs.bp)

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            token = session.get("_csrf")
            if not token or token != request.form.get("_csrf"):
                abort(400, "Your session expired. Reload the page and try again.")

    @app.context_processor
    def inject_globals():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        open_jobs = 0
        if g.get("user"):
            open_jobs = db.get_db().execute(
                "SELECT COUNT(*) FROM print_jobs WHERE status != 'completed'"
            ).fetchone()[0]
        return {"csrf_token": session["_csrf"], "open_jobs": open_jobs}

    @app.template_filter("localtime")
    def localtime(value):
        if not value:
            return ""
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        try:
            dt = dt.astimezone(ZoneInfo(app.config["APP_TIMEZONE"]))
        except Exception:
            pass  # fall back to UTC if the zone is unknown or tzdata is missing
        return dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handle_error(error):
        return render_template("error.html", error=error), error.code

    return app
