"""Five general checks of 20-Nov, from the 95 golden questions on the local model (Qwen3.6-35B) - answers with the
right numbers but told wrong. None of them knows a question, a product, a customer, a month or a number:

A. a forecast amount written in full rupees ("INR 534,887,655.19") although the answer rule says "Write forecast
   amounts rounded in Cr": the answer is rewritten once (answer_verify check 7);
B. a list of products named without their codes (the rows have product_code FG01484, the answer only says "GCI
   TX-675-3A 0.4kW"): rewritten once (answer_verify check 8);
C. whole quantities shown as "31.000" in the rows the AI reads (and on the cards): now 31 (agent.format_value);
D. (SELECT ... LIMIT 1) UNION ALL SELECT ... ORDER BY ... ASC LIMIT 1 - in MySQL the last LIMIT cuts the WHOLE union
   (one row came back, the lowest month was called the highest): the SQL goes back to the AI (union_check.py);
E. one row's value called the total ("a total stock value of INR 466,320.00" = the first of 29 items, the real total
   is 2,811,795.75): rewritten once with the total worked out by our code (answer_verify check 9).
Right answers and right SQL are never flagged. The AI and MySQL are fakes (no Groq call, no local model).
Run with:  python -m pytest -q portal/tests/test_answer_format_checks.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import answer_verify, union_check
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.ask() saves a Question

DATA_TO = datetime.date(2026, 10, 31)


def result_of(sql, columns, rows, truncated=False, text="question"):
    return agent.AskResult(text=text, status="ok", sql=sql, columns=columns, rows=rows, truncated=truncated)


# ---------- A. a forecast amount in full rupees ----------

FORECAST_SQL = ("SELECT f.sales_month, f.period_start, f.period_end, ROUND(f.forecast_inr, 2) AS forecast_inr, "
                "ROUND(f.low_inr, 2) AS low_inr, ROUND(f.high_inr, 2) AS high_inr, f.mape_pct, f.data_to "
                "FROM ml_sales_forecast AS f WHERE f.level = 'TOTAL' AND f.sales_month = 'Nov 2026'")
FORECAST_COLUMNS = ["sales_month", "period_start", "period_end", "forecast_inr", "low_inr", "high_inr", "mape_pct",
                    "data_to", "actual_so_far_inr"]
FORECAST_ROWS = [["Nov 2026", datetime.date(2026, 10, 21), datetime.date(2026, 11, 20), Decimal("534887655.19"),
                  Decimal("498487638.37"), Decimal("571287672.01"), Decimal("4.16"), DATA_TO,
                  Decimal("189269525.00")]]
# the 20-Nov answer of the local model, word for word
RUPEES_ANSWER = ("Based on data up to 31-Oct-2026, the forecast for sales in Nov 2026 (21-Oct-2026 to 20-Nov-2026) is "
                 "INR 534,887,655.19, with a range between INR 498,487,638.37 and INR 571,287,672.01. The model used "
                 "is Holt-Winters with a mean absolute percentage error of 4.16%. So far, actual sales have reached "
                 "INR 189,269,525.00 as of 31-Oct-2026.")
CR_ANSWER = ("Based on data up to 31-Oct-2026, the forecast for sales month Nov 2026 (21-Oct-2026 to 20-Nov-2026) is "
             "about INR 53.5 Cr (range 49.8 - 57.1 Cr), with an average model error of 4.16 %. Actual sales so far are "
             "INR 189,269,525.00.")


def test_a_forecast_in_full_rupees_is_flagged_with_the_cr_form():
    correction, _facts = answer_verify.problems(result_of(FORECAST_SQL, FORECAST_COLUMNS, FORECAST_ROWS),
                                                RUPEES_ANSWER)

    assert ("Your answer writes forecast amounts in full rupees (INR 534,887,655.19, INR 498,487,638.37, "
            "INR 571,287,672.01). Write forecast amounts rounded in Cr as the answer rule says") in correction
    assert "INR 534,887,655.19 -> about INR 53.5 Cr" in correction
    assert "189,269,525" not in correction  # an actual is not a forecast: never part of this check


@pytest.mark.parametrize("answer", [
    CR_ANSWER,
    # the exact amount next to its Cr form is fine
    "The forecast for Nov 2026 is INR 534,887,655.19 (about 53.5 Cr), range about 49.8 Cr to 57.1 Cr.",
    "The forecast for Nov 2026 is about 53.49 crore, between 49.85 and 57.13 crore.",
])
def test_a_forecast_in_cr_is_not_flagged(answer):
    assert answer_verify.forecast_rupee_problems(result_of(FORECAST_SQL, FORECAST_COLUMNS, FORECAST_ROWS),
                                                 answer) == []


def test_full_rupees_of_a_query_without_the_forecast_table_are_not_this_check():
    sql = "SELECT c.sales_month, SUM(il.net_taxable_value) AS forecast_inr FROM fact_invoice_lines il"
    assert answer_verify.forecast_rupee_problems(result_of(sql, FORECAST_COLUMNS, FORECAST_ROWS), RUPEES_ANSWER) == []


def test_a_total_forecast_column_next_to_actual_rows_is_checked_too():
    """20-Nov N41: the forecast is repeated on every salesperson's row (total_forecast_inr)."""
    columns = ["sales_person_name", "actual_net_sales_inr", "total_forecast_inr", "low_inr", "high_inr"]
    rows = [["Divya Nair", Decimal("23832337.00"), Decimal("534887655.19"), Decimal("498487638.37"),
             Decimal("571287672.01")],
            ["Meera Shetty", Decimal("432740.00"), Decimal("534887655.19"), Decimal("498487638.37"),
             Decimal("571287672.01")]]
    sql = "SELECT ... FROM fact_invoice_lines il CROSS JOIN ml_sales_forecast f"
    answer = ("The total forecast is INR 534,887,655.19 (range about 49.8 Cr to 57.1 Cr); Divya Nair leads the "
              "actual sales with INR 23,832,337.00.")

    found = answer_verify.forecast_rupee_problems(result_of(sql, columns, rows), answer)

    assert len(found) == 1 and "(INR 534,887,655.19)" in found[0] and "23,832,337" not in found[0]


