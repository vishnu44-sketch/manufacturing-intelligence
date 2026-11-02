"""The portal pages. Every page needs a signed-in user."""
import datetime
import decimal
import io
from collections import Counter

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Conversation, Question
from .rag import agent, store, warehouse
from .rag.sql_guard import GuardError, check_sql
from .usage import ai_usage

HISTORY_PAGE_SIZE = 25
CHAT_SIZE = 20  # questions the Ask page shows of one chat (older ones of that chat: History)
JUST_ANSWERED = "ask_just_answered"  # session key: the question to show the token notice for, once
CHAT_GROUPS = ("Today", "Yesterday", "Previous 7 days", "Older")  # the chat list on the left

# example questions shown under the question box (a click fills the box)
EXAMPLES = [
    "Top 5 customers by invoice value in Aug 2026?",
    "What were net sales in each NOP sales month of FY 2026-27?",
    "How many sales orders are open and what is their value?",
    "What is the stock value as on 20-Sep-2026?",
]

# the Data page: what each ai_gold table holds, in plain words (a new table shows with its name only)
TABLE_NOTES = {
    "fact_invoice_lines": "Invoice lines and credit / debit note lines (sales)",
    "fact_sales_order_lines": "Sales order lines",
    "fact_stock_ledger": "Stock ledger = inventory: stock balances and movements (Inventory Audit Report)",
    "dim_calendar": "Calendar: one row per day, with its financial year and NOP sales month",
    "dim_customers": "Customers",
    "dim_fx_rates": "INR to JPY exchange rates, one per NOP sales month",
    "dim_products": "Products / items",
    "dim_sales_people": "Sales people",
    "dim_stock_movement_types": "Kinds of stock row (Purchase, COGS, transfer, balances ...)",
    "dim_tax_codes": "GST tax codes of the sales orders",
    "load_log": "Load history: one row per table for each data load",
}
TABLE_KINDS = (("fact_", "Main data"), ("dim_", "Lookup"), ("load_log", "Load history"))  # by name start


def _is_admin(user):
    return user.is_staff or user.is_superuser


@never_cache  # no stale 'Thinking...' snapshot when coming Back to this page
@login_required
def ask(request):
    """Ask NOP, like ChatGPT: the user's chats on the left, the open chat on the right.
    GET /ask/ opens his most recently used chat (or the empty new-chat screen when he has none);
    POST /ask/ starts a NEW chat with the question (the "New chat" screen and History's
    "Ask again" post here). An example link (?q=...) opens the new-chat screen with the box filled."""
    if request.method == "POST":
        return _ask_in_chat(request, None)
    if request.GET.get("q"):
        return redirect(f"{reverse('ask_new')}?{urlencode({'q': request.GET['q']})}")
    latest = request.user.conversations.filter(archived=False).first()
    if latest:
        return redirect("ask_chat", chat_id=latest.pk)
    return _chat_page(request, None)


@never_cache  # no stale 'Thinking...' snapshot when coming Back to this page
@login_required
def ask_new(request):
    """The empty "New chat" screen. The chat itself is only made with its first question,
    so pressing "New chat" never leaves empty chats behind."""
    return _chat_page(request, None, question=request.GET.get("q", "")[:agent.MAX_QUESTION_CHARS])


@never_cache  # no stale 'Thinking...' snapshot when coming Back to this page
@login_required
def ask_chat(request, chat_id):
    """One chat of the user (others: 404). GET shows it; POST adds a question to it. Asking works
    Post/Redirect/Get: the question is answered and saved, then the browser comes back to
    /ask/c/<chat>/#q-<id> - so a refresh never asks the AI again. Showing a chat never calls the
    AI; only its newest answer runs its saved SQL again (the rows table)."""
    chat = _own_chat(request, chat_id)
    if request.method == "POST":
        return _ask_in_chat(request, chat)
    return _chat_page(request, chat)


