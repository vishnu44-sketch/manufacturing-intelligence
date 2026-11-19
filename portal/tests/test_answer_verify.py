"""Our own check of a data answer's TEXT against the rows and the facts (portal/answer_verify.py, agent.explain).

18-Nov: "What is the sales forecast for August 2027?" got "there was no sales forecast for August 2027" - the SQL read
only the PRODUCT level (0 rows), while ml_sales_forecast has the TOTAL forecast for Aug 2027 (about 53.7 Cr).
Now the answer is checked once by our code (no AI call): a "no data / no forecast" claim that the rows or the
forecast table disprove, or a big amount that is in neither the rows nor the facts, sends the answer back to the
AI ONCE with the exact correction; the rewritten answer is kept even when it is still wrong (never a loop).
The answers that are right (the 18-Nov chat: forecasts in Cr, risk lists, alerts, run-out, groups) are never sent
back. General, documents, memory and answer-check replies are never checked.

The AI is the fake one of test_agent.py (FakeAI behind LangChain); MySQL and the notes search are faked.
Run with:  python -m pytest -q portal/tests/test_answer_verify.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import answer_verify
from portal.rag import agent, warehouse
from portal.tests.test_agent import (DOC_ANSWER, DOC_QUESTION, PDF_HITS, mysql, use_fake_ai,  # noqa: F401
                                     use_pdf_hits)
from portal.tests.test_forecast_checks import PER_MONTH_SQL, YEAR_ROWS, sales_month
from portal.tests.test_ml_questions import ALLOWED
from portal.tests.test_stream import fake_ai, kinds, signed_in, stream  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

DATA_TO = datetime.date(2026, 10, 31)
QUESTION = "What is the sales forecast for August 2027?"
# the SQL of 18-Nov (question 167): only the PRODUCT level - no row for Aug 2027
PRODUCT_SQL = """```sql
SELECT f.product_code, f.product_description, f.sales_month, f.period_start, f.period_end, f.forecast_inr,
  f.low_inr, f.high_inr, f.mape_pct, f.data_to
FROM ml_sales_forecast AS f
WHERE f.level = 'PRODUCT' AND f.sales_month = 'Aug 2027'
ORDER BY f.forecast_inr DESC
LIMIT 500
```"""
NO_ROWS = {"columns": ["product_code", "product_description", "sales_month", "period_start", "period_end",
                       "forecast_inr", "low_inr", "high_inr", "mape_pct", "data_to"], "rows": [], "truncated": False}
# the 18-Nov answer, word for word
NO_FORECAST_ANSWER = ("In sales month Aug 2027 (21-Jul-2027 to 20-Aug-2027), there was no sales forecast for "
                      "August 2027.")
FIXED_ANSWER = ("There is no product forecast for Aug 2027 (products are forecast only Nov 2026 to Jan 2027), but the "
                "total sales forecast for sales month Aug 2027 is about INR 53.7 Cr, likely between 46.8 Cr and "
                "60.7 Cr.")


def forecast_table():
    """What answer_verify.FORECAST_SQL reads from ml_sales_forecast (18-Nov, laptop): TOTAL Nov 2026 - Oct 2027,
    PRODUCT Nov 2026 - Jan 2027 (the products added up)."""
    total = [["TOTAL", *sales_month(2026, 11)[:2], Decimal("534887655.19"), Decimal("498487638.37"),
              Decimal("571287672.01")],
             ["TOTAL", *sales_month(2026, 12)[:2], Decimal("520192526.92"), Decimal("481252539.80"),
              Decimal("559132514.04")]]
    total += [["TOTAL", row[0], row[1], row[3], row[4], row[5]] for row in YEAR_ROWS["rows"]]
    products = [["PRODUCT", *sales_month(y, m)[:2], Decimal("91234567.00"), Decimal("80000000.00"),
                 Decimal("99000000.00")] for y, m in ((2026, 11), (2026, 12), (2027, 1))]
    return {"columns": ["level", "sales_month", "period_start", "forecast_inr", "low_inr", "high_inr"],
            "rows": total + products, "truncated": False}


@pytest.fixture
def ml(monkeypatch, mysql):  # noqa: F811
    """The fake MySQL with the ml_ tables allowed."""
    monkeypatch.setattr(warehouse, "allowed_tables", lambda: ALLOWED)
    return mysql


def result_of(sql, data, text="what will our sales be", understood=""):
    return agent.AskResult(text=text, status="ok", sql=sql, columns=data["columns"], rows=data["rows"],
                           truncated=data.get("truncated", False), understood_as=understood)


def last_message(call):
    return call[-1]["content"]


# ---------- check 1: the 18-Nov "no forecast for Aug 2027" ----------

def test_the_18_nov_no_forecast_answer_is_rewritten_once_with_the_total_forecast(monkeypatch, ml, user):
    ml.results = [NO_ROWS, forecast_table()]
    fake = use_fake_ai(monkeypatch, [(PRODUCT_SQL, 3000), (NO_FORECAST_ANSWER, 700), (FIXED_ANSWER, 900)])

    result = agent.ask(QUESTION, user)

    assert result.status == "ok" and result.answer == FIXED_ANSWER
    assert len(fake.calls) == 3                                    # SQL, answer, ONE rewrite
    rewrite = fake.calls[2]
    # the rewrite is the same answer request + the first answer + the exact correction
    assert rewrite[0]["content"] == agent.EXPLAIN_SYSTEM_PROMPT
    assert rewrite[1]["content"] == fake.calls[1][1]["content"]
    assert rewrite[2] == {"role": "assistant", "content": NO_FORECAST_ANSWER}
    correction = last_message(rewrite)
    assert rewrite[3]["role"] == "user"
    assert correction.startswith('Your answer says "there was no sales forecast for August 2027", but the forecast '
                                 "table ml_sales_forecast has the total sales forecast")
    assert "TOTAL Aug 2027 forecast 537,112,731.17 (about 53.7 Cr)" in correction
    assert "range 467,665,000.80 (about 46.8 Cr) to 606,560,461.54 (about 60.7 Cr)" in correction
    assert "Products are forecast only for Nov 2026 to Jan 2027." in correction
    assert correction.endswith("Rewrite the whole answer using only the rows and the facts and the numbers in this "
                               "message - in the same plain style.")
    # counted: both answer calls' tokens, the rewrite's time as its own step
    assert result.sql_tokens == 3000 and result.answer_tokens == 700 + 900
    assert "answer_fix" in result.step_secs
    assert "Rewrite the answer to match the data (AI)" in [step["label"] for step in result.time_steps]
    assert result.question.answer == FIXED_ANSWER and result.question.answer_tokens == 1600


def test_a_product_only_claim_on_a_question_without_products_also_gets_the_total(ml):
    """18-Nov (question 168): "no sales forecast records for products in Sep 2027" - right about the products, but the
    question asked for the sales forecast, and the TOTAL for Sep 2027 is there."""
    ml.results = [forecast_table()]
    result = result_of(PRODUCT_SQL.strip("`").replace("sql\n", ""), NO_ROWS, "can you give it for sep 2027",
                       "What is the sales forecast for September 2027?")
    answer = "There were no sales forecast records for products in sales month Sep 2027 (21-Aug-2027 to 20-Sep-2027)."

    correction, facts = answer_verify.problems(result, answer)

    assert "TOTAL Sep 2027 forecast 562,931,379.32 (about 56.3 Cr)" in correction and "562931379.32" in facts


def test_a_product_question_without_a_product_forecast_that_month_is_not_flagged(ml):
    result = result_of(PRODUCT_SQL, NO_ROWS, "forecast of each product for Aug 2027")
    answer = "There is no product forecast for Aug 2027 - products are forecast for Nov 2026 to Jan 2027."
    ml.results = [forecast_table()]

    assert answer_verify.problems(result, answer) == ("", "")


def test_the_rewrite_that_gives_the_total_passes_the_check_of_the_second_answer(ml):
    """The rewrite's "no product forecast for Aug 2027 ... the total is about 53.7 Cr" is right: its amounts are the
    correction's (agent.explain checks the second answer with them)."""
    ml.results = [forecast_table(), forecast_table()]
    result = result_of(PRODUCT_SQL, NO_ROWS, QUESTION)
    correction, facts = answer_verify.problems(result, NO_FORECAST_ANSWER)

    assert answer_verify.problems(result, FIXED_ANSWER, "", facts, correction) == ("", "")
    # the same amounts in a FIRST answer (no rows, no correction yet) would be invented
    assert "not in the rows or the facts: 53.7 Cr, 46.8 Cr, 60.7 Cr" in answer_verify.problems(result, FIXED_ANSWER)[0]


