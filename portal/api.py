"""The JSON API of the website (the React app in frontend/), under /api/.

The rules: a session sign-in (Django's own), a CSRF token on every POST (and any other changing
method), and a user only reaches his own chats, questions and memories (anyone else's are 'not found'; staff
as before: a chat is private, a saved question may be opened). Users, Documents and Data are for
staff only (403), and so is the Audit log (read-only: there is no way to change or delete a line).
Who did what is written to the audit log (audit.py): sign-ins, people, chat and memory actions, Excel
downloads - never a password. The Knowledge graph (every user, GET only) reads the NOP data live and
read-only, with no AI call (knowledge_graph.py); so does the Home page (home.py). It never answers with a redirect or an HTML page: without a
sign-in every endpoint says 401 in JSON. The work itself is in services.py. Never sent: the admin-only `error` details of a
question, and any password or password hash.
"""
import datetime
import functools
import json
import logging

from django import forms
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm, UsernameField
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.shortcuts import get_object_or_404
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import dateformat, timezone
from django.utils.text import Truncator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from . import audit, charts, home, knowledge_graph, services, user_memory
from .models import AuditLog, Question, UserMemory
from .rag import agent, warehouse
from .usage import ai_usage

log = logging.getLogger(__name__)

SIGN_IN_FAILED = "User ID and password did not match - please try again."
STAFF_ONLY = "Only administrators can open this page. If you need it, ask an administrator."
SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")
FIX_FIELDS = "Please correct the marked fields."


def _error(status, detail, **extra):
    """A JSON error the React app shows as it is: {"detail": "...", ...}."""
    return JsonResponse({"detail": detail, **extra}, status=status)


def _csrf_rejected(request):
    """True when this request has no valid CSRF token (the check Django's middleware makes for a page)."""
    return CsrfViewMiddleware(lambda r: None).process_view(request, None, (), {}) is not None


def api_view(methods, login_needed=True, staff_only=False):
    """Wrap an API view: only these HTTP methods (else 405), a signed-in user (else 401), staff when
    staff_only (else 403), a CSRF token on every changing method (else 403), and 'not found' as JSON
    404. All in JSON, never an HTML page or a redirect. The CSRF check is made here (not by the
    middleware) so a failure is JSON too."""
    def wrap(view):
        @functools.wraps(view)
        def checked(request, *args, **kwargs):
            if request.method not in methods:
                return _error(405, f"Use {' or '.join(methods)} here.")
            if login_needed and not request.user.is_authenticated:
                return _error(401, "Please sign in.")
            if staff_only and not services.is_admin(request.user):
                return _error(403, STAFF_ONLY)
            if request.method not in SAFE_METHODS and _csrf_rejected(request):
                return _error(403, "The CSRF token is missing or wrong - reload the page and try again.")
            try:
                return view(request, *args, **kwargs)
            except Http404:
                return _error(404, "Not found.")
        return csrf_exempt(never_cache(checked))
    return wrap


def _body(request):
    """The posted JSON object ({} when the body is empty); None when it is not a JSON object."""
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _format(moment, fmt):
    """A date or time as text in India time ('' for none); a date or a naive time stays as it is."""
    if not moment:
        return ""
    if hasattr(moment, "tzinfo") and timezone.is_aware(moment):
        moment = timezone.localtime(moment)
    return dateformat.format(moment, fmt)


def _when(moment):
    """'03 Nov 2026 10:15 AM' in India time, as the pages show it."""
    return _format(moment, "d M Y h:i A")


def _me(user):
    return {"username": user.get_username(), "name": user.get_full_name() or user.get_username(),
            "is_staff": services.is_admin(user)}


def _chat(chat, group=""):
    """One chat for the list / the chat header."""
    data = {"id": chat.pk, "title": chat.title, "archived": chat.archived,
            "created_at": timezone.localtime(chat.created_at).isoformat(), "created_text": _when(chat.created_at),
            "updated_at": timezone.localtime(chat.updated_at).isoformat(),
            "updated_text": _format(chat.updated_at, "d M, h:i A")}
    if group:
        data["group"] = group
    if hasattr(chat, "n"):
        data["questions"] = chat.n
    return data


def _card(saved, token_notice=""):
    """One saved question as an answer card, read from what was saved (no AI call, no SQL run: the
    rows come from /api/questions/<id>/rows). The SQL, the rows and the Excel link only for an
    answered data question; never the admin-only error details."""
    result, _ = services.saved_result(saved, load_rows=False)
    has_rows = saved.status == "ok" and bool(saved.sql)
    return {
        "id": saved.pk,
        "text": saved.text,
        "status": saved.status,
        "answer": saved.answer,
        "understood_as": saved.understood_as,
        "backup_model": saved.model if result.answered_by_backup else "",  # '' = the main model answered
        "token_notice": token_notice,  # only right after asking
        "time_steps": [{"label": s["label"], "secs": round(s["secs"], 3), "note": s["note"]}
                       for s in result.time_steps],
        "sql": saved.sql if has_rows else "",
        "sources": [{"kind": s.get("kind", ""), "heading": s.get("heading", "")}
                    for s in (saved.sources or []) if isinstance(s, dict)],
        "secs": result.secs,
        "tries": saved.tries,
        "row_count": saved.rows_count,
        "has_rows": has_rows,
        "rows_url": reverse("api_rows", args=[saved.pk]) if has_rows else "",
        "excel_url": reverse("api_excel", args=[saved.pk]) if has_rows else "",
        "created_at": timezone.localtime(saved.created_at).isoformat(),
        "created_text": _when(saved.created_at),
        "edited": saved.chat_order is not None,
    }