@login_required
@require_POST
def chat_rename(request, chat_id):
    """Give a chat its own title."""
    chat = _own_chat(request, chat_id)
    title = " ".join(request.POST.get("title", "").split())[:200]
    if title:
        chat.title = title
        chat.save(update_fields=["title"])
    else:
        messages.error(request, "A chat needs a title.")
    return redirect(_back_to(request, chat))


@login_required
@require_POST
def chat_remove(request, chat_id):
    """Remove a chat from the list (archived). Its questions stay in History; it can be restored."""
    chat = _own_chat(request, chat_id)
    chat.archived = True
    chat.save(update_fields=["archived"])
    messages.success(request, f'"{chat.title}" was removed from your chats - its questions are still in '
                              f'History, and "Removed chats" at the bottom of the list can bring it back.')
    return redirect(_back_to(request, chat, left=True))


@login_required
@require_POST
def chat_restore(request, chat_id):
    """Put a removed chat back into the list."""
    chat = _own_chat(request, chat_id)
    chat.archived = False
    chat.save(update_fields=["archived"])
    return redirect("ask_chat", chat_id=chat.pk)


@login_required
@require_POST
def chat_delete(request, chat_id):
    """Delete a chat for good: the chat AND its questions (they also disappear from History).
    The page asks "Are you sure?" first."""
    chat = _own_chat(request, chat_id)
    count = chat.questions.count()
    title, back = chat.title, _back_to(request, chat, left=True)
    chat.delete()  # its questions go with it (on_delete=CASCADE)
    messages.success(request, f'"{title}" was deleted with its {count} question{"s" if count != 1 else ""}.')
    return redirect(back)


@login_required
@require_POST
def question_edit(request, pk):
    """Edit an old question (like ChatGPT): the edited text is asked again and its new answer takes
    the old question's place in the chat. The old version is hidden from the chat but stays in
    History, marked "edited". Only the owner's own, not yet edited questions can be edited."""
    old = get_object_or_404(Question, pk=pk, user=request.user, replaced_by__isnull=True)
    chat = old.conversation if old.conversation and old.conversation.user_id == request.user.id else None
    text = request.POST.get("question", "").strip()
    back = f"{reverse('ask_chat', args=[chat.pk])}#q-{old.pk}" if chat else reverse("ask_result", args=[old.pk])
    if not text:
        messages.error(request, "Type the edited question first.")
        return redirect(back)
    if len(text) > agent.MAX_QUESTION_CHARS:
        messages.error(request, f"Please keep the question under {agent.MAX_QUESTION_CHARS} characters.")
        return redirect(back)
    context = _chat_context(chat, before=old) if chat else []
    saved = agent.ask(text, request.user, context=context).question
    Question.objects.filter(pk=saved.pk).update(conversation=chat, chat_order=old.chat_order or old.created_at)
    Question.objects.filter(pk=old.pk).update(replaced_by=saved)
    request.session[JUST_ANSWERED] = saved.pk  # one-time token notice, as for a new question
    if chat is None:
        return redirect("ask_result", pk=saved.pk)
    first = chat.questions.filter(replaced_by__isnull=True).exclude(pk=saved.pk).order_by(
        Coalesce("chat_order", "created_at"), "pk").first()
    if (first is None or (old.chat_order or old.created_at) <= (first.chat_order or first.created_at)) \
            and chat.title == Conversation.title_from(old.text):  # the first question, title not renamed
        chat.title = Conversation.title_from(text)
    chat.updated_at, chat.archived = saved.created_at, False
    chat.save(update_fields=["title", "updated_at", "archived"])
    return redirect(f"{reverse('ask_chat', args=[chat.pk])}#q-{saved.pk}")


@never_cache  # no stale 'Thinking...' snapshot when coming Back to this page
@login_required
def ask_result(request, pk):
    """One saved question - for its owner (or an admin): the answer, the full rows table, SQL and
    sources as saved. The rows come from running the saved SQL again through the guard and the
    read-only connection. The AI is NOT asked again, so refreshing this page costs no AI tokens."""
    saved = _own_question(request, pk)
    result, rows_error = _saved_result(saved, load_rows=True)
    own_chat = saved.conversation if saved.conversation and saved.conversation.user_id == request.user.id else None
    return _chat_page(request, own_chat, question=saved.text, single=result, rows_error=rows_error)