def test_a_no_data_claim_about_a_month_in_the_rows_is_flagged_with_the_row():
    result = result_of(PER_MONTH_SQL, YEAR_ROWS, "what is my 2027 total sales")
    answer = "Jan 2027 is about INR 54.6 Cr. There is no forecast for Aug 2027."

    correction, _facts = answer_verify.problems(result, answer)

    assert correction.startswith('Your answer says "There is no forecast for Aug 2027", but the rows show: '
                                 "sales_month Aug 2027, period_start 21-Jul-2027, period_end 20-Aug-2027, "
                                 "forecast_inr 537,112,731.17 (about 53.7 Cr)")


def test_a_query_with_rows_told_as_no_data_is_flagged():
    result = result_of(PER_MONTH_SQL, YEAR_ROWS)

    correction, _facts = answer_verify.problems(result, "The query returned no data for 2027.")

    assert "but the query returned 10 row(s) with data" in correction


@pytest.mark.parametrize("answer", [
    # months that are really not forecast, the actual sales of a forecast month, a month with no row
    "Sales months Jan 2027 to Oct 2027 are forecast; Nov and Dec 2027 are not forecast and have no actual sales yet.",
    "There is no forecast beyond Oct 2027.",
    "Actual sales for Aug 2027 are not available yet.",
    "Only Jan 2027 to Oct 2027 are forecast; no other month is forecast.",
    "There is no forecast for Nov 2027.",
])
def test_true_no_data_sentences_are_not_flagged(answer):
    assert answer_verify.problems(result_of(PER_MONTH_SQL, YEAR_ROWS), answer) == ("", "")


