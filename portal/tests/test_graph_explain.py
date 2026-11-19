"""The Knowledge graph's "Explain this" (POST /api/graph/explain - api.graph_explain_node, graph_explain.py): one AI
call writes 3-5 sentences about one node, from facts the server reads itself.

The AI is a FAKE (test_agent.FakeAI, installed as portal.lc.llm.make_llm) and MySQL is a fake (test_knowledge_graph's
FakeMySQL, with the FY and ml_* queries added here) - no Groq call, no database outside the tests.
Checks: sign-in, POST only, CSRF, bad input 400 and unknown node 404 before any AI call, the facts of a customer and a
product (with their ML results) built from the database - never from the browser - and only those facts + the rules go
to the AI, the kept reply (no second AI call), the model chain (the backup, the second key at once on a per-minute
limit) and the friendly errors.
Run with:  python -m pytest -q portal/tests/test_graph_explain.py
"""
import datetime
import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from portal import graph_explain
from portal import knowledge_graph as kg
from portal.lc import llm
from portal.rag import agent, warehouse
from portal.tests.test_agent import BACKUP, MAIN, CutOff, daily_limit_error, rate_limit_error, use_fake_ai
from portal.tests.test_knowledge_graph import AURORA, PAGES, FakeMySQL

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 4)
DATA_TO = datetime.date(2026, 10, 31)
EXPLAINED = ("Aurora Hydraulics Private Limited bought INR 2.91 Crore from 21-Dec-2025 to 04-Nov-2026. "
             "Most of it is hydraulic motors. Its risk is High as of 31-Oct-2026.")


class ExplainMySQL(FakeMySQL):
    """FakeMySQL + the queries of graph_explain.py: the net sales per FY and the ml_* results."""

    def __init__(self):
        super().__init__()
        self.ml_missing = False   # True: the ml_ tables do not exist (no ML run yet)
        self.forecast = True      # False: the product is not a top-10 product (no forecast rows)

    def rows(self, sql, params):
        if "GROUP BY c.financial_year" in sql:
            return [["2526", Decimal("1000000.00"), 5], ["2627", Decimal("28088275.00"), 56]]
        if "FROM ml_" in sql and self.ml_missing:
            raise warehouse.QueryError("Table 'ss_gold.ml_customer_risk' doesn't exist")
        if "FROM ml_customer_risk" in sql:
            return [["High", Decimal("72.50"), "Sales fell 82% (last 3 months vs its normal 3 months)",
                     datetime.date(2026, 9, 1), 60, 20, Decimal("150000.00"), Decimal("830000.00"), Decimal("81.93"),
                     DATA_TO]] if params[0] == AURORA else []
        if "FROM ml_customer_segments" in sql:
            return [["Big regular buyers", 3, 61, Decimal("29088275.00"), datetime.date(2025, 12, 21),
                     datetime.date(2026, 10, 28), DATA_TO]]
        if "FROM ml_stock_runout" in sql:
            return [["Under 30 days", DATA_TO, Decimal("40.000"), Decimal("180.000"), Decimal("2.000"),
                     Decimal("20.0"), datetime.date(2026, 11, 20), DATA_TO]]
        if "FROM ml_sales_forecast" in sql:
            if not self.forecast:
                return []
            return [["Nov 2026", datetime.date(2026, 10, 21), datetime.date(2026, 11, 20), Decimal("1250000.00"),
                     Decimal("1000000.00"), Decimal("1500000.00"), DATA_TO],
                    ["Dec 2026", datetime.date(2026, 11, 21), datetime.date(2026, 12, 20), Decimal("1300000.00"),
                     Decimal("950000.00"), Decimal("1650000.00"), DATA_TO]]
        return super().rows(sql, params)


@pytest.fixture
def mysql(monkeypatch):
    fake = ExplainMySQL()
    monkeypatch.setattr(warehouse, "run_select_params", fake)
    monkeypatch.setattr(kg, "document_pages", lambda: PAGES)
    monkeypatch.setattr(graph_explain, "today", lambda: TODAY)
    kg.clear_cache()
    graph_explain.clear_cache()
    yield fake
    kg.clear_cache()
    graph_explain.clear_cache()