def _ask_in_chat(request, chat):
    """Answer a posted question in this chat (None = start a new chat with it), then redirect to it."""
    question = request.POST.get("question", "").strip()
    if not question:
        messages.error(request, "Type a question first.")
    elif len(question) > agent.MAX_QUESTION_CHARS:
        messages.error(request, f"Please keep the question under {agent.MAX_QUESTION_CHARS} characters.")
    else:
        context = _chat_context(chat) if chat else []  # follow-ups ("and for Sep?") see the chat so far
        saved = agent.ask(question, request.user, context=context).question
        if chat is None:  # a new chat is made with its first question
            chat = Conversation.objects.create(user=request.user, title=Conversation.title_from(saved.text),
                                               created_at=saved.created_at, updated_at=saved.created_at)
        else:
            chat.updated_at, chat.archived = saved.created_at, False  # asking again brings it back
            chat.save(update_fields=["updated_at", "archived"])
        Question.objects.filter(pk=saved.pk).update(conversation=chat)
        request.session[JUST_ANSWERED] = saved.pk  # one-time token notice on the next view only
        return redirect(f"{reverse('ask_chat', args=[chat.pk])}#q-{saved.pk}")
    return _chat_page(request, chat, question=question[:agent.MAX_QUESTION_CHARS * 2])


def _chat_context(chat, before=None):
    """The chat's last answered questions (oldest first, at most agent.CONTEXT_SIZE) for a follow-up;
    with before=, only the ones placed before that question (an edit). Refused / failed questions
    and edited-away versions are left out."""
    questions = chat.questions.filter(replaced_by__isnull=True, status__in=("ok", "nodata")).annotate(
        place=Coalesce("chat_order", "created_at"))
    if before is not None:
        questions = questions.filter(place__lt=before.chat_order or before.created_at)
    return list(questions.order_by("-place", "-pk")[:agent.CONTEXT_SIZE])[::-1]


def _chat_page(request, chat, question="", single=None, rows_error=""):
    """The Ask page: chat list on the left; on the right the open chat (chat), one saved answer
    (single) or the empty new-chat screen, with the question box at the bottom."""
    just_answered = request.session.pop(JUST_ANSWERED, None)
    items, earlier, total = _chat_items(chat, just_answered) if chat and not single else ([], 0, 0)
    for item in items:
        if item["question"].pk == just_answered:
            item["token_notice"] = _token_notice(item["question"])
    # an explicit order: Django ignores Meta.ordering in a query with a GROUP BY (the Count)
    removed = list(request.user.conversations.filter(archived=True).annotate(n=Count("questions"))
                   .order_by("-updated_at", "-pk"))
    return render(request, "portal/ask.html", {
        "chat": chat, "items": items, "earlier": earlier, "total": total,
        "single": single, "rows_error": rows_error, "question": question, "examples": EXAMPLES,
        "chat_groups": _chat_groups(request.user), "removed": removed,
        "ask_action": reverse("ask_chat", args=[chat.pk]) if chat else reverse("ask"),
    })


def _chat_items(chat, just_answered=None):
    """(items, earlier, total) of one chat: its last CHAT_SIZE questions in chat order, oldest first;
    earlier = how many older questions of this chat are not shown (they are in History). Each item
    is {question, result, rows_error, rows_loaded, token_notice}. Edited-away versions are left out
    (an edited question sits at the old one's place - chat_order). Only the NEWEST answer, and the
    one just answered (e.g. after an edit), run their saved SQL again (the rows table); older
    answers show what was saved, so the page stays fast."""
    questions = chat.questions.filter(replaced_by__isnull=True).annotate(
        place=Coalesce("chat_order", "created_at")).order_by("-place", "-pk")
    total = questions.count()
    shown = list(questions[:CHAT_SIZE])[::-1]
    items = []
    for saved in shown:
        load = saved is shown[-1] or saved.pk == just_answered
        result, rows_error = _saved_result(saved, load_rows=load)
        items.append({"question": saved, "result": result, "rows_error": rows_error,
                      "rows_loaded": load and saved.status == "ok" and bool(saved.sql),
                      "token_notice": ""})
    return items, total - len(shown), total


