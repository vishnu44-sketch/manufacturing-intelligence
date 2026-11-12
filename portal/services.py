"""The app's shared work behind the JSON API (api.py): asking in a chat, editing a question, the
chat list, saved answers (no AI call), the Excel file, and the numbers of the Data and Documents
pages. Moved here from the old Django pages (views.py) when the website became the React app, so
every rule lives in one place."""
import datetime
import decimal
import io
from collections import Counter

from django.db.models import Count
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .lc import vectorstore
from .lc.memory import ChatHistory
from .models import Conversation, Question
from .rag import agent, store, warehouse
from .rag.sql_guard import GuardError, check_sql

HISTORY_PAGE_SIZE = 25
CHAT_SIZE = 20  # questions the Ask page shows of one chat (older ones of that chat: History)
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

# the Excel download when the saved SQL cannot run again
EXCEL_ERRORS = (GuardError, warehouse.QueryError, warehouse.WarehouseUnavailable)


def is_admin(user):
    return user.is_staff or user.is_superuser


# ------------------------------------------------------------------ asking
def question_problem(question, empty="Type a question first."):
    """Why this (stripped) question cannot be asked - '' when it is fine."""
    if not question:
        return empty
    if len(question) > agent.MAX_QUESTION_CHARS:
        return f"Please keep the question under {agent.MAX_QUESTION_CHARS} characters."
    return ""


def answer_in_chat(user, chat, question):
    """Ask one checked question in this chat (None = start a new chat with it) and save it there.
    Returns (the saved Question, the chat)."""
    context = ChatHistory.for_chat(chat) if chat else None  # follow-ups ("and for Sep?") see the chat so far
    return _put_in_chat(user, chat, agent.ask(question, user, context=context).question)


def answer_in_chat_streamed(user, chat, question):
    """answer_in_chat() for the streamed Ask page: a generator that yields the question's progress events
    (agent.ask_events: steps, pieces of the answer) and returns (the saved Question, the chat) - saved the same."""
    context = ChatHistory.for_chat(chat) if chat else None
    result = yield from agent.ask_events(question, user, context=context)
    return _put_in_chat(user, chat, result.question)


def _put_in_chat(user, chat, saved):
    """The just-saved question goes into its chat; None = a new chat is made with it. -> (saved, chat)."""
    if chat is None:  # a new chat is made with its first question
        chat = Conversation.objects.create(user=user, title=Conversation.title_from(saved.text),
                                           created_at=saved.created_at, updated_at=saved.created_at)
    else:
        chat.updated_at, chat.archived = saved.created_at, False  # asking again brings it back
        chat.save(update_fields=["updated_at", "archived"])
    Question.objects.filter(pk=saved.pk).update(conversation=chat)
    saved.conversation = chat
    return saved, chat


def editable_question(user, pk):
    """The user's own question with this id that was not edited yet and not in a deleted chat (else 'not found')."""
    return get_object_or_404(Question.objects.visible(), pk=pk, user=user, replaced_by__isnull=True)


def edit_question(user, old, text):
    """Edit an old question (like ChatGPT): the edited (checked) text is asked again and its new answer
    takes the old question's place in the chat. The old version is hidden from the chat but stays in
    History, marked "edited". Editing the chat's first question also retitles a chat that was not
    renamed. Returns (the new saved Question, its chat or None)."""
    chat = old.conversation if old.conversation and old.conversation.user_id == user.id else None
    context = ChatHistory.for_chat(chat, before=old) if chat else None  # the chat's memory before the edited question
    saved = agent.ask(text, user, context=context).question
    Question.objects.filter(pk=saved.pk).update(conversation=chat, chat_order=old.chat_order or old.created_at)
    Question.objects.filter(pk=old.pk).update(replaced_by=saved)
    saved.refresh_from_db()
    if chat is None:
        return saved, None
    first = chat.questions.filter(replaced_by__isnull=True).exclude(pk=saved.pk).order_by(
        Coalesce("chat_order", "created_at"), "pk").first()
    if (first is None or (old.chat_order or old.created_at) <= (first.chat_order or first.created_at)) \
            and chat.title == Conversation.title_from(old.text):  # the first question, title not renamed
        chat.title = Conversation.title_from(text)
    chat.updated_at, chat.archived = saved.created_at, False
    chat.save(update_fields=["title", "updated_at", "archived"])
    return saved, chat


def token_notice(saved):
    """'This question used 4,344 tokens (SQL 3,483 + answer 861) - openai/gpt-oss-120b' - shown
    once, right after the question was answered; '' when Groq reported no tokens."""
    if saved.total_tokens is None:
        return ""
    first = "route" if agent.from_documents(saved.sources) else "SQL"  # a document question wrote no SQL
    parts = [f"{label} {n:,}" for label, n in ((first, saved.sql_tokens), ("answer", saved.answer_tokens))
             if n is not None]
    text = f"This question used {saved.total_tokens:,} tokens ({' + '.join(parts)})"
    return f"{text} - {saved.model}" if saved.model else text


# ------------------------------------------------------------------ chats
def own_chat(user, chat_id):
    """The user's own chat with this id - anyone else's is 'not found' (also for admins: chats are private),
    and so is a deleted one."""
    return get_object_or_404(Conversation.objects.visible(), pk=chat_id, user=user)