def _audit_memories(request, saved):
    """A question that said "Remember that ..." and saved a memory: one audit line for the new memory."""
    if saved.status == "memory":
        for memory in saved.memories.all():
            audit.record(request, "memory_added", f"memory {memory.pk}", text=memory.text, question=saved.pk)


def _answered(saved, chat):
    """The reply after a question was asked: its chat and its card with the one-time token notice."""
    return {"chat": _chat(chat) if chat else None, "card": _card(saved, services.token_notice(saved))}


# ------------------------------------------------------------------ sign in / out
@api_view(["GET"], login_needed=False)
def csrf(request):
    """Sets the CSRF cookie (the React app sends it back as X-CSRFToken on every POST)."""
    return JsonResponse({"csrfToken": get_token(request)})


@api_view(["POST"], login_needed=False)
def sign_in(request):
    """{username, password} -> the user (a session cookie is set), or 400 when they do not match."""
    data = _body(request)
    if data is None:
        return _error(400, "Send the sign-in as a JSON object.")
    username = str(data.get("username", "")).strip()
    user = authenticate(request, username=username, password=str(data.get("password", "")))
    if user is None:  # also for a user who is not active
        audit.record(request, "login_failed", username=username)  # the name tried - never the password
        return _error(400, SIGN_IN_FAILED)
    login(request, user)
    audit.record(request, "login_ok", f"user {user.pk}")
    return JsonResponse({**_me(user), "csrfToken": get_token(request)})  # sign-in gives a new CSRF token


@api_view(["POST"], login_needed=False)
def sign_out(request):
    """Ends the session (fine also when nobody was signed in)."""
    if request.user.is_authenticated:
        audit.record(request, "logout", f"user {request.user.pk}")
    logout(request)
    return JsonResponse({"ok": True})


@api_view(["GET"])
def me(request):
    """Who is signed in, plus what the Ask screen needs: the example questions and the length limit."""
    return JsonResponse({**_me(request.user), "examples": services.EXAMPLES,
                         "max_question_chars": agent.MAX_QUESTION_CHARS})


# ------------------------------------------------------------------ chats
@api_view(["GET"])
def chats(request):
    """The user's chats, most recently used first, each with its day group (Today, Yesterday ...),
    and apart from them the removed (archived) chats, also newest first."""
    return JsonResponse({
        "chats": [_chat(chat, group["label"])
                  for group in services.chat_groups(request.user) for chat in group["chats"]],
        "removed": [_chat(chat) for chat in services.removed_chats(request.user)],
    })


@api_view(["GET"])
def chat_detail(request, chat_id):
    """One own chat: its last questions in chat order (oldest first) as answer cards.
    earlier = how many older questions are not sent (they are in History)."""
    chat = services.own_chat(request.user, chat_id)
    shown, total = services.chat_questions(chat)
    return JsonResponse({"chat": _chat(chat), "total": total, "earlier": total - len(shown),
                         "cards": [_card(saved) for saved in shown]})


@api_view(["POST"])
def chat_rename(request, chat_id):
    """{title} -> the chat with its own title (spaces tidied, at most 200 characters)."""
    chat = services.own_chat(request.user, chat_id)
    data = _body(request)
    if data is None:
        return _error(400, "Send the title as a JSON object.")
    title = " ".join(str(data.get("title") or "").split())[:200]
    if not title:
        return _error(400, "A chat needs a title.")
    old_title, chat.title = chat.title, title
    chat.save(update_fields=["title"])
    audit.record(request, "chat_renamed", f"chat {chat.pk}", old_title=old_title, new_title=title)
    return JsonResponse({"chat": _chat(chat)})


@api_view(["POST"])
def chat_remove(request, chat_id):
    """Remove a chat from the list (archived). Its questions stay in History; it can be restored."""
    chat = services.own_chat(request.user, chat_id)
    chat.archived = True
    chat.save(update_fields=["archived"])
    audit.record(request, "chat_removed", f"chat {chat.pk}", title=chat.title)
    return JsonResponse({"chat": _chat(chat), "message": (
        f'"{chat.title}" was removed from your chats - its questions are still in History, and '
        f'"Removed chats" at the bottom of the list can bring it back.')})


