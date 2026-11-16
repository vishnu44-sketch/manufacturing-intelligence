"""portal/sql_words.py: the SQL of an answer told in plain English (no AI, 0 tokens).

- The bar-chart SQL from the plan, a top-n, a WITH list, a stock query, LIKE name matches, UNION.
- A SQL it cannot read gives [] (the page then points to Show SQL).
- Never an exception: every example SQL of docs/sql_examples.md and every saved question's SQL.
"""
import re
from pathlib import Path

import pytest

from portal.lc.docs import load_docs
from portal.sql_words import describe_sql

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def example_sqls():
    """The ```sql blocks of the 'example' chunks of docs/sql_examples.md."""
    sqls = []
    for chunk in load_docs(DOCS_DIR):
        if chunk["kind"] == "example":
            sqls.extend(m.group(1).strip() for m in re.finditer(r"```sql\s*\n(.*?)```", chunk["text"], re.S))
    return sqls


def check_shape(sentences):
    """Short plain sentences: a list of strings, each one ending with a full stop, at most 10."""
    assert isinstance(sentences, list)
    assert 1 <= len(sentences) <= 10
    for s in sentences:
        assert isinstance(s, str) and s.strip() == s and s[0].isupper() and s.endswith(".")
        assert "  " not in s
    assert len(set(sentences)) == len(sentences)  # never the same sentence twice


BAR_CHART_SQL = """
SELECT c.sales_month, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_month IN ('Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026', 'Oct 2026')
  AND il.invoice_date <= CURRENT_DATE
GROUP BY c.sales_month
ORDER BY MIN(c.sales_period_start)
LIMIT 5
"""


def test_bar_chart_sql_in_plain_words():
    assert describe_sql(BAR_CHART_SQL) == [
        "Took the invoice lines (sales, credit and debit notes).",
        "Matched each line to its date in the calendar.",
        "Kept the sales months Jun 2026, Jul 2026, Aug 2026, Sep 2026 and Oct 2026.",
        "Kept the lines dated up to today.",
        "Added up the net value before GST (net sales) for each sales month.",
        "Showed the sales months oldest first, at most 5.",
    ]


def test_top_n_customers():
    sql = """SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) AS invoice_value_inr
             FROM fact_invoice_lines il
             JOIN dim_calendar c ON c.date_id = il.invoice_date_id
             JOIN dim_customers cu ON cu.customer_id = il.customer_id
             WHERE c.financial_year = '2627' AND il.sale_type = 'Export' AND cu.customer_id <> -1
             GROUP BY cu.customer_id, cu.customer_name
             ORDER BY invoice_value_inr DESC
             LIMIT 5"""
    assert describe_sql(sql) == [
        "Took the invoice lines (sales, credit and debit notes).",
        "Matched each line to its date in the calendar and its customer.",
        "Kept the financial year FY 2026-27.",
        "Kept only the export sales.",
        "Left out the Unknown customer.",
        "Added up the net value before GST (net sales) for each customer.",
        "Showed the top 5 customers by net sales.",
    ]


def test_with_period_list_is_told_first():
    sql = """WITH periods AS (
               SELECT DISTINCT c.sales_month, c.sales_period_start, c.sales_period_end
               FROM dim_calendar c
               WHERE c.sales_period_end <= CURRENT_DATE
               ORDER BY c.sales_period_end DESC
               LIMIT 6)
             SELECT p.sales_month, ROUND(COALESCE(SUM(il.net_taxable_value), 0), 2) AS sales_inr
             FROM periods p
             LEFT JOIN fact_invoice_lines il
                    ON il.invoice_date BETWEEN p.sales_period_start AND p.sales_period_end
             GROUP BY p.sales_month, p.sales_period_start
             ORDER BY p.sales_period_start"""
    out = describe_sql(sql)
    check_shape(out)
    assert out[0] == ("First made a list of periods from the calendar: kept the days whose sales month "
                      "ended up to today; sorted by end of the sales month, newest first, at most 6.")
    assert out[1] == "Took the list of periods."
    assert out[2] == "Matched each row to its invoice lines (also keeping rows with none)."
    assert "Added up the net value before GST (net sales) for each sales month." in out
    assert out[-1] == "Showed the sales months oldest first."