def test_a_full_rupee_forecast_is_rewritten_once_in_cr(monkeypatch, mysql):  # noqa: F811
    fake = use_fake_ai(monkeypatch, [RUPEES_ANSWER, CR_ANSWER])

    answer = agent.explain(result_of(FORECAST_SQL, FORECAST_COLUMNS, FORECAST_ROWS, text="next month's sales?"))

    assert answer == CR_ANSWER and len(fake.calls) == 2
    assert "Write forecast amounts rounded in Cr" in fake.calls[1][-1]["content"]


# ---------- B. products named without their codes ----------

TOP_SQL = ("SELECT p.product_code, p.product_description, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr "
           "FROM fact_invoice_lines il JOIN dim_products p ON p.product_id = il.product_id GROUP BY p.product_id "
           "ORDER BY net_sales_inr DESC LIMIT 3")
TOP_COLUMNS = ["product_code", "product_description", "net_sales_inr"]
TOP_ROWS = [["FG01484", "GCI TX-675-3A 0.4kW (415V 50Hz)", Decimal("106617050.00")],
            ["FG01116", "Procon Pump PR-317-3A 7.5kW (415V 50Hz)", Decimal("45777950.00")],
            ["FG01656", "Trochoid pump GX-280-1B 7.5kW (415V 50Hz)", Decimal("44293585.00")]]
NO_CODE_ANSWER = ("In FY 2026-27 so far, the top product by sales value was GCI TX-675-3A 0.4kW (415V 50Hz) with INR "
                  "106,617,050.00, then Procon Pump PR-317-3A 7.5kW (415V 50Hz) at INR 45,777,950.00 and Trochoid "
                  "pump GX-280-1B 7.5kW at INR 44,293,585.00.")
CODE_ANSWER = ("In FY 2026-27 so far, the top product by sales value was GCI TX-675-3A 0.4kW (FG01484) with INR "
               "106,617,050.00, then Procon Pump PR-317-3A 7.5kW (FG01116) at INR 45,777,950.00 and Trochoid pump "
               "GX-280-1B 7.5kW (FG01656) at INR 44,293,585.00.")
PAIRS_COLUMNS = ["product_a_code", "product_a_description", "product_b_code", "product_b_description",
                 "orders_together"]
PAIRS_ROWS = [["FG00580", "Coolant Unit HM-132-3A 0.75kW (415V 50Hz)", "FG01116",
               "Procon Pump PR-317-3A 7.5kW (415V 50Hz)", 146],
              ["FG00542", "YTH-PARTS TX-325-3A 2.2kW (415V 50Hz)", "FG01484", "GCI TX-675-3A 0.4kW (415V 50Hz)", 144]]


def test_products_named_without_codes_are_flagged():
    correction, _facts = answer_verify.problems(result_of(TOP_SQL, TOP_COLUMNS, TOP_ROWS), NO_CODE_ANSWER)

    assert ("Your answer names the products without their codes (GCI TX-675-3A 0.4kW, Procon Pump PR-317-3A 7.5kW, "
            "Trochoid pump GX-280-1B 7.5kW): give each product's code with its name, e.g. \"GCI TX-675-3A 0.4kW "
            "(FG01484)\" - the codes are in the product_code column of the rows.") in correction


