"""The Home page API (/api/home - home.py): sign-in, GET only, the shape of the reply, the KPI numbers only up to
today, a part that cannot be read (MySQL down) gives a partial reply and never a 500, no secret in the JSON, the
user's own usage numbers, the kept values, Qdrant only on our own collections, the KPI trends (whole NOP months
up to today) with their Ask-page questions, and the user's own recent questions.
MySQL and Qdrant are faked here (no server is needed); there is no AI call anywhere.
Run with:  python -m pytest -q portal/tests/test_home.py
"""
import datetime
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from portal import home
from portal.models import Question
from portal.rag import agent, store, warehouse
from portal.tests.test_views_ask import api_get, api_post

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 5)
COUNTS = {"dim_calendar": 1096, "dim_customers": 5001, "dim_products": 5001, "dim_sales_people": 31,
          "fact_invoice_lines": 100720, "fact_sales_order_lines": 101260, "fact_stock_ledger": 108246, "load_log": 18}
SECRETS = {  # every value here must never show in the reply
    "MYSQL_HOST": "db-secret-host.example", "MYSQL_PORT": "53306", "AI_DB_USER": "secret_reader_user",
    "AI_DB_PASSWORD": "Pw-Secret-123", "APP_DB_PASSWORD": "App-Pw-Secret-456",
    "GROQ_API_KEY": "gsk_secret_test_key_789", "QDRANT_URL": "http://qdrant-secret-host:6339",
    "QDRANT_API_KEY": "qdrant-secret-key-000",
}


