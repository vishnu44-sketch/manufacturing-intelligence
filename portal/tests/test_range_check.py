"""A range in the answer that is not the rows' range (portal/answer_verify.py check 10, 23-Nov).

23-Nov (Groq): "okay create 2 line chart one for last 6 months sales and another line chart for last month days wise
sales" - the rows had both series in one column ('monthly' May-Oct 2026 and 'daily' 21-31 Oct 2026) and the answer
said "monthly net sales ranging from INR 459,457,491.70 in May 2026 to INR 517,494,492.75 in Oct 2026" - but the lowest
month was Jul 2026 (434,659,336.50). Now a range whose ends are values of one column but not its lowest and highest
(worked out per series) sends the answer back ONCE with the real lowest and highest; right ranges, ranges of a part
the sentence names, cut lists, percents and ranges over two columns are never flagged.
The AI and MySQL are fakes (no Groq call, no local model).
Run with:  python -m pytest -q portal/tests/test_range_check.py
"""
import datetime
from decimal import Decimal

import pytest

from portal import answer_verify
from portal.rag import agent
from portal.tests.test_agent import mysql, use_fake_ai  # noqa: F401

pytestmark = pytest.mark.django_db  # agent.explain() may save

SQL = "SELECT 'monthly' AS series, ... FROM fact_invoice_lines ... UNION ALL SELECT 'daily' AS series, ..."
COLUMNS = ["series", "period", "period_start", "period_end", "net_sales_inr"]


def _month(label, start, end, amount):
    return ["monthly", label, start, end, Decimal(amount)]


def _day(day, amount):
    date = datetime.date(2026, 10, day)
    return ["daily", agent.format_value(date)[0], date, date, Decimal(amount)]


# the real sales of the laptop database (sales months May-Oct 2026, days 21-31 Oct 2026 - no invoice on the 25th)
MONTHS = [_month("May 2026", datetime.date(2026, 4, 21), datetime.date(2026, 5, 20), "459457491.70"),
          _month("Jun 2026", datetime.date(2026, 5, 21), datetime.date(2026, 6, 20), "514347284.15"),
          _month("Jul 2026", datetime.date(2026, 6, 21), datetime.date(2026, 7, 20), "434659336.50"),
          _month("Aug 2026", datetime.date(2026, 7, 21), datetime.date(2026, 8, 20), "466556045.75"),
          _month("Sep 2026", datetime.date(2026, 8, 21), datetime.date(2026, 9, 20), "472683542.23"),
          _month("Oct 2026", datetime.date(2026, 9, 21), datetime.date(2026, 10, 20), "517494492.75")]
DAYS = [_day(21, "11592826.00"), _day(22, "14555036.00"), _day(23, "17611305.50"), _day(24, "15529002.00"),
        _day(26, "41466448.00"), _day(27, "13662908.50"), _day(28, "20957202.00"), _day(29, "17462856.50"),
        _day(30, "20823662.50"), _day(31, "15608278.00")]
ROWS = MONTHS + DAYS
# the 23-Nov answer: the range sentence word for word ("ranging from ... in May 2026 to ... in Oct 2026")
WRONG_ANSWER = ("The first chart shows monthly net sales ranging from INR 459,457,491.70 in May 2026 to "
                "INR 517,494,492.75 in Oct 2026. The second chart shows the daily net sales of the last month.")
RIGHT_ANSWER = ("The first chart shows monthly net sales ranging from INR 434,659,336.50 in Jul 2026 to "
                "INR 517,494,492.75 in Oct 2026. Daily net sales ranged from INR 11,592,826.00 on 21-Oct-2026 to "
                "INR 41,466,448.00 on 26-Oct-2026.")


def result_of(rows=ROWS, columns=COLUMNS, sql=SQL, truncated=False, text="2 line charts"):
    return agent.AskResult(text=text, status="ok", sql=sql, columns=columns, rows=rows, truncated=truncated)


# ---------- the real case ----------