def test_product_pairs_named_without_codes_are_flagged():
    """20-Nov N27: 'the Coolant Unit HM-132-3A 0.75kW and the Procon Pump PR-317-3A 7.5kW ...' - no code."""
    answer = ("The Coolant Unit HM-132-3A 0.75kW and the Procon Pump PR-317-3A 7.5kW are bought together most often "
              "(146 orders), then YTH-PARTS TX-325-3A 2.2kW with GCI TX-675-3A 0.4kW (144 orders).")
    sql = "SELECT * FROM ml_product_pairs pp ORDER BY pp.orders_together DESC LIMIT 2"

    found = answer_verify.product_code_problems(result_of(sql, PAIRS_COLUMNS, PAIRS_ROWS), answer)

    assert len(found) == 1 and '"Coolant Unit HM-132-3A 0.75kW (FG00580)"' in found[0]
    assert "product_a_code column" in found[0]


@pytest.mark.parametrize("columns, rows, answer", [
    (TOP_COLUMNS, TOP_ROWS, CODE_ANSWER),
    # codes for some products are enough (never a false alarm on a mostly right answer)
    (TOP_COLUMNS, TOP_ROWS, NO_CODE_ANSWER.replace("(415V 50Hz) with", "(FG01484) with", 1)),
    # the answer names no product of the rows (a summary)
    (TOP_COLUMNS, TOP_ROWS, "The top 3 products made INR 196,688,585.00 together."),
    # one product only (a single item's answer)
    (TOP_COLUMNS, TOP_ROWS[:1], "GCI TX-675-3A 0.4kW sold INR 106,617,050.00."),
    # the same product on every row (a filter, not a list of products)
    (TOP_COLUMNS, [["FG01484", "GCI TX-675-3A 0.4kW", Decimal("1.00")], ["FG01484", "GCI TX-675-3A 0.4kW",
                                                                       Decimal("2.00")]],
     "GCI TX-675-3A 0.4kW was sold twice."),
    # a customer code is not a product code
    (["customer_code", "customer_name", "net_sales_inr"],
     [["C00012", "Sakura Pump Japan Co., Ltd.", Decimal("1.00")], ["C00034", "Lotus Hydraulics Limited",
                                                                  Decimal("2.00")]],
     "Sakura Pump Japan Co., Ltd. and Lotus Hydraulics Limited are the top customers."),
], ids=["codes", "some-codes", "no-product-named", "one-row", "one-product", "customers"])
def test_answers_with_codes_or_without_a_product_list_are_not_flagged(columns, rows, answer):
    assert answer_verify.product_code_problems(result_of(TOP_SQL, columns, rows), answer) == []


# ---------- C. whole quantities without .000 ----------

@pytest.mark.parametrize("value, column, text", [
    (Decimal("31.000"), "units_on_open_orders", "31"),          # 20-Nov N62: was "31.000 units"
    (Decimal("191.000"), "units_in_stock", "191"),
    (Decimal("2462.000"), "orders_together", "2,462"),
    (Decimal("12.500"), "units_in_stock", "12.500"),            # a real decimal stays
    (Decimal("0.4816"), "support_pct", "0.4816"),
    (Decimal("466320.00"), "stock_value_inr", "466,320.00"),    # money keeps its 2 decimals
    (Decimal("1955500.00"), "net_sales_inr", "1,955,500.00"),
    (Decimal("18.000000"), "gst_rate", "18.00"),                # rates as before
    (Decimal("2462.000"), "net_quantity", "2,462"),             # quantities as before
])
def test_whole_numbers_with_three_zero_decimals_show_whole(value, column, text):
    assert agent.format_value(value, column)[0] == text


def test_the_rows_the_ai_reads_have_no_000():
    result = result_of("SELECT ...", ["product_code", "units_on_open_orders", "units_in_stock"],
                       [["FG00542", Decimal("31.000"), Decimal("191.000")]])

    table = agent.explain_values(result, agent.ROWS_FOR_ANSWER)["table"]

    assert "FG00542 | 31 | 191" in table and ".000" not in table


# ---------- D. a UNION whose last LIMIT cuts the whole union ----------

