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
        # Defaults for the Spoolman integration; the Settings page overrides them.
        SPOOLMAN_URL=os.environ.get("SPOOLMAN_URL", ""),
        SPOOLMAN_LOCATION=os.environ.get("SPOOLMAN_LOCATION", ""),
        # Spools with less than this many grams left are marked "low".
        LOW_SPOOL_GRAMS=os.environ.get("LOW_SPOOL_GRAMS", "100"),
        ZIP_MAX_UNCOMPRESSED_MB=int(os.environ.get("ZIP_MAX_UNCOMPRESSED_MB", "1000")),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get(
            "SECRET_KEY"
        ) or _load_or_create_secret(app.instance_path)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    from . import auth, db, files, inventory, jobs, settings, spools

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(inventory.bp)
    app.register_blueprint(jobs.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(spools.bp)

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

    @app.template_global()
    def filament_choices():
        """(options, error, enabled) for colour dropdowns; fetched once per request."""
        if "filament_choices" not in g:
            from . import spoolman
            from .settings import spoolman_enabled

            if spoolman_enabled():
                options, error = spoolman.load_options()
                g.filament_choices = (options, error, True)
            else:
                g.filament_choices = ([], "", False)
        return g.filament_choices

    @app.template_filter("swatch_css")
    def swatch_css(value):
        """CSS background for one or several hex colours (re-validated)."""
        from .spoolman import clean_colors

        colors = [c for c in clean_colors(value).split(",") if c]
        if not colors:
            return ""
        if len(colors) == 1:
            return "#" + colors[0]
        step = 100 / len(colors)
        stops = ", ".join(
            f"#{c} {i * step:.1f}% {(i + 1) * step:.1f}%" for i, c in enumerate(colors)
        )
        return f"linear-gradient(90deg, {stops})"

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handle_error(error):
        return render_template("error.html", error=error), error.code

    return app