class FakeMySQL:
    """Answers each fixed query of home.py by its words and keeps every (sql, params) it was given."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.data_from = datetime.date(2025, 12, 21)   # the first invoice date (as in the real data)
        self.stock = [[datetime.date(2026, 9, 20), Decimal("23856971.91"), 52]]
        # the top customer and product of the last complete NOP month (2.7% and 1.5% of its 1,200,000.00)
        self.top = [["customer", 101, "Allied Castings Limited", Decimal("32400.00")],
                    ["product", 202, "Coolant pump HM-445-1B", Decimal("18000.00")]]
        # the trend query: (NOP month, its last day, net sales, customers, products, FY running total), oldest first;
        # Jul 2026 had no sale (the LEFT JOIN gives 0)
        self.trend = [
            ["May 2026", datetime.date(2026, 5, 20), Decimal("5806675.00"), 14, 27, Decimal("11233965.00")],
            ["Jun 2026", datetime.date(2026, 6, 20), Decimal("12767485.00"), 20, 38, Decimal("24001450.00")],
            ["Jul 2026", datetime.date(2026, 7, 20), Decimal("0.00"), 0, 0, Decimal("24001450.00")],
            ["Aug 2026", datetime.date(2026, 8, 20), Decimal("7604315.00"), 20, 25, Decimal("31605765.00")],
            ["Sep 2026", datetime.date(2026, 9, 20), Decimal("1955500.00"), 8, 9, Decimal("33561265.00")],
            ["Oct 2026", datetime.date(2026, 10, 20), Decimal("2367096647.50"), 1434, 3263, Decimal("2400657912.50")],
        ]

    def _check(self):
        if self.down:
            raise warehouse.WarehouseUnavailable("Cannot connect to MySQL as secret_reader_user: (2003) refused")

    def params(self, sql, params=(), max_rows=500):
        self.calls.append((sql, tuple(params)))
        self._check()
        return {"columns": [], "rows": self.rows(sql), "truncated": False}

    def select(self, sql, max_rows=500):
        self.calls.append((sql, ()))
        self._check()
        if sql == "SELECT 1":
            return {"columns": ["1"], "rows": [[1]], "truncated": False}
        if "COUNT(*)" in sql and "UNION ALL" in sql:   # services.table_counts()
            return {"columns": ["name", "rows"], "rows": [[n, c] for n, c in COUNTS.items()], "truncated": False}
        raise AssertionError(f"unexpected SQL: {sql}")

    def tables(self):
        self._check()
        return set(COUNTS)

    def rows(self, sql):
        if "UNION ALL" in sql and "JOIN dim_customers cu" in sql:
            return self.top
        if "ORDER BY nop_sales_period_end DESC" in sql:
            return self.trend
        if "FROM dim_calendar t" in sql:
            return [[TODAY, "Nov 2026", datetime.date(2026, 10, 21), datetime.date(2026, 11, 20), "2627", "FY 2026-27",
                     "Oct 2026", datetime.date(2026, 9, 21), datetime.date(2026, 10, 20),
                     "Sep 2026", datetime.date(2026, 8, 21), datetime.date(2026, 9, 20), datetime.date(2026, 4, 1)]]
        if "FROM fact_invoice_lines f" in sql:
            # last month, the month before, FY so far, the same dates a year before, customers x2, products x2
            return [[Decimal("1200000.00"), Decimal("1000000.00"), Decimal("4360522752.50"), Decimal("1000.00"),
                     2063, 10, 3811, 5, self.data_from, 5000]]
        if "FROM fact_sales_order_lines s" in sql:
            return [[10, 14, Decimal("5335415.00"), Decimal("6059202.20")]]
        if "FROM fact_stock_ledger sl" in sql:
            return self.stock
        if sql.startswith("SELECT (SELECT MIN(invoice_date)"):
            return [[datetime.date(2025, 12, 21), datetime.date(2027, 3, 20),      # invoices
                     datetime.date(2024, 4, 2), datetime.date(2027, 3, 20),        # orders
                     datetime.date(2026, 9, 20), datetime.date(2027, 3, 20),       # stock
                     datetime.date(2024, 4, 1), datetime.date(2027, 3, 31),        # calendar
                     2, TODAY]]
        raise AssertionError(f"unexpected SQL: {sql}")


class FakeQdrant:
    """Our two collections with a few points; keeps the collection names it was asked about."""

    def __init__(self):
        self.asked = []
        self.points = {"mi_docs": 91, "mi_pdfs": 16}
        self.down = False

    def collection_exists(self, name):
        self.asked.append(name)
        if self.down:
            raise ConnectionError("refused")
        return name in self.points

    def count(self, name, exact=True):
        self.asked.append(name)
        return SimpleNamespace(count=self.points[name])


@pytest.fixture(autouse=True)
def fresh_cache():
    home.clear_cache()
    yield
    home.clear_cache()


@pytest.fixture
def mysql(monkeypatch):
    fake = FakeMySQL()
    monkeypatch.setattr(warehouse, "run_select_params", fake.params)
    monkeypatch.setattr(warehouse, "run_select", fake.select)
    monkeypatch.setattr(warehouse, "allowed_tables", fake.tables)
    return fake


@pytest.fixture
def qdrant(monkeypatch):
    fake = FakeQdrant()
    monkeypatch.setattr(store, "COLLECTION", "mi_docs")
    from portal.lc import pdfs
    monkeypatch.setattr(pdfs, "COLLECTION", "mi_pdfs")
    monkeypatch.setattr(store, "_client", lambda path=None: fake)
    return fake


def get_home(client):
    r = api_get(client, "api_home")
    assert r.status_code == 200
    return r.json()


def test_a_stranger_must_sign_in(client, mysql, qdrant):
    r = api_get(client, "api_home")
    assert r.status_code == 401
    assert r.json()["detail"] == "Please sign in."
    assert mysql.calls == [] and qdrant.asked == []   # nothing is read for a stranger


def test_get_only(client, user, mysql, qdrant):
    client.force_login(user)
    assert api_post(client, "api_home", {}).status_code == 405


def test_every_user_gets_the_whole_page(client, user, mysql, qdrant):
    user.first_name = "Asha"
    user.save()
    client.force_login(user)
    body = get_home(client)
    assert body["first_name"] == "Asha"
    assert body["calendar"] == {"today": "05-Nov-2026", "month": "Nov 2026", "month_from": "21-Oct-2026",
                                "month_to": "20-Nov-2026", "fy": "2627", "fy_label": "FY 2026-27"}
    cards = {card["key"]: card for card in body["kpis"]}
    assert list(cards) == ["month_sales", "fy_sales", "customers", "products", "open_orders", "stock",
                           "top_customer", "top_product"]
    assert cards["month_sales"]["label"] == "Net sales Oct 2026"
    assert cards["month_sales"]["text"] == "INR 1,200,000.00"
    assert cards["month_sales"]["note"].startswith("21-Sep-2026 to 20-Oct-2026")
    assert cards["month_sales"]["change"] == {"pct": 20.0, "direction": "up", "text": "20.0% vs Sep 2026"}
    assert cards["fy_sales"]["text"] == "INR 4,360,522,752.50" and cards["fy_sales"]["note"] == "01-Apr-2026 to 05-Nov-2026"
    assert cards["customers"]["text"] == "2,063" and "of 5,000 customers" in cards["customers"]["note"]
    assert cards["customers"]["total"] == 5000                  # all customers, for the ring on the card
    assert all("total" not in cards[key] for key in cards if key != "customers")
    assert cards["products"]["text"] == "3,811"
    assert cards["open_orders"]["text"] == "INR 5,335,415.00"
    assert "10 orders (14 lines)" in cards["open_orders"]["note"] and "05-Nov-2026" in cards["open_orders"]["note"]
    assert cards["stock"]["text"] == "INR 23,856,971.91" and "20-Sep-2026" in cards["stock"]["note"]
    assert body["kpi_error"] == "" and body["tables_error"] == "" and body["connections_error"] == ""
    tables = {t["table"]: t for t in body["tables"]}
    assert list(tables) == ["fact_invoice_lines", "fact_sales_order_lines", "fact_stock_ledger",
                            "dim_customers", "dim_products", "dim_calendar"]       # the main tables only
    assert tables["fact_invoice_lines"] == {
        "table": "fact_invoice_lines", "name": "Sales invoices", "note": "Invoice, credit and debit note lines",
        "rows": 100720, "rows_text": "100,720", "from": "21-Dec-2025", "to": "20-Mar-2027", "after_today": True}
    assert tables["fact_stock_ledger"]["note"].startswith("2 stock reports")
    assert tables["dim_customers"]["from"] == "" and tables["dim_customers"]["after_today"] is False
    lines = {line["key"]: line for line in body["connections"]}
    assert [lines[k]["name"] for k in ("ai_gold", "docs", "pdfs", "groq")] == [
        "MySQL ai_gold", "Qdrant mi_docs", "Qdrant mi_pdfs", "Groq AI"]
    assert all(lines[k]["ok"] for k in ("ai_gold", "app_db", "docs", "pdfs"))
    assert (lines["docs"]["note"], lines["pdfs"]["note"]) == ("91 pieces", "16 pieces")
    assert lines["groq"]["what"].startswith(agent.model_name())
    assert body["model"] == agent.model_name()


def test_a_staff_user_gets_the_same_page(client, staff, mysql, qdrant):
    client.force_login(staff)
    body = get_home(client)
    assert body["first_name"] == "boss"   # no first name: the user name
    assert len(body["kpis"]) == 8


def test_the_numbers_count_only_up_to_today(client, user, mysql, qdrant):
    client.force_login(user)
    get_home(client)
    sql = {name: next(s for s, _ in mysql.calls if name in s)
           for name in ("FROM fact_invoice_lines f", "FROM fact_sales_order_lines s", "FROM fact_stock_ledger sl")}
    assert "f.invoice_date <= CURDATE()" in sql["FROM fact_invoice_lines f"]
    assert "s.status = 'Open' AND s.order_date <= CURDATE()" in sql["FROM fact_sales_order_lines s"]
    assert "WHERE report_date <= CURDATE()" in sql["FROM fact_stock_ledger sl"]
    assert "movement_type = 'Closing balance'" in sql["FROM fact_stock_ledger sl"]
    sales_params = next(p for s, p in mysql.calls if "FROM fact_invoice_lines f" in s)
    assert max(sales_params) == TODAY                  # no period reaches past today
    assert "net_taxable_value" in sql["FROM fact_invoice_lines f"]


def test_a_change_against_last_year_only_when_the_data_reaches_back(client, user, mysql, qdrant):
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["fy_sales"]["change"] is None         # the invoices start on 21-Dec-2025, after 01-Apr-2025
    assert cards["customers"]["change"] is None

    home.clear_cache()
    mysql.data_from = datetime.date(2024, 4, 1)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["customers"]["change"]["direction"] == "up"
    assert cards["customers"]["change"]["text"] == "206x vs the same dates of FY 2025-26"   # 2063 against 10
    assert cards["products"]["change"]["text"] == "762x vs the same dates of FY 2025-26"   # 3811 against 5


def test_no_stock_report_up_to_today(client, user, mysql, qdrant):
    mysql.stock = []
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["stock"]["text"] == "-" and cards["stock"]["note"] == "No stock report dated up to today"


def test_mysql_down_gives_a_partial_reply_not_a_500(client, user, mysql, qdrant):
    mysql.down = True
    client.force_login(user)
    r = api_get(client, "api_home")
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"] == [] and body["calendar"] is None and body["kpi_error"] == home.MYSQL_DOWN
    assert body["tables"] == [] and body["tables_error"] == home.MYSQL_DOWN
    lines = {line["key"]: line for line in body["connections"]}
    assert lines["ai_gold"]["ok"] is False and lines["ai_gold"]["note"] == "Not reachable right now"
    assert lines["docs"]["ok"] and lines["app_db"]["ok"]   # the rest still works
    assert body["usage"]["questions_today"] == 0 and body["usage_error"] == ""
    assert body["today"]                                    # the welcome still has today's date
    assert "2003" not in r.content.decode() and "secret_reader_user" not in r.content.decode()


def test_a_failure_is_not_kept(client, user, mysql, qdrant):
    mysql.down = True
    client.force_login(user)
    assert get_home(client)["kpi_error"]
    mysql.down = False
    assert get_home(client)["kpi_error"] == ""             # tried again at once, not kept for 10 minutes


def test_the_numbers_are_kept_a_while(client, user, mysql, qdrant):
    client.force_login(user)
    get_home(client)
    asked = len(mysql.calls)
    get_home(client)
    assert len(mysql.calls) == asked                         # the second call reads nothing again
    assert home.CACHE_SECONDS == 600 and home.CHECK_SECONDS == 60


def test_qdrant_down_is_a_red_dot(client, user, mysql, qdrant):
    qdrant.down = True
    client.force_login(user)
    lines = {line["key"]: line for line in get_home(client)["connections"]}
    assert (lines["docs"]["ok"], lines["docs"]["note"]) == (False, "Not reachable right now")
    assert lines["ai_gold"]["ok"] is True


def test_a_collection_never_built(client, user, mysql, qdrant):
    del qdrant.points["mi_pdfs"]
    client.force_login(user)
    lines = {line["key"]: line for line in get_home(client)["connections"]}
    assert (lines["pdfs"]["ok"], lines["pdfs"]["note"]) == (False, "Not built yet")


def test_never_the_main_projects_collection(client, user, mysql, qdrant, monkeypatch):
    monkeypatch.setattr(store, "COLLECTION", "nop_docs")
    client.force_login(user)
    lines = {line["key"]: line for line in get_home(client)["connections"]}
    assert (lines["docs"]["ok"], lines["docs"]["note"]) == (False, "Wrong collection setting")
    assert "nop_docs" not in qdrant.asked


def test_groq_only_says_whether_the_key_is_set(client, user, mysql, qdrant, monkeypatch):
    client.force_login(user)
    groq = {line["key"]: line for line in get_home(client)["connections"]}["groq"]
    assert (groq["ok"], groq["note"]) == (False, "Key not set")       # the tests have no key
    home.clear_cache()
    monkeypatch.setenv("GROQ_API_KEY", SECRETS["GROQ_API_KEY"])
    r = api_get(client, "api_home")
    groq = {line["key"]: line for line in r.json()["connections"]}["groq"]
    assert (groq["ok"], groq["note"]) == (True, "Key set")
    assert SECRETS["GROQ_API_KEY"] not in r.content.decode()


def test_no_secret_in_the_reply(client, user, mysql, qdrant, monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    _asked(user, 100)   # so "recent" is not empty
    client.force_login(user)
    for down in (False, True):
        home.clear_cache()
        mysql.down = down
        text = api_get(client, "api_home").content.decode()
        for value in SECRETS.values():
            assert value not in text
        for word in ("password", "secret", "api_key", "host"):
            assert word not in text.lower()


def _asked(user, tokens, when=None):
    saved = Question.objects.create(user=user, text="Net sales?", model=agent.model_name(), total_tokens=tokens)
    if when:
        Question.objects.filter(pk=saved.pk).update(created_at=when)
    return saved


def test_usage_counts_the_users_own_questions_today(client, user, other, mysql, qdrant, monkeypatch):
    monkeypatch.setenv("GROQ_DAILY_TOKEN_LIMIT", "100000")
    now = timezone.now()
    _asked(user, 4000)
    _asked(user, 6000)
    _asked(other, 10000)                                   # someone else: not "your" questions, but the app's tokens
    _asked(user, 99999, now - datetime.timedelta(days=2))  # two days ago: not today, not in the last 24 hours
    client.force_login(user)
    usage = get_home(client)["usage"]
    assert (usage["questions_today"], usage["my_tokens_today"], usage["my_tokens_text"]) == (2, 10000, "10,000")
    assert (usage["tokens_24h"], usage["limit"], usage["pct"]) == ("20,000", "100,000", 20)   # the whole app
    assert usage["period_tokens"] == "20,000" and usage["period_end"]
    assert usage["model"] == agent.model_name()


def test_usage_is_per_user_and_not_kept(client, user, other, mysql, qdrant):
    _asked(user, 500)
    client.force_login(other)
    assert get_home(client)["usage"]["questions_today"] == 0
    client.force_login(user)
    assert get_home(client)["usage"]["questions_today"] == 1
    _asked(user, 500)
    assert get_home(client)["usage"]["questions_today"] == 2


def test_the_reply_is_plain_json(client, user, mysql, qdrant):
    client.force_login(user)
    body = get_home(client)
    json.dumps(body)   # nothing odd inside
    for card in body["kpis"]:
        keys = {"key", "label", "money", "value", "text", "note", "change", "trend", "ask", "facts"}
        if card["key"] in ("top_customer", "top_product"):
            keys.add("name")
        if card["key"] == "customers":
            keys.add("total")
            assert isinstance(card["total"], int)
        assert set(card) == keys
        assert isinstance(card["value"], (int, float))
        assert card["facts"] is None or (1 <= len(card["facts"]) <= 3 and all(isinstance(f, str) for f in card["facts"]))
        for point in card["trend"] or []:
            assert set(point) == {"label", "value"} and isinstance(point["value"], float)
    assert body["recent"] == [] and body["recent_error"] == ""


# ------------------------------------------------------------------ the KPI trends and their questions
def test_the_kpi_trends(client, user, mysql, qdrant):
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    months = ["May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026"]   # oldest first
    sales = cards["month_sales"]["trend"]
    assert [p["label"] for p in sales] == months
    assert sales[-1] == {"label": "Oct 2026", "value": 2367096647.5}        # the card's own last complete month
    assert sales[-2] == {"label": "Sep 2026", "value": 1955500.0}
    assert sales[2] == {"label": "Jul 2026", "value": 0.0}                  # a month without a sale is 0
    assert [p["value"] for p in cards["customers"]["trend"]] == [14.0, 20.0, 0.0, 20.0, 8.0, 1434.0]
    assert [p["value"] for p in cards["products"]["trend"]] == [27.0, 38.0, 0.0, 25.0, 9.0, 3263.0]
    fy = cards["fy_sales"]["trend"]
    assert [p["label"] for p in fy] == months and fy[-1]["value"] == 2400657912.5   # the FY running total
    assert cards["open_orders"]["trend"] is None and cards["stock"]["trend"] is None
    assert cards["top_customer"]["trend"] is None and cards["top_product"]["trend"] is None


def test_the_trend_query_counts_whole_months_up_to_today(client, user, mysql, qdrant):
    client.force_login(user)
    get_home(client)
    sql, params = next((s, p) for s, p in mysql.calls if "ORDER BY nop_sales_period_end DESC" in s)
    # the months first (one row per month - dim_calendar has one row per day), then the invoices
    assert "SELECT DISTINCT nop_sales_month, nop_sales_period_start, nop_sales_period_end" in sql
    assert "LIMIT 6" in sql and "LEFT JOIN fact_invoice_lines i" in sql
    assert "nop_sales_period_end <= CURDATE()" in sql and "i.invoice_date <= CURDATE()" in sql
    assert "net_taxable_value" in sql and "customer_id <> -1" in sql
    # the FY start, then the KPI's last complete month (20-Oct-2026), then the FY start again
    assert params == (datetime.date(2026, 4, 1), datetime.date(2026, 10, 20), datetime.date(2026, 4, 1))


def test_the_fy_trend_has_only_this_fys_months(client, user, mysql, qdrant):
    ends = [datetime.date(2025, 11, 20), datetime.date(2025, 12, 20), datetime.date(2026, 1, 20),
            datetime.date(2026, 2, 20), datetime.date(2026, 3, 20), datetime.date(2026, 4, 20)]
    mysql.trend = [[day.strftime("%b %Y"), day, Decimal("10.00"), 1, 1, Decimal("5.00")] for day in ends]
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert len(cards["month_sales"]["trend"]) == 6
    assert cards["fy_sales"]["trend"] is None             # only Apr 2026 ends in FY 2026-27: one point is no line

    home.clear_cache()
    mysql.trend = mysql.trend[-2:] + [["May 2026", datetime.date(2026, 5, 20), Decimal("7.00"), 1, 1,
                                       Decimal("12.00")]]
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["fy_sales"]["trend"] == [{"label": "Apr 2026", "value": 5.0}, {"label": "May 2026", "value": 12.0}]


def test_no_trend_with_fewer_than_two_months(client, user, mysql, qdrant):
    mysql.trend = mysql.trend[-1:]
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert all(card["trend"] is None for card in cards.values())
    assert cards["month_sales"]["text"] == "INR 1,200,000.00"   # the card itself still shows


def test_each_kpi_has_its_question_for_the_ask_page(client, user, mysql, qdrant):
    client.force_login(user)
    asks = {card["key"]: card["ask"] for card in get_home(client)["kpis"]}
    assert asks == {
        "month_sales": "Net sales of the last 6 NOP months as a line chart",
        "fy_sales": "Net sales by NOP month of FY 2026-27 so far as a line chart",
        "customers": "Active customers in each of the last 6 NOP months",
        "products": "Number of products sold in each of the last 6 NOP months",
        "open_orders": "List the open sales orders up to today",
        "stock": "Stock value by item group on the latest stock report",
        "top_customer": "Top 10 customers of the last NOP month by net sales",
        "top_product": "Top 10 products of the last NOP month by net sales",
    }


def test_the_trends_are_kept_with_the_numbers(client, user, mysql, qdrant):
    client.force_login(user)
    get_home(client)
    get_home(client)
    assert sum("ORDER BY nop_sales_period_end DESC" in s for s, _ in mysql.calls) == 1


# ------------------------------------------------------------------ the user's recent questions
def _asked_at(user, text, minutes_ago, **fields):
    saved = Question.objects.create(user=user, text=text, model=agent.model_name(), **fields)
    Question.objects.filter(pk=saved.pk).update(created_at=timezone.now() - datetime.timedelta(minutes=minutes_ago))
    return saved


def test_recent_questions_are_the_users_own_last_five(client, user, other, mysql, qdrant):
    from portal.models import Conversation
    chat = Conversation.objects.create(user=user, title="Sales")
    deleted = Conversation.objects.create(user=user, title="Gone", deleted_at=timezone.now())
    archived = Conversation.objects.create(user=user, title="Old", archived=True)
    mine = [_asked_at(user, f"Question {n}", minutes_ago=n * 10, conversation=chat) for n in range(1, 6)]
    _asked_at(user, "Asked in a deleted chat", minutes_ago=1, conversation=deleted)
    edited = _asked_at(user, "Edited away", minutes_ago=2, conversation=chat)
    Question.objects.filter(pk=edited.pk).update(replaced_by=mine[0])
    _asked_at(other, "Someone else's question", minutes_ago=0)
    in_list = _asked_at(user, "From a chat removed from the list", minutes_ago=3, conversation=archived,
                        status="nodata")
    client.force_login(user)
    recent = get_home(client)["recent"]
    # newest first, at most 5; not the deleted chat's, not the edited one, never another user's;
    # a chat only removed from the list still shows (as on History)
    assert [q["text"] for q in recent] == ["From a chat removed from the list", "Question 1", "Question 2",
                                           "Question 3", "Question 4"]
    assert recent[0] == {"id": in_list.pk, "text": "From a chat removed from the list", "status": "nodata",
                         "when": recent[0]["when"], "url": f"/q/{in_list.pk}"}
    assert recent[1]["status"] == "ok" and recent[1]["url"] == f"/q/{mine[0].pk}"

    client.force_login(other)
    assert [q["text"] for q in get_home(client)["recent"]] == ["Someone else's question"]


def test_recent_when_is_india_time(client, user, mysql, qdrant):
    saved = Question.objects.create(user=user, text="Net sales?", model=agent.model_name())
    moment = datetime.datetime(2026, 11, 5, 8, 34, tzinfo=datetime.timezone.utc)   # 2:04 PM in India
    Question.objects.filter(pk=saved.pk).update(created_at=moment)
    client.force_login(user)
    assert get_home(client)["recent"][0]["when"] == "05-Nov 2:04 PM"


def test_recent_failing_is_handled(client, user, mysql, qdrant, monkeypatch):
    from portal.models import QuestionQuerySet

    def broken(self):
        raise RuntimeError("app database user secret_reader_user refused")

    monkeypatch.setattr(QuestionQuerySet, "visible", broken)
    client.force_login(user)
    r = api_get(client, "api_home")
    assert r.status_code == 200
    body = r.json()
    assert body["recent"] == [] and body["recent_error"] == home.PART_FAILED
    assert len(body["kpis"]) == 8 and body["usage_error"] == ""   # the rest still comes
    assert "secret_reader_user" not in r.content.decode()


# ------------------------------------------------------------------ the small facts and the top cards
def test_the_facts_of_the_cards(client, user, mysql, qdrant):
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["open_orders"]["facts"] == ["10 orders", "14 lines", "INR 60.6 L incl. GST"]   # 6,059,202.20
    assert cards["stock"]["facts"] == ["52 items", "Report 20-Sep-2026"]
    assert cards["top_customer"]["facts"] == ["2.7% of Oct 2026 sales"]   # 32,400 of 1,200,000
    assert cards["top_product"]["facts"] == ["1.5% of Oct 2026 sales"]    # 18,000 of 1,200,000
    for key in ("month_sales", "fy_sales", "customers", "products"):
        assert cards[key]["facts"] is None


def test_one_order_and_no_stock_report(client, user, mysql, qdrant, monkeypatch):
    rows = mysql.rows
    monkeypatch.setattr(mysql, "rows", lambda sql: [[1, 1, Decimal("950.00"), Decimal("950.00")]]
                        if "FROM fact_sales_order_lines s" in sql else rows(sql))
    mysql.stock = []
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["open_orders"]["facts"] == ["1 order", "1 line", "INR 950 incl. GST"]
    assert cards["stock"]["facts"] is None


def test_the_top_customer_and_product(client, user, mysql, qdrant):
    client.force_login(user)
    kpis = get_home(client)["kpis"]
    assert len(kpis) == 8 and [card["key"] for card in kpis[-2:]] == ["top_customer", "top_product"]
    customer, product = kpis[-2:]
    assert customer == {
        "key": "top_customer", "label": "Top customer Oct 2026", "name": "Allied Castings Limited", "money": True,
        "value": 32400.0, "text": "INR 32,400.00",
        "note": "21-Sep-2026 to 20-Oct-2026 (last complete NOP sales month)", "change": None, "trend": None,
        "ask": "Top 10 customers of the last NOP month by net sales", "facts": ["2.7% of Oct 2026 sales"]}
    assert (product["label"], product["name"], product["text"]) == (
        "Top product Oct 2026", "Coolant pump HM-445-1B", "INR 18,000.00")
    assert product["ask"] == "Top 10 products of the last NOP month by net sales" and product["change"] is None


def test_the_top_query_counts_the_last_month_up_to_today(client, user, mysql, qdrant):
    client.force_login(user)
    get_home(client)
    get_home(client)
    tops = [(s, p) for s, p in mysql.calls if "UNION ALL" in s and "JOIN dim_customers cu" in s]
    assert len(tops) == 1                                       # one query for both, kept with the other numbers
    sql, params = tops[0]
    month = (datetime.date(2026, 9, 21), datetime.date(2026, 10, 20))
    assert params == month + month                              # the last complete NOP month, for both parts
    assert "il.invoice_date <= CURDATE()" in sql and "net_taxable_value" in sql
    assert "customer_id <> -1" in sql and "product_id <> -1" in sql   # never the Unknown row
    assert "dim_calendar" not in sql                            # dates on the invoice: no day-by-day join
    assert "JOIN dim_products p" in sql and "product_description" in sql


def test_no_sales_in_the_last_month(client, user, mysql, qdrant):
    mysql.top = []
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    for key in ("top_customer", "top_product"):
        card = cards[key]
        assert (card["value"], card["text"], card["name"], card["note"], card["facts"]) == (
            0.0, "-", "", "No sales in Oct 2026", None)
        assert card["ask"]                                       # a click still asks the Ask page


def test_only_a_top_customer(client, user, mysql, qdrant):
    mysql.top = mysql.top[:1]                                    # sales in the month, but only service lines
    client.force_login(user)
    cards = {card["key"]: card for card in get_home(client)["kpis"]}
    assert cards["top_customer"]["name"] == "Allied Castings Limited"
    assert cards["top_product"]["text"] == "-" and cards["top_product"]["facts"] is None


@pytest.mark.parametrize("amount, text", [
    (63648019, "6.4 Cr"), (6059202.2, "60.6 L"), (950, "950"), (0, "0"), (None, "0"), (12345, "12.3 K"),
    (100000, "1 L"), (-150000, "-1.5 L"), (2367096647.5, "237 Cr"), (Decimal("43605227525.00"), "4,361 Cr"),
])
def test_short_money(amount, text):
    assert home._short_money(amount) == text
