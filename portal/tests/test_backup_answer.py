"""The backup model's ANSWER request stays small enough, and a 413 on it is tried once more smaller (18-Nov).

At 10:10 an ML Insights question gave 102 rows: the backup model (the main model was over its daily limit) wrote the
SQL, but the answer step failed after 0.3 s and the card said "Here are the rows for your question (the AI could not
write a summary this time)." (History: that time the backup itself was at its daily limit.) A big answer request can
fail the same way when it is more than the backup's ~6,000 tokens a minute (Groq 413, request too large) - and until
now nothing smaller was tried. Now:
- the backup's answer request has at most agent.FALLBACK_ROWS_FOR_ANSWER rows (fewer when the text is still big),
  always with the "only the first N are shown to you, the user's table shows all ROW_COUNT" rule;
- on a 413 it is sent once more as the smallest request (agent.BACKUP_SMALLEST_ROWS rows, only the app's facts: the
  ML results note, the totals, the run-out dates, the forecast months stay; the general data-dates / history-start
  rules and the extra PDF pieces go) before the rows are shown without a summary;
- every fact the app works out (highest / lowest, run-out dates, totals ...) comes from ALL the rows, not the cut ones;
- the main model's answer request is as before (agent.ROWS_FOR_ANSWER rows).
Measured with tiktoken o200k on 102-row ML results: the backup's request 2,340-4,040 tokens (+1,000 for the reply),
the smallest 2,060-2,780 (+1,000); the main model's 3,030-7,200.

The AI is the FAKE of test_agent.py (FakeAI behind LangChain): no Groq call.
Run with:  python -m pytest -q portal/tests/test_backup_answer.py
"""
import datetime
import re
from decimal import Decimal

import pytest

from portal.lc import calls
from portal.lc.calls import LcRequest
from portal.rag import agent
from portal.tests.test_agent import (BACKUP, MAIN, daily_limit_error, explain_messages, mysql,  # noqa: F401
                                     use_fake_ai, with_backup)  # noqa: F401
from portal.tests.test_backup_ml_mode import BACKUP_BUDGET, ml_gold  # noqa: F401
from portal.tests.test_backup_model import too_large_error

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

QUESTION = "which items will run out of stock in the next 90 days?"
RUNOUT_SQL = ("SELECT sr.product_code, sr.product_description, sr.item_group, sr.stock_qty, sr.avg_daily_sales_qty, "
              "sr.days_left, sr.runout_date, sr.status, sr.report_date FROM ml_stock_runout sr "
              "WHERE sr.status IN ('Out of stock', 'Under 30 days', 'Under 90 days') ORDER BY sr.days_left")
RUNOUT_COLUMNS = ["product_code", "product_description", "item_group", "stock_qty", "avg_daily_sales_qty",
                  "days_left", "runout_date", "status", "report_date"]
TODAY = datetime.date.today()          # agent.past_runout_note compares with the real today
PAST = 30                              # the first 30 items' run-out dates are before today
# 102 items, soonest first (as the SQL orders them)
RUNOUT_ROWS = {"columns": RUNOUT_COLUMNS,
               "rows": [[f"FG{1000 + i:05d}", f"HYDRAULIC CYLINDER ASSY {i} BORE 63 X STROKE 250 MM", "Finished goods",
                         Decimal(f"{100 + i * 7}.000"), Decimal(f"{3 + i % 9}.456"), Decimal(f"{i * 0.9:.1f}"),
                         TODAY + datetime.timedelta(days=i - PAST), "Under 30 days" if i < 60 else "Under 90 days",
                         datetime.date(2026, 10, 31)] for i in range(102)],
               "truncated": False}
STOCK_NOTE = ("Stock run-out totals (worked out by the app): 12 Out of stock, 349 Under 30 days, 102 Under 90 days, "
              "85 OK, 900 No recent sales - 1,448 items; stock report and data up to 31-Oct-2026.")
ANSWER = "60 items run out within 30 days and 42 more within 90 days; 30 of them would have run out already."
CHARS_PER_TOKEN = 2.9   # a safe count for rows of numbers: tiktoken o200k counted 3.0-3.2 characters a token


def tokens(call):
    """A safe count of the tokens of one call's messages (more than tiktoken o200k counts)."""
    return round(sum(len(message["content"]) for message in call) / CHARS_PER_TOKEN)


def rows_in(request):
    """The data rows the answer request shows (the lines of the table after its header line)."""
    return len(re.findall(r"^FG\d{5} \| ", request, flags=re.M))