@pytest.fixture
def main_model(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", MAIN)
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", BACKUP)


@pytest.fixture
def signed_in(client, user):
    client.force_login(user)
    return client


def explain(client, data=None, **extra):
    body = data if isinstance(data, str) else json.dumps({"type": "customer", "id": str(AURORA)} if data is None else data)
    return client.post(reverse("api_graph_explain"), data=body, content_type="application/json", **extra)


def ml_sql(fake):
    return [sql for sql, _ in fake.calls if "FROM ml_" in sql]


# ---------- who may ask ----------

def test_it_needs_a_sign_in_and_a_post(client, user, monkeypatch, mysql):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    assert explain(client).status_code == 401
    client.force_login(user)
    r = client.get(reverse("api_graph_explain"), {"type": "customer", "id": AURORA})

    assert r.status_code == 405 and r.json()["detail"] == "Use POST here."
    assert fake.calls == [] and mysql.calls == []


def test_it_needs_the_csrf_token(user, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    no_token = explain(client)
    assert no_token.status_code == 403 and "CSRF" in no_token.json()["detail"]
    assert fake.calls == [] and mysql.calls == []

    token = client.get(reverse("api_csrf")).json()["csrfToken"]
    assert settings.CSRF_COOKIE_NAME in client.cookies
    ok = explain(client, HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and len(fake.calls) == 1


@pytest.mark.parametrize("data, words", [
    ({"type": "planet", "id": "1"}, "Unknown node type"),
    ({"id": "16"}, "Unknown node type"),
    ({"type": "customer", "id": "abc"}, "is a number"),
    ({"type": "customer"}, "Give the node's id."),
    ({"type": "customer", "id": "16", "fy": "2099"}, "financial year"),
    ("not json", "Send a JSON object."),
    ("[1, 2]", "Send a JSON object."),
])
def test_bad_input_is_a_400_and_asks_no_ai(signed_in, monkeypatch, mysql, data, words):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in, data)

    assert r.status_code == 400 and words in r.json()["detail"]
    assert fake.calls == []


def test_an_unknown_node_is_a_404_and_asks_no_ai(signed_in, monkeypatch, mysql):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in, {"type": "customer", "id": "999"})

    assert r.status_code == 404 and "No customer '999'" in r.json()["detail"]
    assert fake.calls == []


def test_mysql_down_is_a_friendly_503_and_asks_no_ai(signed_in, monkeypatch, mysql):
    mysql.down = True
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in)

    assert r.status_code == 503 and r.json()["detail"] == kg.MYSQL_DOWN
    assert "ai_reader" not in r.content.decode() and fake.calls == []


# ---------- the facts and the AI call ----------