def test_a_name_without_a_row_in_that_month_is_not_flagged():
    """"Meridian had no sales in Sep 2026" while other customers did - that claim can be right."""
    data = {"columns": ["customer_name", "sales_month", "net_sales_inr"],
            "rows": [["Aurora Fluid Power Limited", "Aug 2026", Decimal("1730000.00")],
                     ["Meridian Hydraulics Limited", "Aug 2026", Decimal("747750.00")],
                     ["Aurora Fluid Power Limited", "Sep 2026", Decimal("1500000.00")]]}
    answer = ("Aurora Fluid Power Limited had INR 1,730,000.00 in Aug 2026 and INR 1,500,000.00 in Sep 2026, while "
              "Meridian Hydraulics Limited had no sales in Sep 2026.")

    assert answer_verify.problems(result_of("SELECT 1", data), answer) == ("", "")


# ---------- check 2: amounts ----------

FORECAST_IN_CR = ("Based on data up to 31-Oct-2026, sales months Jan 2027 to Oct 2027 of 2027 are forecast: Jan 2027 "
                  "about INR 54.6 Cr (range INR 50.2 Cr - 59.1 Cr), Feb 2027 about INR 53.97 Cr, Mar 2027 about INR "
                  "62.8 Cr (range 56.8 - 68.8 Cr, the highest), Jul 2027 about INR 50.0 Cr (the lowest) and Aug 2027 "
                  "INR 537,112,731.17 (about 53.7 Cr). Together the ten months come to about INR 558.3 Cr; Jan to Mar "
                  "2027 add up to about 171.4 Cr. Mar 2027 is about 12.8 Cr more than Jul 2027. The model's average "
                  "error is 4.16 %; Nov and Dec 2027 are not forecast.")


def test_a_correct_forecast_answer_in_crore_is_not_flagged():
    assert answer_verify.problems(result_of(PER_MONTH_SQL, YEAR_ROWS), FORECAST_IN_CR) == ("", "")


def test_an_invented_amount_is_flagged():
    answer = FORECAST_IN_CR.replace("Aug 2027 INR 537,112,731.17 (about 53.7 Cr)", "Aug 2027 about INR 75.0 Cr")

    correction, _facts = answer_verify.problems(result_of(PER_MONTH_SQL, YEAR_ROWS), answer)

    assert correction.startswith("This amount in your answer is not in the rows or the facts: 75.0 Cr. Give only "
                                 "amounts from the rows and the facts")
    assert "Rewrite the whole answer using only the rows and the facts - in the same plain style." in correction