def runout_sql_reply():
    return (f"```sql\n{RUNOUT_SQL}\n```", 3000)


@pytest.fixture
def runout(monkeypatch, ml_gold):
    """The fake MySQL gives the 102 items; the run-out totals note as the real one says it."""
    ml_gold.results = [RUNOUT_ROWS]
    monkeypatch.setattr(agent, "ml_totals_note", lambda sql: STOCK_NOTE if "ml_stock_runout" in (sql or "") else "")
    return ml_gold


def has_the_ml_facts(request, shown):
    """The rules and facts the answer must keep, whatever it is cut to."""
    assert f"102 row(s); only the first {shown} are shown to you here, the user's table shows all 102" in request
    assert "ML results: " + agent.ML_RESULTS_NOTE in request
    assert "\n\n" + STOCK_NOTE in request
    # the run-out fact is worked out from ALL 102 rows (the AI sees far fewer)
    assert f"Run-out dates (worked out by the app - use this): {PAST} of the 102 items" in request
    return True


# ---------- at the main model's daily limit ----------

def test_the_backup_answer_request_of_102_rows_is_cut_and_keeps_the_facts(monkeypatch, runout, user, with_backup):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), runout_sql_reply(), (ANSWER, 4000)])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.answer == ANSWER and result.model == BACKUP
    assert fake.models == [MAIN, BACKUP, BACKUP] and len(result.rows) == 102
    answer = fake.calls[2]
    request = answer[-1]["content"]
    assert rows_in(request) <= agent.FALLBACK_ROWS_FOR_ANSWER
    assert has_the_ml_facts(request, rows_in(request))
    assert fake.max_tokens[2] == agent.FALLBACK_MAX_TOKENS
    assert tokens(answer) + agent.FALLBACK_MAX_TOKENS <= BACKUP_BUDGET


def test_a_413_on_the_backup_answer_sends_the_smallest_request(monkeypatch, runout, user, with_backup):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), runout_sql_reply(), too_large_error(), (ANSWER, 3000)])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.answer == ANSWER
    assert result.model == BACKUP and result.answered_by_backup and not result.error
    assert fake.models == [MAIN, BACKUP, BACKUP, BACKUP]
    cut, smallest = fake.calls[2], fake.calls[3]
    request = smallest[-1]["content"]
    assert rows_in(request) == agent.BACKUP_SMALLEST_ROWS < rows_in(cut[-1]["content"])
    assert has_the_ml_facts(request, agent.BACKUP_SMALLEST_ROWS)
    assert smallest[0]["content"] == cut[0]["content"] == agent.EXPLAIN_SYSTEM_PROMPT     # the same rules
    assert tokens(smallest) < tokens(cut)
    assert tokens(smallest) + agent.FALLBACK_MAX_TOKENS <= BACKUP_BUDGET - 1000          # well under
    assert fake.max_tokens[3] == agent.FALLBACK_MAX_TOKENS


def test_a_413_on_the_smallest_answer_too_shows_the_rows(monkeypatch, runout, user, with_backup):
    fake = use_fake_ai(monkeypatch, [daily_limit_error(), runout_sql_reply(), too_large_error(), too_large_error()])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.answer == agent.ROWS_ONLY_ANSWER and len(result.rows) == 102
    assert fake.models == [MAIN, BACKUP, BACKUP, BACKUP]                                 # tried once more, not again


def test_the_main_model_answer_request_has_its_normal_rows(monkeypatch, runout, user, with_backup):
    fake = use_fake_ai(monkeypatch, [runout_sql_reply(), (ANSWER, 6000)])

    result = agent.ask(QUESTION, user, mode="ml")

    assert result.status == "ok" and result.model == MAIN and fake.models == [MAIN, MAIN]
    request = fake.calls[1][-1]["content"]
    assert rows_in(request) == agent.ROWS_FOR_ANSWER == 50
    assert has_the_ml_facts(request, 50)
    assert fake.max_tokens[1] == agent.ANSWER_MAX_TOKENS


# ---------- the parts ----------

def test_for_backup_gives_the_smallest_answer_values_only_after_a_413():
    made = []
    request = LcRequest("answer", {"table": "20 rows"}, backup={"smallest": lambda: made.append(1) or {"table": "8"}})
    assert calls.for_backup(request) is request and made == []                           # made only when needed
    assert calls.for_backup(request, smallest=True).values == {"table": "8"} and made == [1]
    plain = LcRequest("answer", {"table": "rows"})
    assert calls.for_backup(plain, smallest=True) is plain                               # nothing smaller: as it is


