import pytest

from printmanager import create_app
from printmanager.db import add_user


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "test.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )
    with app.app_context():
        add_user("alice", "pw-alice")
        add_user("bob", "pw-bob")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class Session:
    """Test client wrapper that attaches the CSRF token to every POST."""

    def __init__(self, client):
        self.client = client

    def token(self):
        self.client.get("/login")
        with self.client.session_transaction() as s:
            return s["_csrf"]

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)

    def post(self, url, data=None, **kwargs):
        data = dict(data or {})
        data["_csrf"] = self.token()
        return self.client.post(url, data=data, **kwargs)

    def login(self, username="alice", password="pw-alice"):
        return self.post(
            "/login", data={"username": username, "password": password}
        )


@pytest.fixture
def auth(client):
    s = Session(client)
    s.login()
    return s


@pytest.fixture(autouse=True)
def _fresh_spoolman_cache():
    from printmanager import spoolman

    spoolman.clear_cache()
    yield
    spoolman.clear_cache()


@pytest.fixture
def spoolman_server():
    from fake_spoolman import FakeSpoolman, spool

    server = FakeSpoolman([
        spool(1, 4, "Black", "PLA", "000000", remaining=740),
        spool(2, 4, "Black", "PLA", "000000", remaining=100),   # same filament: merged
        spool(3, 7, "Black", "PLA", "000000", vendor="Other"),  # same look, other filament id: merged
        spool(4, 5, "Red", "PETG", "ff0000"),
        spool(5, 6, "Old", "PLA", "00ff00", archived=True),     # archived: skipped
        spool(6, 8, "Empty", "PLA", "0000ff", remaining=0),     # empty: skipped
        spool(7, 9, "Shelf", "PLA", "ffffff", location="Shed"), # other location
        spool(8, 10, "Rainbow", "PLA", "", multi_color_hexes="ff0000,00ff00"),
        spool(9, 11, "Weird", "PLA", "red;x"),                  # invalid hex: no colour
    ])
    yield server
    server.stop()