@api_view(["POST"])
def chat_restore(request, chat_id):
    """Put a removed chat back into the list."""
    chat = services.own_chat(request.user, chat_id)
    chat.archived = False
    chat.save(update_fields=["archived"])
    audit.record(request, "chat_restored", f"chat {chat.pk}", title=chat.title)
    return JsonResponse({"chat": _chat(chat)})


@api_view(["POST"])
def chat_delete(request, chat_id):
    """Delete a chat: the chat AND its questions disappear for the user (also from History). The rows are
    kept for the audit log (soft delete, services.delete_chat); staff still open the questions from the
    Audit page. The app asks "Are you sure?" first."""
    chat = services.own_chat(request.user, chat_id)
    count, title = chat.questions.count(), chat.title
    ids = services.delete_chat(request.user, chat)
    audit.record(request, "chat_deleted", f"chat {chat.pk}", title=title, questions=count, question_ids=ids)
    return JsonResponse({"deleted": count, "message":
                         f'"{title}" was deleted with its {count} question{"s" if count != 1 else ""}.'})


# ------------------------------------------------------------------ asking
def _asked(request):
    """(question, chat, None) of a posted {question, chat_id}, or (None, None, the JSON error): 400 when the
    question is empty or too long, 404 for a chat that is not the user's own."""
    data = _body(request)
    if data is None:
        return None, None, _error(400, "Send the question as a JSON object.")
    question = str(data.get("question") or "").strip()
    chat_id = data.get("chat_id")
    if chat_id is not None and (isinstance(chat_id, bool) or not str(chat_id).isdigit()):
        return None, None, _error(400, "chat_id must be a chat number or null.")
    chat = services.own_chat(request.user, int(chat_id)) if chat_id is not None else None
    problem = services.question_problem(question)
    if problem:
        return None, None, _error(400, problem)
    return question, chat, None


@api_view(["POST"])
def ask(request):
    """{question, chat_id} -> asks it (chat_id null = a new chat) and returns the new answer card with
    its chat. 400 when the question is empty or too long; 404 for a chat that is not the user's own."""
    question, chat, refused = _asked(request)
    if refused:
        return refused
    saved, chat = services.answer_in_chat(request.user, chat, question)
    _audit_memories(request, saved)  # the question itself is in the Question table (its own audit trail)
    return JsonResponse(_answered(saved, chat))


STREAM_TYPE = "application/x-ndjson"  # one JSON object per line


@api_view(["POST"])
def ask_stream(request):
    """/api/ask streamed (the Ask page): the same sign-in, CSRF and checks (they still fail as a JSON error, before
    anything is sent) and the same saved question, but the reply is one JSON object per line while it runs:
        {"type": "step", "label": "Search the notes in Qdrant"}    a step starts
        {"type": "token", "text": "..."}                           a piece of the final answer as it is written
        {"type": "done", "chat": {...}, "card": {...}}              the same reply as /api/ask
        {"type": "error", "message": "..."}                         something failed outside the question itself
    A problem inside the question (the AI is busy, MySQL is down ...) is a saved question with a friendly answer:
    it comes as "done", as on /api/ask."""
    question, chat, refused = _asked(request)
    if refused:
        return refused
    response = StreamingHttpResponse(_ask_lines(request, chat, question), content_type=STREAM_TYPE)
    response["X-Accel-Buffering"] = "no"  # nginx and similar proxies: pass each line on at once
    return response


def _line(event):
    """One event as one line of JSON."""
    return (json.dumps(event) + "\n").encode("utf-8")


def _ask_lines(request, chat, question):
    """The lines of ask_stream. When the browser stops listening (closed, reloaded), the question still runs to
    the end and is saved - as on /api/ask - only nothing more is sent."""
    events = services.answer_in_chat_streamed(request.user, chat, question)
    gone = False
    while True:
        try:
            event = next(events)
        except StopIteration as finished:
            saved, chat = finished.value
            break
        except Exception:  # e.g. the History database failed while saving: the page shows a friendly message
            log.exception("Streamed question failed")
            if not gone:
                yield _line({"type": "error", "message": agent.UNEXPECTED})
            return
        if gone:
            continue
        try:
            yield _line(event)
        except GeneratorExit:  # the browser left: finish quietly (no more lines may be sent)
            gone = True
    _audit_memories(request, saved)
    if not gone:
        yield _line({"type": "done", **_answered(saved, chat)})


@api_view(["POST"])
def question_edit(request, pk):
    """{question} -> the edited question is asked again; its new card takes the old one's place in the
    chat (replaced = the old card's id). Only the owner's own, not yet edited questions (else 404)."""
    old = services.editable_question(request.user, pk)
    data = _body(request)
    if data is None:
        return _error(400, "Send the question as a JSON object.")
    text = str(data.get("question") or "").strip()
    problem = services.question_problem(text, empty="Type the edited question first.")
    if problem:
        return _error(400, problem)
    saved, chat = services.edit_question(request.user, old, text)
    audit.record(request, "question_edited", f"question {old.pk}", new_question=saved.pk,
                 chat=chat.pk if chat else None)
    _audit_memories(request, saved)
    return JsonResponse({**_answered(saved, chat), "replaced": old.pk})