def _chat_groups(user, now=None):
    """The chat list: [{label, chats}] for Today / Yesterday / Previous 7 days / Older (India
    dates of each chat's last question), most recent first; removed chats are left out.
    Each chat has .n = its number of questions."""
    today = timezone.localtime(now or timezone.now()).date()
    groups = {label: [] for label in CHAT_GROUPS}
    chats = user.conversations.filter(archived=False).annotate(n=Count("questions"))
    for chat in chats.order_by("-updated_at", "-pk"):  # newest first (Meta.ordering is ignored with Count)
        age = (today - timezone.localtime(chat.updated_at).date()).days
        label = ("Today" if age <= 0 else "Yesterday" if age == 1
                 else "Previous 7 days" if age <= 7 else "Older")
        groups[label].append(chat)
    return [{"label": label, "chats": chats} for label, chats in groups.items() if chats]


def _own_chat(request, chat_id):
    """The user's own chat with this id - anyone else's is 'not found' (also for admins: chats are private)."""
    return get_object_or_404(Conversation, pk=chat_id, user=request.user)


def _back_to(request, chat, left=False):
    """Where a chat-menu action returns to: the page it came from (a safe local 'next' address).
    When the chat leaves the list (removed / deleted) it never goes back into that chat: only to
    another chat or the new-chat screen, else to /ask/ (which opens the latest chat)."""
    target = request.POST.get("next", "")
    if not (target.startswith("/") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()})):
        target = ""
    this_chat = reverse("ask_chat", args=[chat.pk])
    if left:
        other_chat = target.startswith(reverse("ask_chat", args=[0])[:-2]) and not target.startswith(this_chat)
        return target if other_chat or target.startswith(reverse("ask_new")) else reverse("ask")
    return target or this_chat


def _token_notice(saved):
    """'This question used 4,344 tokens (SQL 3,483 + answer 861) - openai/gpt-oss-120b' - shown
    once, right after the question was answered; '' when Groq reported no tokens."""
    if saved.total_tokens is None:
        return ""
    parts = [f"{label} {n:,}" for label, n in (("SQL", saved.sql_tokens), ("answer", saved.answer_tokens))
             if n is not None]
    text = f"This question used {saved.total_tokens:,} tokens ({' + '.join(parts)})"
    return f"{text} - {saved.model}" if saved.model else text


def _saved_result(saved, load_rows):
    """(AskResult, rows_error) of a saved question - built from what was saved, no AI call.
    With load_rows, an answered question's SQL runs again (guard + read-only connection) for
    its rows table; rows_error says why the rows could not be loaded."""
    result = agent.AskResult(text=saved.text, status=saved.status, answer=saved.answer,
                             sql=saved.sql, secs=saved.secs or 0.0, tries=saved.tries,
                             sources=saved.sources, question=saved, model=saved.model,
                             sql_tokens=saved.sql_tokens, answer_tokens=saved.answer_tokens,
                             understood_as=saved.understood_as, step_secs=saved.step_secs or {})
    rows_error = ""
    if load_rows and saved.status == "ok" and saved.sql:
        try:
            data = _run_saved_sql(saved)
        except (GuardError, warehouse.QueryError, warehouse.WarehouseUnavailable) as exc:
            rows_error = f"The rows could not be loaded again: {exc}"
        else:
            result.columns, result.rows, result.truncated = data["columns"], data["rows"], data["truncated"]
    return result, rows_error