def test_the_23_nov_monthly_range_is_flagged_with_the_real_lowest_month():
    told = answer_verify.range_problems(result_of(), WRONG_ANSWER)

    assert len(told) == 1
    assert "INR 459,457,491.70 to INR 517,494,492.75 is not the range of net_sales_inr of the series 'monthly'" \
        in told[0]
    assert "over its 6 rows the lowest is 434,659,336.50 (about 43.5 Cr) (Jul 2026)" in told[0]
    assert "the highest is 517,494,492.75 (about 51.7 Cr) (Oct 2026)" in told[0]
    assert "11,592,826" not in told[0]  # the daily rows are another series: never the monthly lowest


def test_the_whole_check_sends_the_wrong_range_back_with_the_correction():
    correction, _facts = answer_verify.problems(result_of(), WRONG_ANSWER)

    assert "the lowest is 434,659,336.50" in correction and correction.endswith("in the same plain style.")


def test_the_23_nov_answer_is_rewritten_once_with_the_true_range(monkeypatch, mysql):  # noqa: F811
    fake = use_fake_ai(monkeypatch, [WRONG_ANSWER, RIGHT_ANSWER])

    answer = agent.explain(result_of())

    assert answer == RIGHT_ANSWER and len(fake.calls) == 2
    assert "the lowest is 434,659,336.50" in fake.calls[1][-1]["content"]


def test_a_wrong_daily_range_is_flagged_within_the_daily_rows():
    answer = "Daily net sales ranged from INR 13,662,908.50 on 27-Oct-2026 to INR 41,466,448.00 on 26-Oct-2026."

    told = answer_verify.range_problems(result_of(), answer)

    assert len(told) == 1 and "series 'daily'" in told[0]
    assert "over its 10 rows the lowest is 11,592,826.00 (about 1.2 Cr) (21-Oct-2026)" in told[0]


@pytest.mark.parametrize("answer", [
    "Monthly net sales were between INR 459,457,491.70 and INR 517,494,492.75.",
    "Monthly net sales went from a low of INR 459,457,491.70 to a high of INR 517,494,492.75.",
    "The lowest month was May 2026 at INR 459,457,491.70 and the highest was Oct 2026 at INR 517,494,492.75.",
    "The highest month was Oct 2026 (INR 517,494,492.75) and the lowest May 2026 (INR 459,457,491.70).",
    "Monthly sales ranged from about 46.0 Cr to 51.7 Cr.",
    "Over the last 6 months, monthly net sales ranged from INR 459,457,491.70 to INR 517,494,492.75.",
])
def test_every_way_of_writing_the_wrong_range_is_flagged(answer):
    assert answer_verify.range_problems(result_of(), answer)


# ---------- never flagged ----------

@pytest.mark.parametrize("answer", [
    RIGHT_ANSWER,
    "Monthly sales ranged from about 43.5 Cr to 51.7 Cr.",
    "Monthly net sales ranged from INR 517,494,492.75 in Oct 2026 down to INR 434,659,336.50 in Jul 2026.",
    "The lowest month was Jul 2026 at INR 434,659,336.50 and the highest was Oct 2026 at INR 517,494,492.75.",
])
def test_the_true_range_is_not_flagged(answer):
    assert answer_verify.range_problems(result_of(), answer) == []


@pytest.mark.parametrize("answer", [
    # a part of the rows named apart from the range: Aug-Oct's lowest IS Aug
    "From Aug 2026 to Oct 2026, monthly net sales ranged from INR 466,556,045.75 to INR 517,494,492.75.",
    # the last 3 of 6 months
    "In the last 3 months, monthly sales ranged from INR 466,556,045.75 to INR 517,494,492.75.",
    "Excluding Jul 2026, monthly sales ranged from INR 459,457,491.70 to INR 517,494,492.75.",
    # a few months named (May, Aug and Oct): their range
    "Sales of May 2026, Aug 2026 and Oct 2026 ranged from INR 459,457,491.70 to INR 517,494,492.75.",
])
def test_a_range_over_a_part_the_sentence_names_is_not_flagged(answer):
    assert answer_verify.range_problems(result_of(), answer) == []