def test_a_customer_is_explained_from_its_own_facts_and_ml_results(signed_in, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, [(EXPLAINED, 640)])

    # numbers sent by the browser are never used: only the type, the id and the period
    r = explain(signed_in, {"type": "customer", "id": str(AURORA), "amount": 999, "facts": "Net sales INR 1 Crore"})

    assert r.status_code == 200, r.content
    assert r.json() == {"text": EXPLAINED, "model": MAIN, "model_label": "Groq gpt-oss-120b", "model_note": "",
                        "tokens": 640, "cached": False, "node": f"customer:{AURORA}",
                        "period": "All data up to today"}
    assert fake.models == [MAIN] and fake.max_tokens == [graph_explain.MAX_TOKENS]   # one call, the main model
    system, human = fake.calls[0]
    assert system["content"] == graph_explain.EXPLAIN_SYSTEM_PROMPT                  # the rules ...
    assert "Write 3 to 5 short sentences" in system["content"]
    assert "Never invent numbers" in system["content"] and "Crore or lakh" in system["content"]
    facts = human["content"]                                                          # ... and only the facts
    assert facts.startswith("Facts about this node (read from the SS Manufacturing data just now):\n")
    for fact in [
        'Node: Customer "Aurora Hydraulics Private Limited" (Chennai, Tamil Nadu · Local Customer)',
        "Today: 04-Nov-2026",
        "Period of the numbers: All data up to today (21-Dec-2025 to 04-Nov-2026)",
        "- Net sales: INR 2.91 Crore (2,90,88,275.00)",
        "- Quantity 812; 61 invoices; 140 invoice lines",
        "- Its lines in this period are dated 03-Apr-2026 to 02-Nov-2026",
        "- Products it bought: 105 in all; top 2 by net sales: Hydraulic motor HM-346-1B INR 12.50 lakh "
        "(12,50,000.00), 4.3% of its net sales; Trochoid pump TP-120 INR -5,000.00\n",
        "- Sales people on its invoices: 2 in all; top 1 by net sales: Priya Iyer INR 2.90 Crore (2,90,00,000.00), "
        "99.7% of its net sales",
        "- Note: Unknown product (service lines, or items not in the master): 7,125.00 is in the total but not drawn.",
        "Net sales per financial year (April to March):",
        "- FY 2025-26: INR 10.00 lakh (10,00,000.00), 5 invoices",
        "- FY 2026-27 so far (up to today): INR 2.81 Crore (2,80,88,275.00), 56 invoices",
        "ML results of the app (estimates, not recorded sales):",
        "- Customer risk (made from the data up to 31-Oct-2026): High, score 72.5 of 100; reason: Sales fell 82% "
        "(last 3 months vs its normal 3 months); last invoice 01-Sep-2026, 60 days before 31-Oct-2026; usually an "
        "invoice every 20 days; net sales of the last 3 months INR 1.50 lakh (1,50,000.00) against its normal 3 "
        "months INR 8.30 lakh (8,30,000.00) (81.9% below normal)",
        "- Customer group (made from the data up to 31-Oct-2026): Big regular buyers (61 invoices; net sales INR "
        "2.91 Crore (2,90,88,275.00) in all the data; invoices from 21-Dec-2025 to 28-Oct-2026; 3 days since the "
        "last invoice)",
    ]:
        assert fact in facts, fact
    assert "999" not in facts and "INR 1 Crore" not in facts                         # nothing from the browser
    assert "stock" not in facts.lower() and "forecast" not in facts.lower()          # no product ML for a customer
    tables = " ".join(ml_sql(mysql))
    assert "ml_customer_risk" in tables and "ml_customer_segments" in tables and "ml_stock_runout" not in tables
    assert all(AURORA in params for sql, params in mysql.calls if "FROM ml_" in sql)   # the id is a parameter only


def test_a_product_is_explained_with_its_stock_run_out_and_forecast(signed_in, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, ["The motor sold INR 2.91 Crore. Its stock runs out around 20-Nov-2026."])

    r = explain(signed_in, {"type": "product", "id": "45", "fy": "2627"})

    assert r.status_code == 200, r.content
    assert r.json()["period"] == "FY 2026-27 so far" and r.json()["node"] == "product:45"
    facts = fake.calls[0][1]["content"]
    for fact in [
        'Node: Product "Hydraulic motor HM-346-1B" (FG00045 · Hydraulic motors)',
        "Period of the numbers: FY 2026-27 so far (01-Apr-2026 to 04-Nov-2026)",
        "- Customers who bought it: 5 in all; top 1 by net sales: Aurora Hydraulics Private Limited INR 12.50 lakh",
        "- Its category: 1 in all; all: Hydraulic motors INR 12.50 lakh",
        "- Company PDF pages that cover it: 2 in all; all: Product Catalogue, page 2 (5 mentions of its category "
        "Hydraulic motors); Warranty and Returns Policy, page 1 (2 mentions of its category Hydraulic motors)",
        "- Stock run-out (stock report of 31-Oct-2026, sales of the 90 days up to 31-Oct-2026): Under 30 days; stock "
        "40; sold 180 in the 90 days (about 2 a day); about 20 days of stock left, runs out around 20-Nov-2026 at "
        "this speed",
        "- Sales forecast (made from the data up to 31-Oct-2026), net sales per sales month with an 80% range: "
        "Nov 2026 (21-Oct-2026 to 20-Nov-2026) INR 12.50 lakh (12,50,000.00), range INR 10.00 lakh (10,00,000.00) "
        "to INR 15.00 lakh (15,00,000.00); Dec 2026",
    ]:
        assert fact in facts, fact
    assert "Customer risk" not in facts and "Customer group" not in facts
    assert [p for sql, p in mysql.calls if "FROM ml_" in sql] == [(45,), (45,)]