RISK = {"columns": ["customer_name", "risk_score", "risk_level", "reason", "last_invoice_date",
                    "days_since_last_invoice", "sales_last_3m_inr", "sales_prev_3m_inr", "change_pct",
                    "lifetime_sales_inr", "data_to"],
        "rows": [["Aurora Fluid Power Limited", Decimal("100.00"), "High",
                  "No sales in the last 3 months (normally about INR 15,280,637 per 3 months); no invoice for 106 days "
                  "(usually every 7 days); 0 orders in the last 3 months (normally about 26)",
                  datetime.date(2026, 7, 17), 106, Decimal("0.00"), Decimal("4876303.50"), Decimal("-100.00"),
                  Decimal("119592664.50"), DATA_TO],
                 ["Sunrise Fluid Power Pvt Ltd", Decimal("100.00"), "High",
                  "No sales in the last 3 months (normally about INR 6,776,191 per 3 months); no invoice for 220 days "
                  "(usually every 7 days); 0 orders in the last 3 months (normally about 15)",
                  datetime.date(2026, 3, 25), 220, Decimal("0.00"), Decimal("0.00"), None, Decimal("45951561.50"),
                  DATA_TO],
                 ["Crescent Fluid Power LLP", Decimal("100.00"), "High", "No sales in the last 3 months",
                  datetime.date(2026, 4, 2), 212, Decimal("0.00"), Decimal("-10044.00"), Decimal("-100.00"),
                  Decimal("2450000.00"), DATA_TO]]}
RISK_SQL = "SELECT r.customer_name, r.risk_score FROM ml_customer_risk r ORDER BY r.risk_score DESC LIMIT 20"
RISK_TOTALS = ("Customer risk totals (worked out by the app): 118 High, 107 Medium, 633 Low - 858 customers scored; "
               "data up to 31-Oct-2026.")
RISK_ANSWER = ("Based on data up to 31-Oct-2026, there are 118 high-risk customers who might stop buying. Aurora "
               "Fluid Power Limited has had no sales for 106 days (normally about INR 15,280,637 per quarter) and "
               "Sunrise Fluid Power Pvt Ltd for 220 days (normally about INR 6,776,191 per quarter). The highest "
               "sales in the previous three months were INR 4,876,303.50 for Aurora Fluid Power Limited and the "
               "lowest a negative INR 10,044.00 for Crescent Fluid Power LLP; Aurora's lifetime sales are about "
               "INR 11.96 Cr.")
ALERTS = {"columns": ["alert_type", "invoice_number", "invoice_date", "customer_name", "value_inr", "typical_inr",
                      "score", "reason", "alerts"],
          "rows": [["Unusual price", "SSMI/D/2425/3672", datetime.date(2024, 9, 21), "Nilgiri Tech Industries Pvt. Ltd.",
                    Decimal("26827.50"), Decimal("38880.00"), Decimal("7.42"),
                    "Unit price 26,828 is 31% below this product's usual 38,880 (seen on 6 invoice lines)", 172],
                   ["Unusual price", "SSMI/D/2425/4379", datetime.date(2024, 10, 21),
                    "Crescent Tech Industries Limited", Decimal("1725.00"), Decimal("2449.49"), Decimal("7.01"),
                    "Unit price 1,725 is 30% below this product's usual 2,449 (seen on 8 invoice lines)", 172]]}
ALERTS_SQL = "SELECT a.alert_type, a.invoice_number FROM ml_invoice_alerts a ORDER BY a.score DESC LIMIT 20"
ALERTS_ANSWER = ("Based on data up to 31-Oct-2026, there are 172 invoice alerts to check, including 100 for unusual "
                 "prices, 60 for unusual quantities, and 12 for large credit notes. The top alert is invoice "
                 "SSMI/D/2425/3672 from 21-Sep-2024 for Nilgiri Tech Industries Pvt. Ltd., where the unit price of "
                 "INR 26,827.50 was 31% below the typical INR 38,880.00 - about INR 12,052.50 less.")
RUNOUT = {"columns": ["product_code", "product_description", "report_date", "stock_qty", "avg_daily_sales_qty",
                      "days_left", "runout_date", "status", "items_under_30_days"],
          "rows": [["FG00966", "Coolant pump GX-597-1B 3.7kW (415V 50Hz)", DATA_TO, Decimal("4.000"),
                    Decimal("0.600"), Decimal("6.7"), datetime.date(2026, 11, 6), "Under 30 days", Decimal("349")],
                   ["FG03877", "Hydraulic motor TX-549-1B 7.5kW (415V 50Hz)", DATA_TO, Decimal("6.000"),
                    Decimal("0.844"), Decimal("7.1"), datetime.date(2026, 11, 7), "Under 30 days", Decimal("349")]]}