def delete_chat(user, chat):
    """"Delete" on the Ask page: the chat and its questions are hidden everywhere for the user (chat list,
    removed chats, History, the chat memory, the API), but the rows are kept for the audit log (soft
    delete). Returns the question ids of the chat (edited-away versions too), oldest first."""
    ids = list(chat.questions.order_by("created_at", "pk").values_list("pk", flat=True))
    chat.deleted_at, chat.deleted_by = timezone.now(), user
    chat.save(update_fields=["deleted_at", "deleted_by"])
    return ids


def chat_questions(chat):
    """(shown, total) of one chat: its last CHAT_SIZE questions in chat order, oldest first, and how
    many it has. Edited-away versions are left out (an edited question sits at the old one's place)."""
    questions = chat.questions.filter(replaced_by__isnull=True).annotate(
        place=Coalesce("chat_order", "created_at")).order_by("-place", "-pk")
    return list(questions[:CHAT_SIZE])[::-1], questions.count()


def chat_groups(user, now=None):
    """The chat list: [{label, chats}] for Today / Yesterday / Previous 7 days / Older (India
    dates of each chat's last question), most recent first; removed chats are left out.
    Each chat has .n = its number of questions."""
    today = timezone.localtime(now or timezone.now()).date()
    groups = {label: [] for label in CHAT_GROUPS}
    chats = user.conversations.visible().filter(archived=False).annotate(n=Count("questions"))
    for chat in chats.order_by("-updated_at", "-pk"):  # newest first (Meta.ordering is ignored with Count)
        age = (today - timezone.localtime(chat.updated_at).date()).days
        label = ("Today" if age <= 0 else "Yesterday" if age == 1
                 else "Previous 7 days" if age <= 7 else "Older")
        groups[label].append(chat)
    return [{"label": label, "chats": chats} for label, chats in groups.items() if chats]


def removed_chats(user):
    """The user's removed (archived) chats, most recently used first, each with .n questions."""
    # an explicit order: Django ignores Meta.ordering in a query with a GROUP BY (the Count)
    return list(user.conversations.visible().filter(archived=True).annotate(n=Count("questions"))
                .order_by("-updated_at", "-pk"))


# ------------------------------------------------------------------ saved answers
def own_question(user, pk):
    """The saved question with this id, if it is the user's own and not in a deleted chat (an admin may
    open any - also one of a deleted chat, e.g. from the Audit page)."""
    saved = get_object_or_404(Question.objects.select_related("conversation"), pk=pk)
    if is_admin(user):
        return saved
    if saved.user_id != user.id or (saved.conversation is not None and saved.conversation.deleted_at is not None):
        raise Http404("Question not found")  # someone else's, or deleted: act as if it does not exist
    return saved


def saved_result(saved, load_rows):
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
            data = run_saved_sql(saved)
        except EXCEL_ERRORS as exc:
            rows_error = f"The rows could not be loaded again: {exc}"
        else:
            result.columns, result.rows, result.truncated = data["columns"], data["rows"], data["truncated"]
    return result, rows_error


def run_saved_sql(saved):
    """{columns, rows, truncated} of a saved question: its SQL is checked by the guard again
    and runs on the read-only connection (no AI call)."""
    return warehouse.run_select(check_sql(saved.sql))


# ------------------------------------------------------------------ the Excel download
def excel_bytes(saved, data):
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


# ------------------------------------------------------------------ Documents (staff)
def documents(source="", find="", question=""):
    """What the AI can read: every piece in the vector store (with a file and a text filter) and a
    test search that shows the pieces the AI would get for a question. Read-only: no AI call and
    nothing is written. The test search runs only when the store has pieces."""
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
            hits = vectorstore.search(question, top_k=agent.TOP_K)  # the same search the AI uses
        except Exception as exc:  # e.g. the embedding model cannot be loaded
            search_error = f"The test search did not work: {exc}"
        else:
            tables = sql_step_tables(question, hits)
    return {"total": len(pieces), "counts": sorted(Counter(p["source"] for p in pieces).items()),
            "pieces": shown, "hits": hits, "tables": tables, "search_error": search_error,
            "store_empty": agent.STORE_EMPTY, "store_error": store_error, "vector_db": store.describe()}


def sql_step_tables(question, hits):
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


# ------------------------------------------------------------------ Data (staff)
def table_kind(name):
    """(sort order, kind) of a table: main data first, then lookups, then the load history."""
    for order, (start, kind) in enumerate(TABLE_KINDS):
        if name.startswith(start):
            return order, kind
    return len(TABLE_KINDS), "Other"


def table_counts():
    """[{name, note, kind, rows}] of every ai_gold table, counted in one query."""
    names = sorted(warehouse.allowed_tables(), key=lambda name: (table_kind(name)[0], name))
    # the names come from information_schema (not from a person), so they are safe in the SQL
    sql = " UNION ALL ".join(f"SELECT '{name}', COUNT(*) FROM `{name}`" for name in names)
    counts = dict(warehouse.run_select(sql, max_rows=len(names))["rows"])
    return [{"name": name, "note": TABLE_NOTES.get(name, ""), "kind": table_kind(name)[1],
             "rows": counts.get(name, 0)} for name in names]


def data_dates(names):
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