@api_view(["POST"])
def question_again(request, pk):
    """History's "Ask again": one of the user's own questions is asked again in a new chat (as it was
    understood, for a follow-up such as "and for Sep?")."""
    old = get_object_or_404(Question.objects.visible(), pk=pk, user=request.user)
    question = (old.understood_as or old.text).strip()
    problem = services.question_problem(question)
    if problem:
        return _error(400, problem)
    saved, chat = services.answer_in_chat(request.user, None, question)
    audit.record(request, "ask_again", f"question {old.pk}", new_question=saved.pk, chat=chat.pk)
    _audit_memories(request, saved)
    return JsonResponse(_answered(saved, chat))


# ------------------------------------------------------------------ saved questions
@api_view(["GET"])
def question_detail(request, pk):
    """One saved answer (its owner, or staff for any): the card and its chat when it is the user's
    own (null otherwise). No AI call; the rows come from /rows."""
    saved = services.own_question(request.user, pk)
    chat = saved.conversation
    if chat is None or chat.user_id != request.user.id or chat.deleted_at is not None:
        chat = None  # someone else's chat (staff) or a deleted one: the answer alone
    return JsonResponse({"card": _card(saved), "chat": _chat(chat) if chat else None})


@api_view(["GET"])
def question_rows(request, pk):
    """The rows table of one answered question: its saved SQL runs again through the guard on the
    read-only connection (no AI call), formatted for the table. rows_error = why they could not be
    loaded. Own questions only (staff: any)."""
    saved = services.own_question(request.user, pk)
    if saved.status != "ok" or not saved.sql:
        return _error(404, "This question has no rows.")
    result, rows_error = services.saved_result(saved, load_rows=True)
    return JsonResponse({"headers": result.headers, "rows": result.table, "row_count": result.row_count,
                         "truncated": result.truncated, "rows_error": rows_error})


@api_view(["POST"])
def question_chart(request, pk):
    """A chart the app cannot draw itself (a sankey, a gauge ...), made by the AI from one answered question's rows:
    {"kind": "sankey diagram"} -> {option, tokens, model, recorded}. The rows run again exactly as for /rows; one AI
    call; the option is plain JSON checked by charts.check_option (never code). Own questions only (staff: any);
    a friendly JSON error when it cannot be made. See charts.py."""
    saved = services.own_question(request.user, pk)
    if saved.status != "ok" or not saved.sql:
        return _error(404, charts.NOT_ANSWERED)
    data = _body(request)
    if data is None:
        return _error(400, "Send a JSON object.")
    kind = str(data.get("kind") or "").strip()
    problem = charts.kind_problem(kind)
    if problem:
        return _error(400, problem)
    try:
        made = charts.make_chart(saved, kind)
    except charts.ChartError as exc:
        return _error(exc.status, str(exc))
    return JsonResponse({"option": made.option, "tokens": made.tokens, "model": made.model, "recorded": made.recorded})