RUNOUT_SQL = "SELECT r.product_code FROM ml_stock_runout r WHERE r.status IN ('Under 30 days') ORDER BY r.days_left"
RUNOUT_ANSWER = ("Based on the stock report of 31-Oct-2026, 349 items are under 30 days from running out of stock and "
                 "1,613 items are in the report. The earliest run-out date is 06-Nov-2026 for the Coolant pump "
                 "GX-597-1B 3.7kW (415V 50Hz) (FG00966), 6.7 days left - it would have run out already unless new "
                 "stock arrived. There are currently 0 items marked as out of stock.")
RUNOUT_TOTALS = ("Stock run-out totals (worked out by the app): 349 Under 30 days, 357 Under 90 days, 85 OK, "
                 "822 No recent sales - 1,613 items; stock report and data up to 31-Oct-2026.")
CUSTOMERS = {"columns": ["customer_name", "net_sales_inr"],
             "rows": [["Sakura Pump Japan Co., Ltd.", Decimal("521288475.00")],
                      ["Crescent Tech Industries Limited", Decimal("381505212.00")],
                      ["Lotus Hydraulics Limited", Decimal("193423327.00")]]}
CUSTOMERS_ANSWER = ("The top customer is Sakura Pump Japan Co., Ltd. with INR 52.13 Cr (INR 521,288,475.00), then "
                    "Crescent Tech Industries Limited with about INR 38.2 Cr and Lotus Hydraulics Limited with about "
                    "19.3 crore - together about INR 109.6 Cr; Sakura is about 13.98 Cr ahead of Crescent.")


@pytest.mark.parametrize("sql, data, facts, answer", [
    (RISK_SQL, RISK, RISK_TOTALS, RISK_ANSWER),
    (ALERTS_SQL, ALERTS, "Invoice alert totals (worked out by the app): 100 Unusual price, 60 Unusual quantity, "
                         "12 Large credit note - 172 alerts to check; data up to 31-Oct-2026.", ALERTS_ANSWER),
    (RUNOUT_SQL, RUNOUT, RUNOUT_TOTALS, RUNOUT_ANSWER),
    ("SELECT cu.customer_name FROM fact_invoice_lines il", CUSTOMERS, "", CUSTOMERS_ANSWER),
], ids=["risk", "alerts", "run-out", "top-customers"])
def test_real_answers_of_the_18_nov_chat_are_not_flagged(sql, data, facts, answer):
    assert answer_verify.problems(result_of(sql, data), answer, facts) == ("", "")


def test_a_count_of_the_whole_table_needs_the_totals_fact():
    """1,613 items is the run-out table's total (the app's fact): without that fact it is an unknown amount."""
    correction, _facts = answer_verify.problems(result_of(RUNOUT_SQL, RUNOUT), RUNOUT_ANSWER)

    assert "not in the rows or the facts: 1,613." in correction


# ---------- check 3: a *_pct column taken x 100 again (19-Nov) ----------
# 19-Nov: "Which products are bought together? Can we sell them as a bundle?" got "... appearing in 146 orders
# (support 48.16 %)" - support_pct 0.4816 is ALREADY a percent (146 of 30,317 orders = 0.48 %).
PAIRS_SQL = ("SELECT pp.product_a_code, pp.product_a_description, pp.product_b_code, pp.product_b_description, "
             "pp.orders_together, pp.support_pct, pp.confidence_pct, pp.lift FROM ml_product_pairs pp "
             "ORDER BY pp.orders_together DESC, pp.lift DESC LIMIT 10")
PAIRS = {"columns": ["product_a_code", "product_a_description", "product_b_code", "product_b_description",
                     "orders_together", "support_pct", "confidence_pct", "lift"],
         "rows": [["FG00580", "Coolant Unit HM-132-3A", "FG01116", "Procon Pump PR-317-3A", 146, Decimal("0.4816"),
                   Decimal("27.92"), Decimal("11.77")],
                  ["FG00542", "Gear Pump GX-210-2B", "FG01484", "Hydraulic motor TX-549-1B", 144, Decimal("0.4750"),
                   Decimal("60.98"), Decimal("1.98")]]}
