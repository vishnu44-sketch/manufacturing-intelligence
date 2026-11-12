"""The audit log (models.AuditLog): record() writes one line of who did what and when.

Written: sign-in, failed sign-in (the name tried, never the password) and sign-out; people added or changed
(which fields - never a password or its hash), switched on / off, their password reset (only the fact) and
their admin rights; a chat renamed, removed, restored or deleted; a question edited or asked again; memories
added or deleted; an Excel download; the MCP tools (run_sql with its SQL, the searches with their question).
Not written: page views and the questions themselves - the Question table already keeps every question.

record() never breaks the request: when the line cannot be written it logs a warning and goes on.
The Audit page (api.audit, staff only) reads the lines; nothing in the app changes or deletes them.
"""
import contextvars
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.db import connection, transaction

from .models import AuditLog

log = logging.getLogger(__name__)

TEXT_CHARS = 2000   # one text in the details (e.g. an MCP SQL) is cut to this
LIST_ITEMS = 50     # a list in the details (e.g. the question ids of a deleted chat) keeps at most this many
# a detail whose name has one of these is never written (a password, its hash, a key ...)
SECRET_WORDS = ("password", "hash", "secret", "token", "key", "authorization", "cookie", "session")
ACTION_WORDS = dict(AuditLog.ACTIONS)

# the address of the MCP caller: the MCP tools get no Django request, so mcp_server.RememberClientAddress
# sets it for each MCP request
mcp_client_ip = contextvars.ContextVar("mcp_client_ip", default=None)


def record(request, action, target="", *, user=None, username=None, **details):
    """Write one audit line - never raises. request = the Django request (who, ip, browser), or None for
    the MCP tools (no user; the ip of the MCP caller when known). user = who did it when the request has
    no signed-in user; username = the name to show without a user (a failed sign-in: the name tried).
    details = small facts about it; anything that looks like a secret is left out, long texts are cut."""
    try:
        if user is None and request is not None and getattr(request.user, "is_authenticated", False):
            user = request.user
        if username is None:
            username = user.get_username() if user is not None else ""
        if request is None and not connection.in_atomic_block:
            # a long-running MCP server has no request to close its database connection: a stale one
            # (e.g. after MySQL's idle timeout) is closed here, so the line is written on a fresh one
            connection.close_if_unusable_or_obsolete()
        with transaction.atomic():  # a failing write never spoils the request's own transaction
            AuditLog.objects.create(
                user=user if user is not None and user.pk else None, username=str(username)[:150],
                action=action, target=str(target)[:100], details=clean(details),
                ip_address=client_ip(request), user_agent=user_agent(request))
    except Exception as exc:  # the audit log must never break what the person did
        log.warning("The audit line %s %s could not be written: %s", action, target, exc)


def clean(value):
    """The details as small, plain JSON: secret-looking names left out, texts cut to TEXT_CHARS,
    lists to LIST_ITEMS, anything else as text."""
    if isinstance(value, dict):
        return {str(name): clean(item) for name, item in value.items()
                if not any(word in str(name).lower() for word in SECRET_WORDS)}
    if isinstance(value, (list, tuple, set)):
        return [clean(item) for item in list(value)[:LIST_ITEMS]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:TEXT_CHARS]


def client_ip(request):
    """The address the request came from (None when unknown). Behind the https proxy
    (DJANGO_BEHIND_HTTPS_PROXY) it is the last address the proxy added to X-Forwarded-For - the one a
    browser cannot fake; otherwise the direct address. For the MCP tools: the MCP caller's address."""
    if request is None:
        address = mcp_client_ip.get() or ""
    else:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) else ""
        address = forwarded.split(",")[-1].strip() if forwarded.strip() else request.META.get("REMOTE_ADDR", "")
    try:
        validate_ipv46_address(address)
    except ValidationError:
        return None
    return address


def user_agent(request):
    """The browser (or tool) that sent the request, cut to AuditLog.USER_AGENT_CHARS ('' for MCP)."""
    if request is None:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:AuditLog.USER_AGENT_CHARS]