# the 20-Nov SQL of "Which month had our highest sales ever, and which had the lowest?", word for word
UNION_BAD = """(
  SELECT c.sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
  FROM fact_invoice_lines AS il JOIN dim_calendar AS c ON c.date_id = il.invoice_date_id
  GROUP BY c.sales_year, c.sales_period_no, c.sales_month
  ORDER BY net_sales_inr DESC
  LIMIT 1
)
UNION ALL
SELECT c.sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines AS il JOIN dim_calendar AS c ON c.date_id = il.invoice_date_id
GROUP BY c.sales_year, c.sales_period_no, c.sales_month
ORDER BY net_sales_inr ASC
LIMIT 1"""
UNION_GOOD = UNION_BAD.replace("UNION ALL\nSELECT", "UNION ALL\n(SELECT").replace("ASC\nLIMIT 1", "ASC\nLIMIT 1)")


@pytest.mark.parametrize("sql", [
    UNION_BAD,
    "(SELECT a FROM t ORDER BY a DESC LIMIT 1) UNION ALL SELECT a FROM t ORDER BY a LIMIT 1",
    "(SELECT a FROM t LIMIT 3) UNION SELECT a FROM u LIMIT 3",
    "(SELECT a FROM t LIMIT 1) UNION ALL (SELECT a FROM u LIMIT 1) UNION ALL SELECT a FROM v ORDER BY a LIMIT 1",
    "SELECT * FROM ((SELECT a FROM t ORDER BY a DESC LIMIT 1) UNION ALL SELECT a FROM t ORDER BY a LIMIT 1) x",
])
def test_a_union_cut_by_its_last_limit_is_found(sql):
    assert union_check.last_part_cuts_the_union(sql).endswith("row(s)")


@pytest.mark.parametrize("sql", [
    UNION_GOOD,
    # the whole union sorted and cut on purpose: no part has its own ORDER BY / LIMIT
    "SELECT a FROM t UNION ALL SELECT a FROM u ORDER BY a LIMIT 5",
    "(SELECT a FROM t) UNION ALL (SELECT a FROM u) ORDER BY a LIMIT 5",
    # each part cut in parentheses, then the guard's LIMIT 500 (or an ORDER BY) for the whole union
    "(SELECT a FROM t ORDER BY a LIMIT 1) UNION ALL (SELECT a FROM u ORDER BY a DESC LIMIT 1) LIMIT 500",
    "(SELECT a FROM t ORDER BY a LIMIT 1) UNION ALL (SELECT a FROM u ORDER BY a DESC LIMIT 1) ORDER BY a",
    # an ORDER BY alone after the last part only sorts - no row is lost
    "(SELECT a FROM t ORDER BY a LIMIT 1) UNION ALL SELECT a FROM u ORDER BY a LIMIT 500",
    "SELECT a FROM t ORDER BY a LIMIT 3",
    "not sql at all ( union",
])
def test_unions_cut_per_part_or_as_a_whole_are_not_flagged(sql):
    assert union_check.last_part_cuts_the_union(sql) == ""


def test_a_union_cut_by_its_last_limit_goes_back_to_the_ai_and_the_fixed_sql_runs(monkeypatch, mysql, user):  # noqa: F811
    mysql.results = [{"columns": ["sales_month", "net_sales_inr"],
                      "rows": [["Mar 2026", Decimal("534303216.00")], ["Apr 2024", Decimal("140960488.50")]],
                      "truncated": False}]
    fake = use_fake_ai(monkeypatch, [f"```sql\n{UNION_BAD}\n```", f"```sql\n{UNION_GOOD}\n```",
                                     "The highest month was Mar 2026 and the lowest Apr 2024."])

    result = agent.ask("Which month had our highest sales ever, and which had the lowest?", user)

    assert result.status == "ok" and result.tries == 2 and len(mysql.calls) == 1
    retry_message = fake.calls[1][-1]["content"]
    assert "MySQL applies its ORDER BY / LIMIT to the WHOLE union" in retry_message
    assert "only 1 row(s) of all the parts came back" in retry_message
    assert "Wrap each part in parentheses so its ORDER BY / LIMIT applies to that part only" in retry_message


# ---------- E. one row's value called the total ----------

STOCK_SQL = ("SELECT s.product_code, s.product_description, s.cumulative_qty AS stock_qty, ROUND(s.cumulative_value, "
             "2) AS stock_value_inr FROM fact_stock_ledger s ORDER BY s.cumulative_value DESC")
STOCK_COLUMNS = ["product_code", "product_description", "stock_qty", "stock_value_inr"]
STOCK_ROWS = [["FG01434", "Coolant Unit CP-294-1B 0.75kW (415V 50Hz)", Decimal("4.000"), Decimal("466320.00")],
              ["FG00818", "Hydraulic motor CP-541-2C 3.7kW (415V 50Hz)", Decimal("6.000"), Decimal("251334.00")],
              ["FG01010", "Coolant Unit HM-290-2C 2.2kW (415V 50Hz)", Decimal("2.000"), Decimal("7464.11")]]