PAIRS_ANSWER = ("The pair bought together most often is Coolant Unit (FG00580) with Procon Pump (FG01116), appearing "
                "in 146 orders (support {support}); of the orders with the Coolant Unit, {confidence} also had the "
                "Procon Pump (lift 11.77). Gear Pump (FG00542) with Hydraulic motor (FG01484) follows with 144 orders "
                "(confidence 60.98 %).")


def test_the_19_nov_support_taken_x_100_is_flagged():
    answer = PAIRS_ANSWER.format(support="48.16 %", confidence="27.92%")

    correction, facts = answer_verify.problems(result_of(PAIRS_SQL, PAIRS), answer)

    assert correction.startswith("support_pct 0.4816 is already a percent: write 0.48 %, not 48.16 %. Never "
                                 "multiply support_pct by 100.")
    assert "confidence_pct" not in correction and facts == ""   # 27.92 % and 60.98 % are right as they are
    assert "Rewrite the whole answer using only the rows and the facts - in the same plain style." in correction


@pytest.mark.parametrize("support, confidence", [
    ("0.48 %", "27.92 %"),           # the right answer
    ("0.4816%", "27.92%"),
    ("0.48 percent", "27.9 %"),
])
def test_percent_columns_written_as_they_are_are_not_flagged(support, confidence):
    answer = PAIRS_ANSWER.format(support=support, confidence=confidence)
    assert answer_verify.problems(result_of(PAIRS_SQL, PAIRS), answer) == ("", "")


def test_a_percent_x_100_is_not_flagged_when_it_is_a_real_value_of_the_rows_or_the_request():
    """48.16 is a real value of another *_pct cell (or of the request): then "48.16 %" can be right."""
    rows = {"columns": PAIRS["columns"], "rows": PAIRS["rows"] + [["FG00001", "Valve", "FG00002", "Seal", 20,
                                                                    Decimal("0.0660"), Decimal("48.16"), Decimal("3.10")]]}
    answer = PAIRS_ANSWER.format(support="48.16 %", confidence="27.92 %")

    assert answer_verify.problems(result_of(PAIRS_SQL, rows), answer) == ("", "")
    assert answer_verify.problems(result_of(PAIRS_SQL, PAIRS), answer, "pairs with a share above 48.16 %") == ("", "")


def test_every_wrong_value_of_a_column_is_named_in_one_sentence():
    answer = ("Coolant Unit with Procon Pump: support 48.16 %. Gear Pump with Hydraulic motor: support 47.5 %. "
              "Confidence 27.92 % and 60.98 %.")

    correction, _facts = answer_verify.problems(result_of(PAIRS_SQL, PAIRS), answer)

    assert correction.startswith("support_pct 0.4816 is already a percent: write 0.48 %, not 48.16 %; support_pct "
                                 "0.475 is already a percent: write 0.48 %, not 47.5 %. Never multiply support_pct "
                                 "by 100.")


def test_a_percent_x_100_of_another_pct_column_is_flagged_too():
    """Generic for any *_pct column, e.g. change_pct -0.5 (a fall of half a percent) told as "-50 %"."""
    data = {"columns": ["customer_name", "change_pct"], "rows": [["Aurora Fluid Power Limited", Decimal("-0.50")]]}

    correction, _facts = answer_verify.problems(result_of("SELECT 1", data), "Aurora's sales fell by 50 %.")

    assert correction.startswith("change_pct -0.5 is already a percent: write -0.50 %, not 50 %.")
    assert answer_verify.problems(result_of("SELECT 1", data), "Aurora's sales fell by 0.5 %.") == ("", "")


def test_percents_without_a_pct_column_are_never_checked():
    data = {"columns": ["customer_name", "share"], "rows": [["Aurora Fluid Power Limited", Decimal("0.4816")]]}
    assert answer_verify.problems(result_of("SELECT 1", data), "Aurora has a 48.16 % share.") == ("", "")


def test_the_corrections_own_wrong_percent_never_makes_a_still_wrong_rewrite_pass():
    """19-Nov gap: the rewrite was checked with the correction as known text, and the correction quotes the wrong
    "48.16 %" - so a rewrite that still wrote 48.16 % passed. The correction now counts only for the amounts."""
    result = result_of(PAIRS_SQL, PAIRS)
    correction, facts = answer_verify.problems(result, PAIRS_ANSWER.format(support="48.16 %", confidence="27.92 %"))
    still_wrong = "Coolant Unit (FG00580) with Procon Pump (FG01116) is the top pair: 146 orders, support 48.16 %."
    fixed = "Coolant Unit (FG00580) with Procon Pump (FG01116) is the top pair: 146 orders, support 0.48 %."

    assert "not 48.16 %" in correction
    assert answer_verify.problems(result, still_wrong, "", facts, correction)[0].startswith(
        "support_pct 0.4816 is already a percent: write 0.48 %, not 48.16 %.")
    assert answer_verify.problems(result, fixed, "", facts, correction) == ("", "")


