"""Flask-Login wiring for the /admin UI. dbstore.users is the source of truth."""
from flask import jsonify, redirect, request, url_for
from flask_login import LoginManager, UserMixin

import dbstore

login_manager = LoginManager()
login_manager.login_view = "admin.login_page"


@login_manager.unauthorized_handler
def _unauthorized():
    """JSON 401 for /admin/api/* fetch calls, HTML redirect for page routes.

    Flask-Login's default behavior (redirect to login_view) makes sense for
    the HTML shell routes (settings/users/audit/profile pages - a browser
    navigation should land on the login page), but a `fetch()` call from the
    SPA to /admin/api/* would silently follow that redirect and see a 200
    HTML response instead of a 401, e.g. when a session expires, a user is
    deleted, or logout happens in another tab - leaving admin pages stuck
    instead of bouncing back to login.
    """
    if request.path.startswith("/admin/api/"):
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for("admin.login_page"))


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