PRODUCT_FORECAST_SQL = ("SELECT f.product_code, f.sales_month, f.forecast_inr FROM ml_sales_forecast f "
                        "WHERE f.level = 'PRODUCT' ORDER BY f.product_code, f.period_start")


def product_forecast():
    """102 product forecasts; the highest is row 90, the lowest row 95 - far below the rows any cut shows."""
    months = ["Nov 2026", "Dec 2026", "Jan 2027"]
    rows = [[f"FG{1000 + i // 3:05d}", months[i % 3], Decimal(f"{1000000 + i * 1000}.00")] for i in range(102)]
    rows[90][2], rows[95][2] = Decimal("9999999.00"), Decimal("1.00")
    return agent.AskResult(text="product forecasts", status="ok", columns=["product_code", "sales_month",
                                                                           "forecast_inr"],
                           rows=rows, sql=PRODUCT_FORECAST_SQL)


def test_the_facts_come_from_all_the_rows_in_every_cut(monkeypatch):
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    monkeypatch.setattr(agent, "ml_totals_note", lambda sql: "")
    monkeypatch.setattr(agent, "forecast_months_note", lambda sql: "products - Nov 2026 to Jan 2027 (3 sales months).")
    result = product_forecast()
    for values in (agent.explain_values(result, agent.ROWS_FOR_ANSWER),
                   agent.explain_values(result, agent.FALLBACK_ROWS_FOR_ANSWER, agent.FALLBACK_MAX_ANSWER_CHARS),
                   agent.explain_values(result, agent.BACKUP_SMALLEST_ROWS, agent.BACKUP_SMALLEST_ANSWER_CHARS,
                                        smallest=True)):
        table = values["table"]
        assert "highest forecast_inr: product_code FG01030, sales_month Nov 2026 = 9,999,999.00" in table
        assert "lowest forecast_inr: product_code FG01031, sales_month Jan 2027 = 1.00" in table
        assert "Forecast months available (worked out by the app): products - Nov 2026 to Jan 2027" in table
        assert "ML results: " + agent.ML_RESULTS_NOTE in table


def test_a_list_in_order_gets_highest_and_lowest_when_the_ai_sees_only_part_of_it(monkeypatch):
    """15 months in order: the main model sees all 15 (the order shows the highest - no line, as before); the
    smallest backup request sees 8, so the app's line names the real lowest (row 15)."""
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    rows = [[f"M{i:02d}", Decimal(f"{1000 - i * 10}.00")] for i in range(15)]
    result = agent.AskResult(text="sales per month", status="ok", columns=["month_name", "net_sales_inr"], rows=rows,
                             sql="SELECT month_name, net_sales_inr FROM fact_invoice_lines")
    assert "Highest / lowest" not in agent.explain_values(result, agent.ROWS_FOR_ANSWER)["table"]
    small = agent.explain_values(result, agent.BACKUP_SMALLEST_ROWS, agent.BACKUP_SMALLEST_ANSWER_CHARS,
                                 smallest=True)["table"]
    assert "lowest net_sales_inr: M14 = 860.00" in small


def test_the_smallest_request_leaves_out_the_general_rules_and_extra_pdf_pieces(monkeypatch):
    monkeypatch.setattr(agent, "data_coverage_notes", lambda sql: [])
    result = agent.AskResult(text="new customers", status="ok",
                             columns=["customer_name", "data_from", "invoice_history_starts"],
                             rows=[[f"C{i}", datetime.date(2024, 4, 1), datetime.date(2024, 4, 1)] for i in range(3)],
                             sql="SELECT 1 FROM fact_invoice_lines")
    hits = [{"title": f"Doc {n}", "page": n, "text": f"piece {n}"} for n in (1, 2, 3)]
    normal = agent.explain_values(result, agent.FALLBACK_ROWS_FOR_ANSWER, agent.FALLBACK_MAX_ANSWER_CHARS,
                                  pdf_hits=hits)
    small = agent.explain_values(result, agent.BACKUP_SMALLEST_ROWS, agent.BACKUP_SMALLEST_ANSWER_CHARS,
                                 pdf_hits=hits, smallest=True)
    assert agent.DATA_DATES_NOTE in normal["table"] and agent.HISTORY_START_NOTE in normal["table"]
    assert agent.DATA_DATES_NOTE not in small["table"] and agent.HISTORY_START_NOTE not in small["table"]
    assert "piece 3" in normal["documents"]
    assert "piece 1" in small["documents"] and "piece 2" not in small["documents"]