@login_required
def ask_excel(request, pk):
    """The rows of one saved question as an Excel file - for its owner (or an admin).
    The saved SQL runs again through the guard and the read-only connection."""
    saved = _own_question(request, pk)
    if saved.status != "ok" or not saved.sql:
        raise Http404("This question has no rows to download")
    try:
        data = _run_saved_sql(saved)
    except (GuardError, warehouse.QueryError, warehouse.WarehouseUnavailable) as exc:
        messages.error(request, f"The Excel file could not be made: {exc}")
        return redirect("history")
    response = HttpResponse(
        _excel_bytes(saved, data),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="ask_nop_{saved.pk}.xlsx"'
    return response


@login_required
def history(request):
    """The signed-in user's own past questions, newest first, 25 per page."""
    questions = request.user.questions.order_by("-created_at")
    page = Paginator(questions, HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "portal/history.html", {"page_obj": page, "questions": page.object_list,
                                                   "main_model": agent.model_name(),
                                                   "usage": ai_usage()})


@login_required
def users(request):
    """List of people who can sign in - staff and superusers only.
    Adding / changing people is done in Django admin."""
    if not _is_admin(request.user):
        return render(request, "portal/noaccess.html", status=403)
    people = get_user_model().objects.order_by("username")
    return render(request, "portal/users.html", {"people": people})


@login_required
def documents(request):
    """What the AI can read - staff and superusers only: every piece in the vector store (with a
    file and a text filter) and a test search that shows the pieces the AI would get for a
    question. Read-only: no AI call and nothing is written."""
    if not _is_admin(request.user):
        return render(request, "portal/noaccess.html", status=403)
    source = request.GET.get("source", "")
    find = request.GET.get("find", "").strip()
    question = request.GET.get("q", "").strip()[:agent.MAX_QUESTION_CHARS]

    try:
        pieces = store.all_pieces()
    except store.VectorStoreUnavailable as exc:  # e.g. the Qdrant server is not running
        pieces, store_error = [], str(exc)
    else:
        store_error = ""
    for number, piece in enumerate(pieces, start=1):  # the number stays the same when filtered
        piece["no"] = number
    shown = [p for p in pieces
             if (not source or p["source"] == source)
             and (not find or find.lower() in (p["heading"] + " " + p["text"]).lower())]

    hits, tables, search_error = [], None, ""
    if question and pieces:
        try:
            hits = store.search(question, top_k=agent.TOP_K)  # the same search the AI uses
        except Exception as exc:  # e.g. the embedding model cannot be loaded
            search_error = f"The test search did not work: {exc}"
        else:
            tables = _sql_step_tables(question, hits)
    return render(request, "portal/documents.html", {
        "total": len(pieces), "counts": sorted(Counter(p["source"] for p in pieces).items()),
        "pieces": shown, "source": source, "find": find, "question": question,
        "hits": hits, "tables": tables, "search_error": search_error,
        "store_empty": agent.STORE_EMPTY, "store_error": store_error,
        "vector_db": store.describe(),
    })


def _sql_step_tables(question, hits):
    """Which tables the SQL step would show with their columns for this question (the agent's own
    choice) - {"all": True} when it would show every table, None when MySQL cannot be read."""
    try:
        all_tables = warehouse.allowed_tables()
    except Exception:  # the page still works without MySQL; it just skips this line
        return None
    chosen = agent.tables_for_question(question, hits, all_tables)
    if chosen is None or chosen >= all_tables:
        return {"all": True, "names": sorted(all_tables)}
    return {"all": False, "names": sorted(chosen)}


@never_cache  # the counts are always the ones of this moment
@login_required
def data_tables(request):
    """How many records each table of the NOP data (MySQL ai_gold) has - staff and superusers only.
    Counted on every visit with the read-only user, so a new data load shows at once.
    Read-only: no AI call and nothing is written."""
    if not _is_admin(request.user):
        return render(request, "portal/noaccess.html", status=403)
    try:
        tables = _table_counts()
        dates = _data_dates({t["name"] for t in tables})
    except (warehouse.WarehouseUnavailable, warehouse.QueryError) as exc:  # e.g. MySQL is not running
        return render(request, "portal/data.html", {"mysql_error": str(exc)})
    total = sum(t["rows"] for t in tables)
    for t in tables:
        t["rows_text"] = f"{t['rows']:,}"
    return render(request, "portal/data.html", {
        "tables": tables, "table_count": len(tables), "total": f"{total:,}",
        "database": warehouse.database_name(), **dates,
    })


def _table_kind(name):
    """(sort order, kind) of a table: main data first, then lookups, then the load history."""
    for order, (start, kind) in enumerate(TABLE_KINDS):
        if name.startswith(start):
            return order, kind
    return len(TABLE_KINDS), "Other"


def _table_counts():
    """[{name, note, kind, rows}] of every ai_gold table, counted in one query."""
    names = sorted(warehouse.allowed_tables(), key=lambda name: (_table_kind(name)[0], name))
    # the names come from information_schema (not from a person), so they are safe in the SQL
    sql = " UNION ALL ".join(f"SELECT '{name}', COUNT(*) FROM `{name}`" for name in names)
    counts = dict(warehouse.run_select(sql, max_rows=len(names))["rows"])
    return [{"name": name, "note": TABLE_NOTES.get(name, ""), "kind": _table_kind(name)[1],
             "rows": counts.get(name, 0)} for name in names]


def _data_dates(names):
    """{invoices_from, invoices_to, last_load}: the first / last invoice date and when the data
    was last loaded (only the ones whose table is there)."""
    parts = []
    if "fact_invoice_lines" in names:
        parts += ["(SELECT MIN(invoice_date) FROM fact_invoice_lines) AS invoices_from",
                  "(SELECT MAX(invoice_date) FROM fact_invoice_lines) AS invoices_to"]
    if "load_log" in names:
        parts.append("(SELECT MAX(loaded_at) FROM load_log) AS last_load")
    if not parts:
        return {}
    result = warehouse.run_select("SELECT " + ", ".join(parts), max_rows=1)
    return dict(zip(result["columns"], result["rows"][0]))


def _own_question(request, pk):
    """The saved question with this id, if it is the user's own (an admin may open any)."""
    saved = get_object_or_404(Question, pk=pk)
    if saved.user_id != request.user.id and not _is_admin(request.user):
        raise Http404("Question not found")  # someone else's question: act as if it does not exist
    return saved


def _run_saved_sql(saved):
    """{columns, rows, truncated} of a saved question: its SQL is checked by the guard again
    and runs on the read-only connection (no AI call)."""
    return warehouse.run_select(check_sql(saved.sql))


def _excel_bytes(saved, data):
    """An .xlsx with two sheets: 'Result' (headers + rows) and 'Question' (what was asked)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="C00000")  # NOP red

    book = Workbook()
    sheet = book.active
    sheet.title = "Result"
    sheet.append(data["columns"])
    for cell in sheet[1]:
        cell.font, cell.fill = header_font, header_fill
    for row in data["rows"]:
        sheet.append([_excel_value(v) for v in row])
        for cell, value in zip(sheet[sheet.max_row], row):
            if isinstance(value, decimal.Decimal):  # keep the decimals MySQL gave, add separators
                places = max(0, -value.as_tuple().exponent) if value.is_finite() else 0
                cell.number_format = "#,##0" + ("." + "0" * places if places else "")
    for i, column in enumerate(data["columns"], start=1):  # a readable column width
        letter = sheet.cell(row=1, column=i).column_letter
        sheet.column_dimensions[letter].width = min(max(12, len(str(column)) + 4), 45)
    sheet.freeze_panes = "A2"

    info = book.create_sheet("Question")
    asked_at = timezone.localtime(saved.created_at).strftime("%d %b %Y %I:%M %p IST")
    for label, value in [("Question", saved.text), ("Answer", saved.answer), ("SQL", saved.sql),
                         ("Asked at", asked_at), ("Asked by", saved.user.get_username()),
                         ("Rows", len(data["rows"]))]:
        info.append([label, value])
    info.column_dimensions["A"].width = 12
    info.column_dimensions["B"].width = 100
    for row in info.iter_rows():
        row[0].font = Font(bold=True)
        row[1].alignment = Alignment(wrap_text=True, vertical="top")

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _excel_value(value):
    """Numbers, text and dates go into Excel as they are; anything else as text."""
    if value is None or isinstance(value, (int, float, decimal.Decimal, str,
                                           datetime.date, datetime.datetime)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
