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