@api_view(["GET"])
def question_excel(request, pk):
    """The rows of one saved question as an Excel file - for its owner (or staff). The saved SQL runs
    again through the guard on the read-only connection. 404 for a question without rows; 503 with
    the reason when MySQL cannot run it now."""
    saved = services.own_question(request.user, pk)
    if saved.status != "ok" or not saved.sql:
        return _error(404, "This question has no rows to download.")
    try:
        data = services.run_saved_sql(saved)
    except services.EXCEL_ERRORS as exc:
        return _error(503, f"The Excel file could not be made: {exc}")
    response = HttpResponse(
        services.excel_bytes(saved, data),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="ask_nop_{saved.pk}.xlsx"'
    audit.record(request, "excel_downloaded", f"question {saved.pk}", rows=len(data["rows"]))
    return response


# ------------------------------------------------------------------ History
def _usage():
    """The AI usage box (usage.ai_usage), with its times as text in India time."""
    usage = ai_usage()
    fmt = "D d-M g:i A"
    return {"rows": usage["rows"], "period_start": _format(usage["period_start"], fmt),
            "period_end": _format(usage["period_end"], fmt), "week_start": _format(usage["week_start"], fmt),
            "week_end": _format(usage["week_end"], fmt)}


def _history_row(saved, main_model):
    """One line of History."""
    has_rows = saved.status == "ok" and bool(saved.sql)
    return {
        "id": saved.pk,
        "created_text": _when(saved.created_at),
        "text": saved.text,
        "understood_as": saved.understood_as,
        "edited": saved.replaced_by_id is not None,  # replaced by a newer version
        "answer": Truncator(saved.answer).chars(140) if saved.answer else "",
        "rows_count": saved.rows_count,
        "secs_text": floatformat(saved.secs, 1) if saved.secs is not None else "-",
        "tokens_text": saved.total_tokens_text,
        "status": saved.status,
        "model": saved.model,
        "backup": bool(saved.model) and saved.model != main_model,
        "ask_again": saved.understood_as or saved.text,
        "excel_url": reverse("api_excel", args=[saved.pk]) if has_rows else "",
    }


@api_view(["GET"])
def history(request):
    """The signed-in user's own past questions, newest first, 25 per page (?page=2), plus the AI usage
    box of this app (all users). Staff also see only their own questions here. Questions of a deleted
    chat are left out (the usage box still counts their tokens: they were used)."""
    questions = request.user.questions.visible().order_by("-created_at")
    page = Paginator(questions, services.HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    main_model = agent.model_name()
    return JsonResponse({
        "questions": [_history_row(saved, main_model) for saved in page.object_list],
        "page": page.number, "pages": page.paginator.num_pages, "count": page.paginator.count,
        "has_previous": page.has_previous(), "has_next": page.has_next(),
        "usage": _usage(),
    })


# ------------------------------------------------------------------ Memory (every user, own memories only)
def _memory(memory):
    """One saved memory for the Memory page (question_id = the question that said "Remember ...", or null)."""
    return {"id": memory.pk, "text": memory.text, "question_id": memory.question_id,
            "created_at": timezone.localtime(memory.created_at).isoformat(), "created_text": _when(memory.created_at)}


@api_view(["GET", "POST"])
def memories(request):
    """GET: the user's own memories, newest first, with the limits. POST {text}: add one by hand - with the same
    limits as "Remember that ..." in a question (400 with the reason when it is too short / long, already
    remembered, or the memory is full)."""
    if request.method == "GET":
        return JsonResponse({"memories": [_memory(m) for m in request.user.memories.order_by("-created_at", "-pk")],
                             "limit": user_memory.MAX_MEMORIES, "max_chars": UserMemory.MAX_CHARS})
    data = _body(request)
    if data is None or not isinstance(data.get("text", ""), str):
        return _error(400, "Send the memory as a JSON object with its text.")
    text = data.get("text", "")
    fact = user_memory.memory_fact(text) or text  # "Remember that X" typed in the box: X is saved
    _, message, memory = user_memory.remember(request.user, fact)
    if memory is None:
        return _error(400, message)
    audit.record(request, "memory_added", f"memory {memory.pk}", text=memory.text)
    return JsonResponse({"memory": _memory(memory), "message": message})


@api_view(["POST"])
def memory_delete(request, memory_id):
    """Delete one of the user's own memories (anyone else's is 'not found')."""
    memory = get_object_or_404(UserMemory, pk=memory_id, user=request.user)
    text, number = memory.text, memory.pk
    memory.delete()
    audit.record(request, "memory_deleted", f"memory {number}", text=text)
    return JsonResponse({"deleted": 1, "message": f'Forgotten: "{text}".'})


@api_view(["POST"])
def memory_delete_all(request):
    """Delete all of the user's own memories (the app asks "Are you sure?" first)."""
    count, _ = request.user.memories.all().delete()
    if count:
        audit.record(request, "memory_delete_all", f"user {request.user.pk}", deleted=count)
    if not count:
        message = "There was nothing to delete."
    else:
        message = "Your 1 memory was deleted." if count == 1 else f"All {count} memories were deleted."
    return JsonResponse({"deleted": count, "message": message})


# ------------------------------------------------------------------ Documents and Data (staff)
@api_view(["GET"], staff_only=True)
def documents(request):
    """What the AI can read (?source=<file>&find=<word> filter the pieces; ?q=<question> runs the test
    search). Read-only: no AI call and nothing is written."""
    source = request.GET.get("source", "")
    find = request.GET.get("find", "").strip()
    question = request.GET.get("q", "").strip()[:agent.MAX_QUESTION_CHARS]
    found = services.documents(source, find, question)
    piece_fields = ("no", "id", "source", "kind", "heading", "text")
    return JsonResponse({
        **{key: found[key] for key in ("total", "tables", "search_error", "store_empty", "store_error", "vector_db")},
        "source": source, "find": find, "question": question,
        "counts": [{"source": name, "count": count} for name, count in found["counts"]],
        "pieces": [{key: piece.get(key, "") for key in piece_fields} for piece in found["pieces"]],
        "hits": [{"kind": hit.get("kind", ""), "score": hit.get("score"), "heading": hit.get("heading", ""),
                  "source": hit.get("source", ""), "text": hit.get("text", "")} for hit in found["hits"]],
    })


@api_view(["GET"], staff_only=True)
def data_tables(request):
    """How many records each table of the NOP data (MySQL ai_gold) has, counted now with the read-only
    user, plus the invoice dates and the last data load. mysql_error = why MySQL cannot be read now.
    Read-only: no AI call and nothing is written."""
    database = warehouse.database_name()
    try:
        tables = services.table_counts()
        dates = services.data_dates({t["name"] for t in tables})
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:  # e.g. MySQL is not running
        return JsonResponse({"database": database, "mysql_error": str(exc), "tables": [], "table_count": 0,
                             "total": "0", "invoices_from": "", "invoices_to": "", "last_load": ""})
    for table in tables:
        table["rows_text"] = f"{table['rows']:,}"
    return JsonResponse({
        "database": database, "mysql_error": "", "tables": tables, "table_count": len(tables),
        "total": f"{sum(t['rows'] for t in tables):,}",
        "invoices_from": _format(dates.get("invoices_from"), "d M Y"),
        "invoices_to": _format(dates.get("invoices_to"), "d M Y"),
        "last_load": _format(dates.get("last_load"), "d M Y h:i A"),
    })


# ------------------------------------------------------------------ Users (staff)
class PersonCreateForm(UserCreationForm):
    """A new person: the admin's own checks (unique sign-in name, the password rules of settings)."""

    class Meta(UserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email", "is_staff", "is_superuser")
        field_classes = {"username": UsernameField}


class PersonForm(forms.ModelForm):
    """The details of a person, with the same checks as the admin's change page."""

    class Meta:
        model = get_user_model()
        fields = ("username", "first_name", "last_name", "email", "is_staff", "is_superuser")
        field_classes = {"username": UsernameField}


def _person(user, me):
    """One person for the Users page - never the password or its hash."""
    return {"id": user.pk, "username": user.get_username(), "name": user.get_full_name() or user.get_username(),
            "first_name": user.first_name, "last_name": user.last_name, "email": user.email,
            "is_staff": user.is_staff, "is_superuser": user.is_superuser, "is_active": user.is_active,
            "last_login": _when(user.last_login), "is_me": user.pk == me.pk}


def _form_errors(form, rename=None):
    """{field: [messages]} of a form ('__all__' = not about one field), with field names renamed."""
    rename = rename or {}
    return {rename.get(field, field): [error["message"] for error in errors]
            for field, errors in form.errors.get_json_data().items()}


def _flag(data, name, current=False):
    """A yes/no field of the posted JSON (missing = the current value)."""
    value = data.get(name, current)
    return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")


def _change_problem(me, person, data):
    """Why `me` may not make this change to `person` ('' = fine). As in the admin a change needs the
    'change user' permission; on top: only a superuser changes a superuser or who is staff /
    superuser, and nobody switches off or demotes himself (so the site always keeps an admin)."""
    if not me.has_perm("auth.change_user"):
        return 403, "You do not have permission to change people - ask a superuser."
    if person.is_superuser and not me.is_superuser:
        return 403, "Only a superuser can change a superuser."
    roles_changed = (_flag(data, "is_staff", person.is_staff) != person.is_staff
                     or _flag(data, "is_superuser", person.is_superuser) != person.is_superuser)
    if roles_changed and not me.is_superuser:
        return 403, "Only a superuser can change who is staff or superuser."
    if person.pk == me.pk and (not _flag(data, "is_active", True) or roles_changed):
        return 400, "You cannot switch off your own account or take away your own admin rights."
    return 0, ""


@api_view(["GET", "POST"], staff_only=True)
def users(request):
    """GET: everyone who can sign in (and what the signed-in admin may change). POST {username,
    first_name, last_name, email, password1, password2, is_staff, is_superuser}: add a person -
    with the admin's 'add user' permission; staff / superuser only by a superuser."""
    admin = request.user
    if request.method == "GET":
        people = get_user_model().objects.order_by("username")
        return JsonResponse({"people": [_person(person, admin) for person in people],
                             "can_add": admin.has_perm("auth.add_user"),
                             "can_change": admin.has_perm("auth.change_user"),
                             "can_set_roles": admin.is_superuser,
                             "admin_url": reverse("admin:auth_user_changelist")})
    if not admin.has_perm("auth.add_user"):
        return _error(403, "You do not have permission to add people - ask a superuser.")
    data = _body(request)
    if data is None:
        return _error(400, "Send the person as a JSON object.")
    if (_flag(data, "is_staff") or _flag(data, "is_superuser")) and not admin.is_superuser:
        return _error(403, "Only a superuser can make someone staff or superuser.")
    form = PersonCreateForm(data={
        **{name: str(data.get(name) or "") for name in ("username", "first_name", "last_name", "email",
                                                        "password1", "password2")},
        "is_staff": _flag(data, "is_staff"), "is_superuser": _flag(data, "is_superuser")})
    if not form.is_valid():
        return _error(400, FIX_FIELDS, errors=_form_errors(form))
    person = form.save()
    audit.record(request, "user_created", f"user {person.pk}", person=person.get_username(),
                 is_staff=person.is_staff, is_superuser=person.is_superuser)
    return JsonResponse({"person": _person(person, admin), "message": f'"{person.get_username()}" can now sign in.'})


@api_view(["POST"], staff_only=True)
def user_detail(request, user_id):
    """{username, first_name, last_name, email, is_staff, is_superuser} -> the changed person
    (fields left out keep their value)."""
    person = get_object_or_404(get_user_model(), pk=user_id)
    data = _body(request)
    if data is None:
        return _error(400, "Send the person as a JSON object.")
    status, problem = _change_problem(request.user, person, data)
    if problem:
        return _error(status, problem)
    current = {"username": person.get_username(), "first_name": person.first_name,
               "last_name": person.last_name, "email": person.email}
    roles = {"is_staff": person.is_staff, "is_superuser": person.is_superuser}  # before the change
    form = PersonForm(instance=person, data={
        **{name: str(data.get(name, value) or "") for name, value in current.items()},
        "is_staff": _flag(data, "is_staff", person.is_staff),
        "is_superuser": _flag(data, "is_superuser", person.is_superuser)})
    if not form.is_valid():
        return _error(400, FIX_FIELDS, errors=_form_errors(form))
    changed = [name for name in form.changed_data if name not in roles]
    person = form.save()
    if changed:  # only the names of the fields (this form has no password field)
        audit.record(request, "user_changed", f"user {person.pk}", person=person.get_username(), fields=changed)
    new_roles = {"is_staff": person.is_staff, "is_superuser": person.is_superuser}
    if new_roles != roles:  # [before, after] of each right that changed
        audit.record(request, "user_roles_changed", f"user {person.pk}", person=person.get_username(),
                     **{name: [roles[name], new_roles[name]] for name in roles if roles[name] != new_roles[name]})
    return JsonResponse({"person": _person(person, request.user), "message": f'"{person.get_username()}" was saved.'})


@api_view(["POST"], staff_only=True)
def user_active(request, user_id):
    """{active: true / false} -> switch a person on or off (an off person cannot sign in)."""
    person = get_object_or_404(get_user_model(), pk=user_id)
    data = _body(request)
    if data is None or not isinstance(data.get("active"), bool):
        return _error(400, "Send {\"active\": true} or {\"active\": false}.")
    status, problem = _change_problem(request.user, person, {"is_active": data["active"]})
    if problem:
        return _error(status, problem)
    person.is_active = data["active"]
    person.save(update_fields=["is_active"])
    audit.record(request, "user_activated" if person.is_active else "user_deactivated", f"user {person.pk}",
                 person=person.get_username())
    state = "can sign in again" if person.is_active else "is switched off and cannot sign in"
    return JsonResponse({"person": _person(person, request.user), "message": f'"{person.get_username()}" {state}.'})


@api_view(["POST"], staff_only=True)
def user_password(request, user_id):
    """{password1, password2} -> a new password for a person, with the password rules of settings
    (as the admin's "Reset password"). Changing one's own keeps one signed in."""
    person = get_object_or_404(get_user_model(), pk=user_id)
    data = _body(request)
    if data is None:
        return _error(400, "Send the password as a JSON object.")
    status, problem = _change_problem(request.user, person, {})
    if problem:
        return _error(status, problem)
    form = SetPasswordForm(person, data={"new_password1": str(data.get("password1") or ""),
                                         "new_password2": str(data.get("password2") or "")})
    if not form.is_valid():
        return _error(400, FIX_FIELDS, errors=_form_errors(
            form, {"new_password1": "password1", "new_password2": "password2"}))
    form.save()
    audit.record(request, "password_reset", f"user {person.pk}", person=person.get_username(),
                 own=person.pk == request.user.pk)  # only the fact - never the password or its hash
    if person.pk == request.user.pk:
        update_session_auth_hash(request, person)
    return JsonResponse({"person": _person(person, request.user),
                         "message": f'The password of "{person.get_username()}" was changed.'})


# ------------------------------------------------------------------ Audit log (staff, read-only)
AUDIT_PAGE_SIZE = 50
SUMMARY_CHARS = 140  # the short details in the table (the whole details on a click)


def _audit_day(text, name):
    """A filter date 'YYYY-MM-DD' as a date (None when empty); ValueError with a plain message when wrong."""
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"The {name} date must look like 2026-11-03.") from None


def _audit_summary(details):
    """The details in one short line: 'title: Sales Aug; questions: 3'."""
    parts = []
    for name, value in details.items():
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        parts.append(f"{name.replace('_', ' ')}: {value}")
    return Truncator("; ".join(parts)).chars(SUMMARY_CHARS)


def _audit_questions(line):
    """The ids of the questions a line is about (each one opens as a saved answer - for staff also in a
    deleted chat): its target 'question 12', new_question, question and question_ids of the details."""
    ids = []
    if line.target.startswith("question "):
        ids.append(line.target.split(" ", 1)[1])
    details = line.details if isinstance(line.details, dict) else {}
    ids += [details.get("question"), details.get("new_question"), *(details.get("question_ids") or [])]
    found = []
    for value in ids:
        if str(value).isdigit() and int(value) not in found:
            found.append(int(value))
    return found


def _audit_line(line):
    """One line of the Audit page."""
    details = line.details if isinstance(line.details, dict) else {}
    return {"id": line.pk, "created_at": timezone.localtime(line.created_at).isoformat(),
            "created_text": _format(line.created_at, "d M Y h:i:s A"), "username": line.username,
            "user_id": line.user_id, "action": line.action,
            "action_text": audit.ACTION_WORDS.get(line.action, line.action), "target": line.target,
            "details": details, "summary": _audit_summary(details), "questions": _audit_questions(line),
            "ip": line.ip_address or "", "user_agent": line.user_agent}


@api_view(["GET"], staff_only=True)
def audit_log(request):
    """The audit log, newest first, AUDIT_PAGE_SIZE per page (?page=2), with filters: ?user=<part of a
    name>, ?action=<code>, ?from= / ?to=<YYYY-MM-DD, India dates, both included>, ?q=<a word in the target,
    the name, the details or the browser>. Plus every action code with its words (the filter list).
    Read-only: only GET - there is no way to add, change or delete a line through the API."""
    user = request.GET.get("user", "").strip()[:150]
    action = request.GET.get("action", "").strip()
    find = request.GET.get("q", "").strip()[:200]
    try:
        day_from = _audit_day(request.GET.get("from", "").strip(), "from")
        day_to = _audit_day(request.GET.get("to", "").strip(), "to")
    except ValueError as exc:
        return _error(400, str(exc))
    if action and action not in audit.ACTION_WORDS:
        return _error(400, "Unknown action.")
    lines = AuditLog.objects.order_by("-created_at", "-pk")
    if user:
        lines = lines.filter(username__icontains=user)
    if action:
        lines = lines.filter(action=action)
    zone = timezone.get_current_timezone()  # day limits in India time, worked out here (no SQL time zones)
    if day_from:
        lines = lines.filter(created_at__gte=datetime.datetime.combine(day_from, datetime.time.min, tzinfo=zone))
    if day_to:
        next_day = day_to + datetime.timedelta(days=1)
        lines = lines.filter(created_at__lt=datetime.datetime.combine(next_day, datetime.time.min, tzinfo=zone))
    if find:
        lines = lines.filter(Q(target__icontains=find) | Q(username__icontains=find) | Q(details__icontains=find)
                             | Q(user_agent__icontains=find) | Q(ip_address__icontains=find))
    page = Paginator(lines, AUDIT_PAGE_SIZE).get_page(request.GET.get("page"))
    return JsonResponse({
        "lines": [_audit_line(line) for line in page.object_list],
        "page": page.number, "pages": page.paginator.num_pages, "count": page.paginator.count,
        "has_previous": page.has_previous(), "has_next": page.has_next(),
        "actions": [{"code": code, "text": text} for code, text in AuditLog.ACTIONS],
        "filters": {"user": user, "action": action, "from": day_from.isoformat() if day_from else "",
                    "to": day_to.isoformat() if day_to else "", "q": find},
    })


# ------------------------------------------------------------------ Home (every user, read-only)
@api_view(["GET"])
def home_page(request):
    """The Home page in one reply (home.py): the KPI cards, the main tables, the connections and the user's own
    usage today. Read-only, no AI call. A part that cannot be read (e.g. MySQL is down) has its own error
    text and the rest still comes - never a 500. Only names and a status: no host, port, user name or key."""
    return JsonResponse(home.home(request.user))


# ------------------------------------------------------------------ Knowledge graph (every user, read-only)
def _graph_reply(make):
    """A knowledge-graph reply: 400 for a value it cannot use, 404 for an unknown node, 503 when MySQL cannot be
    read now (MySQL's own words go to the log, not to the page)."""
    try:
        return JsonResponse(make())
    except knowledge_graph.BadRequest as exc:
        return _error(400, str(exc))
    except knowledge_graph.NotFound as exc:
        return _error(404, str(exc))
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:
        log.warning("Knowledge graph: the NOP data could not be read: %s", exc)
        return _error(503, knowledge_graph.MYSQL_DOWN)


@api_view(["GET"])
def graph_search(request):
    """?q=aur&types=customer,product -> up to 20 matching nodes (2 characters or more) and how many in all (total);
    &offset=20&limit=10 -> the next ones in the same order ("Show more"; limit 1..10, never past the 50th)."""
    return _graph_reply(lambda: knowledge_graph.search(request.GET.get("q", ""), request.GET.get("types", ""),
                                                       request.GET.get("offset"), request.GET.get("limit")))


@api_view(["GET"])
def graph_node(request):
    """?type=customer&id=16&fy=2627&limit=25 -> the node, its totals in the period, its top neighbours and edges."""
    return _graph_reply(lambda: knowledge_graph.node(request.GET.get("type", ""), request.GET.get("id", ""),
                                                     request.GET.get("fy", ""), request.GET.get("limit")))


@api_view(["GET"])
def graph_similar(request):
    """?customer_id=16&fy=2627&limit=10 -> the customers who buy the most of the same products."""
    return _graph_reply(lambda: knowledge_graph.similar(request.GET.get("customer_id", ""), request.GET.get("fy", ""),
                                                        request.GET.get("limit")))


@csrf_exempt
def not_found(request, rest=""):
    """Any other address under /api/: 404 in JSON (never the React page or an HTML error)."""
    return _error(404, "Not found.")