def test_stock_query():
    sql = """SELECT p.product_code, p.product_description, sl.cumulative_qty AS stock_qty,
                    sl.cumulative_value AS stock_value_inr
             FROM fact_stock_ledger sl
             JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
             JOIN dim_products p ON p.product_id = sl.product_id
             WHERE t.movement_type = 'Closing balance'
               AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)
             ORDER BY sl.cumulative_value DESC
             LIMIT 5"""
    assert describe_sql(sql) == [
        "Took the stock ledger (stock balances and movements).",
        "Matched each stock row to its kind of stock row and its product.",
        "Kept only the closing balance rows (stock on hand).",
        "Kept the latest stock report.",
        "Showed the product code, product, stock quantity and stock value.",
        "Showed the top 5 by stock value.",
    ]


def test_like_name_matches():
    sql = """SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
             FROM fact_invoice_lines il
             JOIN dim_customers cu ON cu.customer_id = il.customer_id
             JOIN dim_products p ON p.product_id = il.product_id
             WHERE cu.customer_name LIKE '%Allied Castings%' AND p.product_code LIKE 'FG%'
               AND p.product_category IS NULL
             GROUP BY cu.customer_name"""
    out = describe_sql(sql)
    check_shape(out)
    assert 'Kept the customer names containing "Allied Castings".' in out
    assert 'Kept the product codes starting with "FG".' in out
    assert "Kept the lines with no product category." in out


def test_union_parts():
    sql = """SELECT 'fact_invoice_lines' AS fact_table, COUNT(*) AS total_lines,
                    SUM(customer_id = -1) AS unknown_customer_lines
             FROM fact_invoice_lines
             UNION ALL
             SELECT 'fact_sales_order_lines', COUNT(*), SUM(customer_id = -1)
             FROM fact_sales_order_lines"""
    assert describe_sql(sql) == [
        "Put the results of 2 parts together, one below the other.",
        "Part 1: took the invoice lines (sales, credit and debit notes); counted the lines and the lines "
        "with an Unknown customer.",
        "Part 2: took the sales order lines; counted the order lines and the order lines with an Unknown "
        "customer.",
    ]


def test_credit_notes_and_case_split():
    sql = """SELECT c.financial_year_label,
                    ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value ELSE 0 END), 2) AS inv,
                    ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN il.net_taxable_value ELSE 0 END), 2) AS cn
             FROM fact_invoice_lines il
             JOIN dim_calendar c ON c.date_id = il.invoice_date_id
             WHERE il.document_type IN ('INVOICE', 'CREDIT_NOTE')
             GROUP BY c.financial_year, c.financial_year_label
             ORDER BY c.financial_year"""
    out = describe_sql(sql)
    assert "Kept only the invoices and credit notes." in out
    assert "Added up the net sales split into invoices and credit notes for each financial year." in out
    assert out[-1] == "Showed the financial years oldest first."


def test_having_not_like_and_or():
    sql = """SELECT sp.sales_person_name, AVG(s.unit_price) AS avg_price
             FROM fact_sales_order_lines s
             JOIN dim_sales_people sp ON sp.sales_person_id = s.sales_person_id
             WHERE (s.status = 'Open' OR s.status = 'Closed') AND sp.sales_person_name NOT LIKE '%Test%'
             GROUP BY sp.sales_person_name
             HAVING COUNT(*) > 10"""
    assert describe_sql(sql) == [
        "Took the sales order lines.",
        "Matched each order line to its sales person.",
        "Kept only the open orders or the closed orders.",
        'Left out the sales person names containing "Test".',
        "Averaged the unit price for each sales person.",
        "Then kept only the sales people with more than 10 order lines.",
    ]


@pytest.mark.parametrize("sql", [
    "", "   ", None, 42, "SELEC nothing FROM", "SELECT FROM WHERE (", "DROP TABLE dim_customers",
    "UPDATE dim_customers SET customer_name = 'x'", "hello, how are you?",
])
def test_unreadable_sql_gives_empty_list(sql):
    assert describe_sql(sql) == []


def test_every_example_sql_reads_without_error():
    sqls = example_sqls()
    assert len(sqls) >= 20  # the docs file really was read
    for sql in sqls:
        out = describe_sql(sql)
        check_shape(out)
        # no SQL words leak into the sentences
        for s in out:
            assert "SELECT" not in s and "fact_" not in s and "dim_" not in s, (sql, s)


@pytest.mark.django_db
def test_every_saved_question_sql_reads_without_error():
    from portal.models import Question

    sqls = list(Question.objects.exclude(sql="").values_list("sql", flat=True))
    if not sqls:
        pytest.skip("no saved questions with SQL in this database")
    for sql in sqls:
        out = describe_sql(sql)
        assert isinstance(out, list)
        if out:
            check_shape(out)