def test_a_product_without_a_forecast_says_so(signed_in, monkeypatch, mysql):
    mysql.forecast = False
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    assert explain(signed_in, {"type": "product", "id": "45"}).status_code == 200

    assert "- Sales forecast: none for this product (only the top 10 products have one)" in fake.calls[0][1]["content"]


def test_without_the_ml_tables_the_ml_facts_are_left_out(signed_in, monkeypatch, mysql):
    mysql.ml_missing = True
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in)

    assert r.status_code == 200
    facts = fake.calls[0][1]["content"]
    assert "ML results" not in facts and "- Net sales: INR 2.91 Crore" in facts


def test_a_category_has_no_ml_facts_but_its_numbers(signed_in, monkeypatch, mysql):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in, {"type": "category", "id": "Hydraulic motors"})

    assert r.status_code == 200
    facts = fake.calls[0][1]["content"]
    assert 'Node: Category "Hydraulic motors" (577 items)' in facts
    assert "- Products in this category: 525 in all" in facts and "FY 2026-27 so far" in facts
    assert ml_sql(mysql) == []


def test_a_pdf_page_is_explained_from_its_text_and_the_categories_it_names(signed_in, monkeypatch, mysql):
    fake = use_fake_ai(monkeypatch, [EXPLAINED])

    r = explain(signed_in, {"type": "document", "id": "product_catalogue.pdf#2"})

    assert r.status_code == 200
    facts = fake.calls[0][1]["content"]
    assert 'Node: Document "Product Catalogue, page 2" (product_catalogue.pdf)' in facts
    assert "Text at the start of the page: 5. Hydraulic motors (HM series)" in facts
    assert ("- Product categories this page names: 1 in all; all: Hydraulic motors (5 mentions, its net sales INR "
            "62.16 Crore (62,15,65,971.00))") in facts
    assert "per financial year" not in facts and ml_sql(mysql) == []


def test_the_same_node_again_is_kept_and_asks_no_ai(signed_in, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, [(EXPLAINED, 640), ("Another text for FY 2026-27.", 500)])

    first = explain(signed_in)
    again = explain(signed_in)

    assert first.json()["cached"] is False
    assert again.status_code == 200 and again.json() == {**first.json(), "cached": True}
    assert len(fake.calls) == 1                                                      # no second AI call

    other = explain(signed_in, {"type": "customer", "id": str(AURORA), "fy": "2627"})  # another period: asked
    assert other.json()["text"] == "Another text for FY 2026-27." and len(fake.calls) == 2


def test_new_facts_or_an_old_reply_ask_again(signed_in, monkeypatch, mysql):
    fake = use_fake_ai(monkeypatch, [EXPLAINED, "Second.", "Third."])
    explain(signed_in)

    mysql.ml_missing = True                                                          # other facts (new data)
    assert explain(signed_in).json()["text"] == "Second."

    for key, (at, reply) in list(graph_explain._kept.items()):                       # 10 minutes later
        graph_explain._kept[key] = (at - graph_explain.CACHE_SECONDS - 1, reply)
    assert explain(signed_in).json()["text"] == "Third." and len(fake.calls) == 3


