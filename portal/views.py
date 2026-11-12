"""The website is the React app (frontend/): this file serves its one page. Every address that is
not the API, the admin or a static file opens the same index.html, and the app shows the right
screen (its sign-in when the API says 401). The work itself is in api.py and services.py."""
from pathlib import Path

from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

# the React app's page, written by `npm run build` in frontend/
REACT_INDEX = Path(__file__).resolve().parent / "static" / "portal" / "app" / "index.html"


@require_safe  # GET / HEAD only: an old form post (e.g. to /ask/) is refused, never answered
@never_cache  # a new build shows at once
@ensure_csrf_cookie  # the React app reads this cookie for its POSTs (sign in, ask)
def react_app(request, rest=""):
    """The React app's index.html (at / and at each of its own addresses, e.g. /c/5 or /history).
    The page itself holds no data: everything comes from the JSON API after the sign-in."""
    try:
        html = REACT_INDEX.read_text(encoding="utf-8")
    except OSError:
        return HttpResponse(
            "<!doctype html><title>Manufacturing Intelligence</title>"
            "<p style='font-family:sans-serif;margin:40px'>The React app is not built yet. In the "
            "<code>frontend</code> folder run <code>npm install</code> and <code>npm run build</code>, "
            "then reload this page.</p>",
            status=503)
    return HttpResponse(html)
