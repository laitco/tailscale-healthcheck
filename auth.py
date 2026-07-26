"""Flask-Login wiring for the /admin UI. dbstore.users is the source of truth."""
from flask_login import LoginManager, UserMixin

import dbstore

login_manager = LoginManager()
login_manager.login_view = "admin.login_page"


class User(UserMixin):
    def __init__(self, user_id: int, username: str):
        self.id = str(user_id)
        self.username = username

    @staticmethod
    def from_row(row: dict):
        if not row:
            return None
        return User(row["id"], row["username"])


@login_manager.user_loader
def load_user(user_id: str):
    try:
        row = dbstore.get_user_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    return User.from_row(row)


def init_app(app):
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    login_manager.init_app(app)