def test_the_reply_is_cleaned_and_a_cut_off_reply_keeps_whole_sentences(signed_in, monkeypatch, mysql):
    use_fake_ai(monkeypatch, [CutOff("**Aurora** bought INR 2.91 Crore in FY 2627. It buys motors. Its ri")])

    r = explain(signed_in)

    assert r.status_code == 200
    assert r.json()["text"] == "Aurora bought INR 2.91 Crore in FY 2026-27. It buys motors."


def test_an_empty_reply_is_a_friendly_502(signed_in, monkeypatch, mysql):
    use_fake_ai(monkeypatch, [CutOff("Aurora bough")])

    r = explain(signed_in)

    assert r.status_code == 502 and r.json()["detail"] == graph_explain.NO_TEXT


# ---------- the model chain and friendly errors ----------

def test_after_the_main_models_daily_limit_the_backup_explains(signed_in, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(MAIN), (EXPLAINED, 300)])

    r = explain(signed_in)

    assert r.status_code == 200, r.content
    body = r.json()
    assert body["model"] == BACKUP and body["model_label"] == f"Groq qwen ({BACKUP})" and body["tokens"] == 300
    assert "the backup model qwen answered" in body["model_note"]
    assert fake.models == [MAIN, BACKUP] and fake.max_tokens[1] == min(graph_explain.MAX_TOKENS,
                                                                        agent.FALLBACK_MAX_TOKENS)
    assert fake.calls[1] == fake.calls[0]                                            # the same facts


def test_the_first_keys_per_minute_limit_asks_the_second_key_at_once(signed_in, monkeypatch, mysql, main_model):
    monkeypatch.setenv(llm.KEY_2, "test-groq-key-2")
    waits = []
    monkeypatch.setattr(agent.time, "sleep", waits.append)
    fake = use_fake_ai(monkeypatch, [rate_limit_error(retry_after=7), EXPLAINED])

    r = explain(signed_in)

    assert r.status_code == 200 and waits == []                                      # no waiting
    assert fake.keys == [llm.KEY, llm.KEY_2] and fake.models == [MAIN, MAIN]
    assert r.json()["model_label"] == "Groq gpt-oss-120b (2nd key)"
    assert r.json()["model_note"].endswith("the second Groq key answered")


def test_a_daily_limit_of_every_model_is_a_friendly_503(signed_in, monkeypatch, mysql, main_model):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(MAIN), daily_limit_error(BACKUP)])

    r = explain(signed_in)

    assert r.status_code == 503 and r.json()["detail"] == graph_explain.DAILY_LIMIT
    assert fake.models == [MAIN, BACKUP]
    assert graph_explain._kept == {}                                                 # nothing kept


def test_a_busy_ai_is_a_friendly_503(signed_in, monkeypatch, mysql, main_model):
    use_fake_ai(monkeypatch, [rate_limit_error(retry_after=600), rate_limit_error(retry_after=600)])

    r = explain(signed_in)

    assert r.status_code == 503 and r.json()["detail"] == agent.AI_BUSY


def test_no_key_set_up_is_a_friendly_503(signed_in, mysql, monkeypatch):
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)                         # the real make_llm: no key

    r = explain(signed_in)

    assert r.status_code == 503 and r.json()["detail"] == llm.MISSING_KEY


# ---------- small helpers ----------

def test_inr_and_the_running_fy():
    assert graph_explain.inr(Decimal("29088275")) == "INR 2.91 Crore (2,90,88,275.00)"
    assert graph_explain.inr(450000) == "INR 4.50 lakh (4,50,000.00)"
    assert graph_explain.inr(-9500) == "INR -9,500.00" and graph_explain.inr(None) == "INR 0.00"
    assert graph_explain.running_fy(datetime.date(2026, 11, 19)) == "2627"
    assert graph_explain.running_fy(datetime.date(2027, 3, 31)) == "2627"
    assert graph_explain.running_fy(datetime.date(2027, 4, 1)) == "2728"