def test_the_rewrite_that_still_multiplies_the_percent_is_logged_and_kept_once(monkeypatch, ml, caplog):
    first = PAIRS_ANSWER.format(support="48.16 %", confidence="27.92 %")
    still_wrong = "Coolant Unit (FG00580) with Procon Pump (FG01116) is the top pair: 146 orders, support 48.16 %."
    fake = use_fake_ai(monkeypatch, [first, still_wrong])

    answer = agent.explain(result_of(PAIRS_SQL, PAIRS, "Which products are bought together?"))

    assert answer == still_wrong and len(fake.calls) == 2              # one rewrite, never a loop
    assert "the rewritten answer still has a problem (kept) - support_pct 0.4816" in caplog.text


# ---------- check 4: the stock report date (19-Nov) ----------
# 19-Nov: "Which products have the most stock right now?" listed the quantities but never said they are the stock of
# the stock report of 31-Oct-2026 ("right now" = the newest stock report).
STOCK_SQL = ("SELECT sl.report_date, p.product_code, p.product_description, sl.cumulative_qty AS stock_qty "
             "FROM fact_stock_ledger sl JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id "
             "JOIN dim_products p ON p.product_id = sl.product_id WHERE t.movement_type = 'Closing balance' "
             "AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger) ORDER BY sl.cumulative_qty DESC "
             "LIMIT 10")
STOCK = {"columns": ["report_date", "product_code", "product_description", "stock_qty"],
         "rows": [[DATA_TO, "RM0128", "Cast iron housing blank 128", Decimal("800.000")],
                  [DATA_TO, "RM0135", "Cast iron housing blank 135", Decimal("725.000")],
                  [DATA_TO, "CO00070", "Packing tape 70", Decimal("705.000")]]}
STOCK_ANSWER = ("The items with the most stock are Cast iron housing blank 128 (RM0128) with 800 units, Cast iron "
                "housing blank 135 (RM0135) with 725 and Packing tape 70 (CO00070) with 705{date}.")


def test_a_stock_answer_without_the_report_date_is_sent_back():
    correction, facts = answer_verify.problems(result_of(STOCK_SQL, STOCK), STOCK_ANSWER.format(date=""))

    assert correction.startswith("Your answer does not say which stock report the numbers are from: the rows are "
                                 "from the stock report of 31-Oct-2026. Say it, e.g. \"As of the stock report "
                                 "31-Oct-2026, ...\"")
    assert facts == ""


@pytest.mark.parametrize("date", [" (stock report of 31-Oct-2026)", ", as of the stock report 31 October 2026",
                                  " as of October 31, 2026", " in the 2026-10-31 report", " on 31/10/2026"])
def test_a_stock_answer_that_names_the_report_date_is_not_flagged(date):
    assert answer_verify.problems(result_of(STOCK_SQL, STOCK), STOCK_ANSWER.format(date=date)) == ("", "")


def test_the_report_date_check_is_only_for_stock_ledger_rows_with_a_report_date():
    answer = STOCK_ANSWER.format(date="")
    no_date = {"columns": STOCK["columns"][1:], "rows": [row[1:] for row in STOCK["rows"]]}
    assert answer_verify.problems(result_of(STOCK_SQL, no_date), answer) == ("", "")      # no report_date column
    assert answer_verify.problems(result_of("SELECT 1", STOCK), answer) == ("", "")         # not fact_stock_ledger
    assert answer_verify.problems(result_of(STOCK_SQL, {"columns": STOCK["columns"], "rows": []}),
                                  "There is no stock.") == ("", "")                          # no rows


def test_a_stock_answer_is_rewritten_once_with_the_report_date(monkeypatch, ml):
    fixed = "As of the stock report 31-Oct-2026, " + STOCK_ANSWER.format(date="")[0].lower() + \
        STOCK_ANSWER.format(date="")[1:]
    fake = use_fake_ai(monkeypatch, [STOCK_ANSWER.format(date=""), fixed])

    answer = agent.explain(result_of(STOCK_SQL, STOCK, "Which products have the most stock right now?"))

    assert answer == fixed and len(fake.calls) == 2
    assert "the stock report of 31-Oct-2026" in last_message(fake.calls[1])