STOCK_TOTAL = "725,118.11"  # 466,320.00 + 251,334.00 + 7,464.11
ONE_ROW_ANSWER = ("As of the stock report 31-Oct-2026, 3 finished goods have stock but no sales in the last 90 days, "
                  "with a total stock value of INR 466,320.00.")


@pytest.mark.parametrize("answer", [
    ONE_ROW_ANSWER,
    "These 3 items are worth INR 466,320.00 in all.",
    "Together, the stock of these items totals about INR 4.66 lakh.",
])
def test_one_rows_value_called_the_total_is_flagged_with_the_real_total(answer):
    correction, _facts = answer_verify.problems(result_of(STOCK_SQL, STOCK_COLUMNS, STOCK_ROWS), answer)

    assert "a total" in correction and "but that is one row's value of stock_value_inr (the row FG01434)" in correction
    assert f"the real total of stock_value_inr over all 3 rows (worked out by our code) is {STOCK_TOTAL}" in correction


@pytest.mark.parametrize("answer", [
    # the real total
    f"As of the stock report 31-Oct-2026, 3 finished goods have stock worth INR {STOCK_TOTAL} in total.",
    "As of the stock report 31-Oct-2026, the stock is worth about INR 7.25 lakh in all.",
    # the row's own total, said with its name
    "As of the stock report 31-Oct-2026, the Coolant Unit CP-294-1B holds a total stock value of INR 466,320.00.",
    "As of the stock report 31-Oct-2026, FG01434 has a total value of INR 466,320.00.",
    # a ranked value
    "As of the stock report 31-Oct-2026, the highest total stock value is INR 466,320.00.",
    # no total word
    "As of the stock report 31-Oct-2026, the biggest item is worth INR 466,320.00.",
])
def test_a_real_total_or_a_named_rows_total_is_not_flagged(answer):
    assert answer_verify.one_row_total_problems(result_of(STOCK_SQL, STOCK_COLUMNS, STOCK_ROWS), answer) == []


def test_a_total_row_a_cut_list_a_month_and_a_same_value_column_are_not_flagged():
    sql = "SELECT ... FROM fact_invoice_lines"
    # a ROLLUP total row: its value IS the total
    rows = [["North", Decimal("100000.00")], ["South", Decimal("50000.00")], ["Total", Decimal("150000.00")]]
    assert answer_verify.one_row_total_problems(result_of(sql, ["region", "net_sales_inr"], rows),
                                                "Total sales were INR 150,000.00.") == []
    # a list cut at the row limit: the shown rows are not all, their sum is no total
    assert answer_verify.one_row_total_problems(result_of(STOCK_SQL, STOCK_COLUMNS, STOCK_ROWS, truncated=True),
                                                ONE_ROW_ANSWER) == []
    # a month's own total ("Mar 2026 totalled ...")
    months = [["Mar 2026", Decimal("534303216.00")], ["Apr 2024", Decimal("140960488.50")]]
    assert answer_verify.one_row_total_problems(result_of(sql, ["sales_month", "net_sales_inr"], months),
                                                "Sales in March 2026 totalled INR 534,303,216.00.") == []
    # the same value on every row (a total repeated next to each row)
    same = [["A", Decimal("534887655.19")], ["B", Decimal("534887655.19")]]
    assert answer_verify.one_row_total_problems(result_of(sql, ["name", "total_forecast_inr"], same),
                                                "The total forecast is INR 534,887,655.19.") == []
    # a price is not summed
    prices = [["A", Decimal("4500.00")], ["B", Decimal("3900.00")]]
    assert answer_verify.one_row_total_problems(result_of(sql, ["item", "unit_price"], prices),
                                                "The total price is INR 4,500.00.") == []


def test_one_rows_total_is_rewritten_once_with_the_real_total(monkeypatch, mysql):  # noqa: F811
    fixed = (f"As of the stock report 31-Oct-2026, 3 finished goods have stock but no sales in the last 90 days, worth "
             f"INR {STOCK_TOTAL} in total; the largest is Coolant Unit CP-294-1B (FG01434) at INR 466,320.00.")
    fake = use_fake_ai(monkeypatch, [ONE_ROW_ANSWER, fixed])

    answer = agent.explain(result_of(STOCK_SQL, STOCK_COLUMNS, STOCK_ROWS, text="unsold stock worth?"))

    assert answer == fixed and len(fake.calls) == 2
    assert f"is {STOCK_TOTAL}" in fake.calls[1][-1]["content"]