@pytest.mark.parametrize("answer", [
    # an amount that is in no row
    "Monthly net sales ranged from INR 400,000,000.00 to INR 517,494,492.75.",
    # one end daily, the other monthly: two series mixed - not checked
    "Net sales ranged from INR 13,662,908.50 to INR 517,494,492.75.",
    # a difference, not a range
    "The difference between INR 459,457,491.70 and INR 517,494,492.75 is about 5.8 Cr.",
    # a change, not a range
    "Monthly net sales rose from INR 459,457,491.70 in May 2026 to INR 517,494,492.75 in Oct 2026.",
    # the words after their amounts ("(the highest)", "(the lowest)"): the amount after "lowest" is another month's
    "Jun 2026 about INR 51.4 Cr (the highest), Jul 2026 about INR 43.5 Cr (the lowest) and May 2026 INR "
    "459,457,491.70.",
])
def test_ends_not_in_one_series_or_not_a_range_are_not_flagged(answer):
    assert answer_verify.range_problems(result_of(), answer) == []


def test_a_list_cut_at_the_row_limit_is_not_checked():
    assert answer_verify.range_problems(result_of(truncated=True), WRONG_ANSWER) == []


def test_percents_and_small_numbers_are_not_checked():
    columns = ["customer_name", "days_since_last_invoice", "change_pct", "sales_last_3m_inr"]
    rows = [["A", 106, Decimal("-40.00"), Decimal("120000.00")], ["B", 248, Decimal("-12.50"), Decimal("95000.00")],
            ["C", 90, Decimal("-75.25"), Decimal("80000.00")], ["D", 300, Decimal("-5.10"), Decimal("150000.00")]]
    result = result_of(rows, columns, sql="SELECT ... FROM ml_customer_risk")
    for answer in ("They have not been invoiced for periods ranging from 106 to 248 days.",
                   "Their sales fell by between 12.50 % and 40.00 %.",
                   "Changes ranged from 12.50% to 40.00%."):
        assert answer_verify.range_problems(result, answer) == []


def test_a_forecast_low_to_high_over_two_columns_is_not_flagged():
    columns = ["sales_month", "forecast_inr", "low_inr", "high_inr"]
    rows = [["Nov 2026", Decimal("534887655.19"), Decimal("498487638.37"), Decimal("571287672.01")],
            ["Dec 2026", Decimal("520192526.92"), Decimal("481252539.80"), Decimal("559132514.04")],
            ["Jan 2027", Decimal("546012345.00"), Decimal("502345678.00"), Decimal("591234567.00")]]
    result = result_of(rows, columns, sql="SELECT ... FROM ml_sales_forecast")
    answer = ("For Dec 2026 the forecast is about INR 52.0 Cr, ranging from INR 48.1 Cr to 55.9 Cr. Sales of Nov 2026 "
              "are likely between INR 498,487,638.37 and INR 571,287,672.01.")
    assert answer_verify.range_problems(result, answer) == []


def test_a_total_row_is_left_out_of_the_range():
    columns = ["region", "net_sales_inr"]
    rows = [["North", Decimal("100000.00")], ["South", Decimal("50000.00")], ["West", Decimal("70000.00")],
            ["Total", Decimal("220000.00")]]
    answer = "Regional sales ranged from INR 50,000.00 (South) to INR 100,000.00 (North)."
    assert answer_verify.range_problems(result_of(rows, columns), answer) == []


def test_customer_by_month_rows_are_checked_per_customer():
    columns = ["customer_name", "sales_month", "net_sales_inr"]
    rows = [["Sakura", "Aug 2026", Decimal("300000.00")], ["Sakura", "Sep 2026", Decimal("120000.00")],
            ["Sakura", "Oct 2026", Decimal("450000.00")], ["Meridian", "Aug 2026", Decimal("90000.00")],
            ["Meridian", "Sep 2026", Decimal("510000.00")], ["Meridian", "Oct 2026", Decimal("200000.00")]]
    result = result_of(rows, columns)
    # Sakura's own lowest and highest: right, although Meridian has a lower and a higher month
    assert answer_verify.range_problems(
        result, "Sakura's monthly sales ranged from INR 120,000.00 to INR 450,000.00.") == []
    told = answer_verify.range_problems(result, "Sakura's monthly sales ranged from INR 300,000.00 to INR 450,000.00.")
    assert len(told) == 1 and "customer_name 'Sakura'" in told[0] and "the lowest is 120,000.00" in told[0]