# ---------- the answer rules and the docs (19-Nov) ----------

def test_the_answer_rules_say_pct_columns_are_percents_and_stock_answers_name_the_report():
    """The answer writer reads EXPLAIN_SYSTEM_PROMPT for every data answer (not only ML ones)."""
    prompt = agent.EXPLAIN_SYSTEM_PROMPT
    assert "Columns ending in _pct are ALREADY percentages" in prompt and "never multiply them by 100" in prompt
    assert "lift is a plain ratio" in prompt
    assert ("Stock rows with a report_date column: ALWAYS say which stock report the numbers are from, e.g. \"As of "
            "the stock report 31-Oct-2026, ...\"") in prompt


# ---------- the flow: once, never a loop; only data answers ----------

def test_a_second_bad_answer_is_kept_and_never_sent_back_again(monkeypatch, ml, user, caplog):
    ml.results = [NO_ROWS, forecast_table(), forecast_table()]
    still_wrong = "There is still no forecast for Aug 2027."
    fake = use_fake_ai(monkeypatch, [PRODUCT_SQL, NO_FORECAST_ANSWER, still_wrong])

    result = agent.ask(QUESTION, user)

    assert len(fake.calls) == 3 and result.answer == still_wrong       # kept, no third answer call
    assert "the rewritten answer still has a problem (kept)" in caplog.text


def test_a_failed_rewrite_keeps_the_first_answer(monkeypatch, ml, user):
    from portal.tests.test_agent import api_error

    ml.results = [NO_ROWS, forecast_table()]
    use_fake_ai(monkeypatch, [PRODUCT_SQL, NO_FORECAST_ANSWER, api_error(400), api_error(400)])

    result = agent.ask(QUESTION, user)

    assert result.status == "ok" and result.answer == NO_FORECAST_ANSWER


def test_a_right_answer_costs_no_extra_call(monkeypatch, ml, user):
    ml.results = [YEAR_ROWS]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{PER_MONTH_SQL}\n```", FORECAST_IN_CR])

    result = agent.ask("what is my 2027 total sales", user)

    assert len(fake.calls) == 2 and result.answer == FORECAST_IN_CR and "answer_fix" not in result.step_secs


def test_a_documents_answer_is_never_checked(monkeypatch, mysql, user):  # noqa: F811
    use_pdf_hits(monkeypatch, PDF_HITS)
    answer = DOC_ANSWER + " There is no data for Aug 2027 and the limit is INR 9,876,543.21."
    fake = use_fake_ai(monkeypatch, ["documents", answer])

    result = agent.ask(DOC_QUESTION, user)

    assert result.status == "docs" and result.answer == answer and len(fake.calls) == 2


def test_only_data_answers_are_checked():
    data = result_of(PER_MONTH_SQL, YEAR_ROWS)
    assert answer_verify.applies(data)
    assert not answer_verify.applies(data, PDF_HITS)                     # a 'both' answer with PDF pieces
    for status in ("general", "docs", "memory", "nodata", "error"):  # general, documents, memory, check replies ...
        assert not answer_verify.applies(agent.AskResult(text="x", status=status))


# ---------- streaming: the first text is cleared, only the rewrite stays ----------

def test_streaming_clears_the_first_answer_and_streams_only_the_rewrite(monkeypatch, ml, signed_in):  # noqa: F811
    ml.results = [NO_ROWS, forecast_table()]
    fake = fake_ai(monkeypatch, [(PRODUCT_SQL, 3000), (NO_FORECAST_ANSWER, 700), (FIXED_ANSWER, 900)])

    _, events = stream(signed_in, QUESTION)

    assert kinds(events) == ["step", "token", "step", "reset", "token", "done"]
    at = next(i for i, e in enumerate(events) if e["type"] == "reset")
    assert events[at - 1] == {"type": "step", "label": "Rewrite the answer to match the data (AI)"}
    first = "".join(e["text"] for e in events[:at] if e["type"] == "token")
    second = "".join(e["text"] for e in events[at:] if e["type"] == "token")
    assert first == NO_FORECAST_ANSWER and second == FIXED_ANSWER
    assert events[-1]["card"]["answer"] == FIXED_ANSWER
    assert fake.streamed == [2, 3]
