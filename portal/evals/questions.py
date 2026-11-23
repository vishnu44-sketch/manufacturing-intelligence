"""The golden set: questions people really asked (and new kinds), each with how to check its answer.

Keys of one item (see grading.py): id, question, must, should, must_have, must_not, allow, expect,
context = ids of earlier questions in the same chat (the item is then a follow-up),
mode = 'ml' for a question asked in an ML Insights chat (agent.ask(mode='ml')).
expect may be a list of statuses, e.g. ["general", "ok"] (either is right).
Q.. = questions from the 09-Oct to 14-Oct evaluations, N.. = new kinds of questions (22-Oct on;
N38-N63 = the 20-Nov role test: managing director, sales person, finance, manufacturing manager).
QUICK = the short set to ask after every docs or prompt change (about 100,000 Groq tokens).
ML_QUICK = the ML Insights set to ask before a demo (about 85,000 tokens).
"""

SAME_DATES = """WITH cv AS (
  SELECT MIN(CASE WHEN invoice_date < '2026-04-01' THEN invoice_date END) AS lf,
         MAX(CASE WHEN invoice_date < '2026-04-01' THEN invoice_date END) AS lt,
         MIN(CASE WHEN invoice_date >= '2026-04-01' THEN invoice_date END) AS tf,
         MAX(CASE WHEN invoice_date >= '2026-04-01' THEN invoice_date END) AS tt
  FROM fact_invoice_lines WHERE invoice_date BETWEEN '2025-04-01' AND '2027-03-31'),
w AS (SELECT GREATEST(lf, tf - INTERVAL 1 YEAR) AS ls, LEAST(lt, tt - INTERVAL 1 YEAR) AS le FROM cv),
t AS (SELECT SUM(CASE WHEN il.invoice_date BETWEEN w.ls AND w.le THEN il.net_taxable_value ELSE 0 END) AS ly,
             SUM(CASE WHEN il.invoice_date BETWEEN w.ls + INTERVAL 1 YEAR AND w.le + INTERVAL 1 YEAR
                      THEN il.net_taxable_value ELSE 0 END) AS ty
      FROM fact_invoice_lines il CROSS JOIN w {where})"""
STOPPED = """WITH l AS (SELECT MAX(invoice_date) - INTERVAL 3 MONTH AS cutoff FROM fact_invoice_lines),
p AS (SELECT il.customer_id, MAX(il.invoice_date) AS last_inv, SUM(il.net_taxable_value) AS s
      FROM fact_invoice_lines il WHERE il.customer_id <> -1 GROUP BY il.customer_id),
st AS (SELECT cu.customer_name, p.s FROM p JOIN dim_customers cu ON cu.customer_id = p.customer_id
       CROSS JOIN l WHERE p.last_inv < l.cutoff)"""
NEW_CUST = """WITH fy AS (SELECT MIN(full_date) AS a, MAX(full_date) AS b FROM dim_calendar WHERE financial_year = '2627'),
fi AS (SELECT customer_id, MIN(invoice_date) AS f FROM fact_invoice_lines WHERE customer_id <> -1 GROUP BY customer_id)
SELECT COUNT(DISTINCT fi.customer_id), ROUND(SUM(il.net_taxable_value), 2)
FROM fy JOIN fi ON fi.f BETWEEN fy.a AND fy.b
JOIN fact_invoice_lines il ON il.customer_id = fi.customer_id AND il.invoice_date BETWEEN fy.a AND fy.b"""
AUG_2026 = "SELECT MIN(full_date), MAX(full_date) FROM dim_calendar WHERE sales_month = 'Aug 2026'"
LATEST_REPORT = "SELECT MAX(report_date) FROM fact_stock_ledger"
CUSTOMER_AUG_2026 = """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE cu.customer_name LIKE '{name}' AND c.sales_month = 'Aug 2026'"""
FY = ("FROM fact_invoice_lines il JOIN dim_calendar c ON il.invoice_date_id = c.date_id "
      "{join} WHERE c.financial_year = '2627'")
PROD = "JOIN dim_products p ON il.product_id = p.product_id"
CUST = "JOIN dim_customers cu ON il.customer_id = cu.customer_id"
LATEST_CLOSE = ("FROM fact_stock_ledger sl JOIN dim_stock_movement_types mt ON sl.movement_type_id = mt.movement_type_id "
                "JOIN dim_products p ON sl.product_id = p.product_id WHERE mt.movement_type = 'Closing balance' "
                "AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)")
MONTH = ("SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il JOIN dim_calendar c "
         "ON il.invoice_date_id = c.date_id WHERE c.sales_month = '{m}'")
FORECAST = "FROM ml_sales_forecast WHERE level = 'TOTAL' ORDER BY period_start LIMIT {limit}"
FORECAST_2027 = ("FROM ml_sales_forecast WHERE level = 'TOTAL' AND period_end >= '2027-01-01' "
                 "AND period_start <= '2027-12-31'")
# 18-Nov: the answer writes a forecast in Cr ("about INR 53.7 Cr", agent.ML_RESULTS_NOTE), so the truth is that text
CR = "CONCAT(ROUND({col} / 10000000, 1))"
FORECAST_MONTH = "FROM ml_sales_forecast WHERE level = 'TOTAL' AND sales_month = '{m}'"
# the top customer of the newest complete sales month (the past actuals next to a month's forecast)
PAST_TOP_CUSTOMER = """SELECT cu.customer_name FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE il.customer_id <> -1 AND c.sales_month = (SELECT c2.sales_month FROM dim_calendar c2
  WHERE c2.sales_period_end <= (SELECT MAX(data_to) FROM ml_sales_forecast) ORDER BY c2.full_date DESC LIMIT 1)
GROUP BY cu.customer_id, cu.customer_name ORDER BY SUM(il.net_taxable_value) DESC LIMIT 1"""
NOT_ANSWERED = ["you can ask me", "could not write a working query"]
# 20-Nov role test: helpers of N38-N63
SP = "JOIN dim_sales_people sp ON il.sales_person_id = sp.sales_person_id"
NET_GST = ("ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN -1 ELSE 1 END * (COALESCE(il.igst_amount, 0) "
           "+ COALESCE(il.cgst_amount, 0) + COALESCE(il.sgst_amount, 0) + COALESCE(il.cess_amount, 0))), 2)")
# FY 2025-26's top 20 customers with no invoice in the last 3 months of the data (business rule 'stopped buying')
TOP20_FY2526_LAPSED = """WITH top20 AS (SELECT il.customer_id FROM fact_invoice_lines il
  JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.financial_year = '2526' AND il.customer_id <> -1
  GROUP BY il.customer_id ORDER BY SUM(il.net_taxable_value) DESC LIMIT 20),
lapsed AS (SELECT cu.customer_name, MAX(il.invoice_date) AS last_inv FROM top20 t
  JOIN fact_invoice_lines il ON il.customer_id = t.customer_id JOIN dim_customers cu ON cu.customer_id = t.customer_id
  GROUP BY cu.customer_id, cu.customer_name
  HAVING MAX(il.invoice_date) < (SELECT MAX(invoice_date) - INTERVAL 3 MONTH FROM fact_invoice_lines))"""
# closing stock value per item in the last two stock reports (items in both), drop = older - newer
STOCK_DROP = """WITH r2 AS (SELECT DISTINCT report_date FROM fact_stock_ledger ORDER BY report_date DESC LIMIT 2),
cb AS (SELECT sl.product_id, sl.report_date, sl.cumulative_value FROM fact_stock_ledger sl
  JOIN dim_stock_movement_types mt ON mt.movement_type_id = sl.movement_type_id
  WHERE mt.movement_type = 'Closing balance' AND sl.report_date IN (SELECT report_date FROM r2)),
d AS (SELECT a.product_id, a.cumulative_value - b.cumulative_value AS drop_value FROM cb a JOIN cb b
  ON b.product_id = a.product_id AND a.report_date = (SELECT MIN(report_date) FROM r2)
  AND b.report_date = (SELECT MAX(report_date) FROM r2))"""

ITEMS = [
    {"id": "Q38", "question": "what is last year and current year revenue",
     "must": """SELECT ROUND(SUM(CASE WHEN invoice_date < '2026-04-01' THEN net_taxable_value ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN invoice_date >= '2026-04-01' THEN net_taxable_value ELSE 0 END), 2)
                FROM fact_invoice_lines WHERE invoice_date BETWEEN '2025-04-01' AND '2027-03-31'""",
     "should": "SELECT MIN(invoice_date) FROM fact_invoice_lines"},
    {"id": "Q39", "question": "can i get above questions profit percentage also", "context": ["Q38"],
     "must": SAME_DATES.format(where="") + " SELECT ROUND((ty - ly) / NULLIF(ly, 0) * 100, 2) FROM t",
     "should": SAME_DATES.format(where="") + " SELECT ROUND(ly, 2), ROUND(ty, 2) FROM t",
     "must_have": ["profit"], "allow": ["profit"]},
    {"id": "Q40", "question": "and for export only?", "context": ["Q38", "Q39"],
     "must": SAME_DATES.format(where="WHERE il.sale_type = 'Export'") + " SELECT ROUND((ty - ly) / NULLIF(ly, 0) * 100, 2) FROM t",
     "should": SAME_DATES.format(where="WHERE il.sale_type = 'Export'") + " SELECT ROUND(ly, 2), ROUND(ty, 2) FROM t",
     "must_have": ["profit"], "allow": ["profit"]},
    {"id": "Q41", "question": "which customers stopped buying from us",
     "must": STOPPED + " SELECT (SELECT COUNT(*) FROM st), (SELECT customer_name FROM st ORDER BY s DESC LIMIT 1)",
     "should": "SELECT MAX(invoice_date) - INTERVAL 3 MONTH FROM fact_invoice_lines"},
    {"id": "Q42", "question": "in current year how many new customer and what is the revanu of those new customer",
     "must": NEW_CUST, "should": "SELECT MIN(invoice_date) FROM fact_invoice_lines", "allow": ["first invoice in this period"],
     "must_not": ["for this period starts", "data for this period", "this period starts"]},
    {"id": "Q43", "question": "what is our profit margin this year", "expect": "nodata", "allow": ["profit"]},
    {"id": "Q44", "question": "How many items have zero stock right now?",
     "must": """SELECT SUM(sl.cumulative_qty = 0) FROM fact_stock_ledger sl
                JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
                WHERE t.movement_type = 'Closing balance' AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)""",
     "should": LATEST_REPORT},
    {"id": "Q02", "question": "How much did Allied Castings buy in Aug 2026?",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
                WHERE cu.customer_name LIKE '%Allied Castings%' AND c.sales_month = 'Aug 2026' GROUP BY cu.customer_name""",
     "should": AUG_2026},
    {"id": "Q17", "question": "What is our cost of goods sold now?",
     "must": """SELECT ROUND(SUM(-sl.transaction_value), 2) FROM fact_stock_ledger sl
                JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
                WHERE t.movement_type = 'COGS' AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)""",
     "should": LATEST_REPORT},
    {"id": "Q03", "question": "How much did Eastern Machine Tools buy in Aug 2026?",
     "must": CUSTOMER_AUG_2026.format(name="%Eastern Machine Tools%"), "should": AUG_2026},
    {"id": "Q31", "question": "What was the purchase value in the latest stock report?",
     "must": """SELECT ROUND(SUM(sl.transaction_value), 2) FROM fact_stock_ledger sl
                JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
                WHERE t.movement_type = 'Purchase' AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)""",
     "should": LATEST_REPORT},
    # 12-Oct: "last month" must come from TODAY (CURDATE), not from sorting the month names as text
    {"id": "Q45", "question": "what is the last month sales and which customer we got more revanu",
     "must": """WITH lm AS (SELECT p.sales_period_start s, p.sales_period_end e FROM dim_calendar t
                JOIN dim_calendar p ON p.full_date = t.sales_period_start - INTERVAL 1 DAY WHERE t.full_date = CURDATE()),
                cs AS (SELECT il.customer_id, SUM(il.net_taxable_value) v FROM fact_invoice_lines il
                JOIN lm ON il.invoice_date BETWEEN lm.s AND lm.e GROUP BY il.customer_id)
                SELECT (SELECT ROUND(SUM(v), 2) FROM cs), (SELECT ROUND(MAX(v), 2) FROM cs)""",
     "should": """SELECT p.sales_period_start, p.sales_period_end FROM dim_calendar t
                  JOIN dim_calendar p ON p.full_date = t.sales_period_start - INTERVAL 1 DAY
                  WHERE t.full_date = CURDATE()"""},
    # 13-Oct: Vishnu's own questions that went wrong (quarter dates, lowest month, since, Not given, category)
    {"id": "Q46", "question": "Which state had the highest net sales in the first quarter of FY 2026-27?",
     "must": """SELECT cu.state, ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
                WHERE c.financial_year = '2627' AND c.fiscal_quarter = 1 GROUP BY cu.state ORDER BY 2 DESC LIMIT 1""",
     "must_have": ["30-jun-2026"], "must_not": ["31-mar-2027"]},
    {"id": "Q47", "question": "Show net sales month by month from Jan 2026 to Oct 2026, after credit notes and debit notes",
     "should": """SELECT ROUND(MIN(s), 2), ROUND(MAX(s), 2) FROM (SELECT SUM(il.net_taxable_value) s FROM fact_invoice_lines il
                  JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                  WHERE c.sales_period_start >= '2025-12-21' AND c.sales_period_end <= '2026-10-20'
                  GROUP BY c.sales_month) x""",
     "must_have": ["21-dec-2025"], "must_not": ["01-jan-2026"]},
    {"id": "Q48", "question": "Which customers bought from us between Jan 2026 and Jun 2026 but have bought nothing since Oct 2026?",
     "must": """SELECT 23158082.50""",
     "must_have": ["21-sep-2026"],
     "must_not": ["unknown customer", "20-oct-2026"]},
    {"id": "Q49", "question": "Which product category sold the most quantity in FY 2026-27?",
     "must_have": ["yth-parts", "not classified"]},
    {"id": "Q50", "question": "How much did OEM customers buy compared to after-market customers in each quarter of FY 2026-27?",
     "should": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                  JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                  WHERE c.financial_year = '2627' AND c.fiscal_quarter = 3 AND il.customer_type IS NULL""",
     "must_have": ["not given"]},
    # 23-Nov: a sale = an INVOICE line, as in N48 / N58 (a finished good whose only line in the period is a credit
    # note had no sales; with any line it was 730 - the model's 731 was the business rule's reading)
    {"id": "Q51", "question": "Which finished goods had no sales between 01-May-2026 and 31-Oct-2026?",
     "must": """SELECT COUNT(*) FROM dim_products p WHERE p.item_group = 'Finished goods' AND NOT EXISTS
                (SELECT 1 FROM fact_invoice_lines il WHERE il.product_id = p.product_id
                 AND il.document_type = 'INVOICE' AND il.invoice_date BETWEEN '2026-05-01' AND '2026-10-31')""",
     "must_have": ["01-may-2026", "31-oct-2026"], "must_not": ["21-apr-2026"]},
    {"id": "Q52", "question": "What was our total stock value on 31-Oct-2026, by warehouse?",
     "must": """SELECT ROUND(SUM(sl.cumulative_value), 2) FROM fact_stock_ledger sl JOIN dim_stock_movement_types t
                ON t.movement_type_id = sl.movement_type_id WHERE t.movement_type = 'Closing balance' AND sl.report_date = '2026-10-31'""",
     "must_have": ["warehouse"]},
    {"id": "Q53", "question": "Which items had the biggest increase in stock value between 30-Jun-2026 and 31-Oct-2026?",
     "must": "SELECT 3653840.77", "must_have": ["1,604"]},
    {"id": "Q54", "question": "Which items were in stock on 31-Oct-2026 but had no sales between 01-May-2026 and 31-Oct-2026?",
     "must_have": ["820", "793"], "must_not": ["ca0092", "test bench"]},
    {"id": "Q55", "question": "How many sales orders are still open, and what is their total value?",
     "must": "SELECT ROUND(SUM(total_amount), 2) FROM fact_sales_order_lines WHERE status = 'Open' AND order_date <= CURDATE()",
     "must_have": ["before gst"]},
    {"id": "Q56", "question": "Which orders in FY 2026-27 had a delivery date more than 30 days after the order date",
     "must_not": ["delivered on"]},
    {"id": "Q57", "question": "What were our export sales in Japanese yen for each month of FY 2026-27, using that month's exchange rate?",
     "must_have": ["sep 2026"]},
    # 14-Oct: a question of its own in a chat must not take the earlier questions' month (13-Oct: Japan -> "No data")
    {"id": "Q58", "question": "give me sep 2026 revanue",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.sales_month = 'Sep 2026'"""},
    {"id": "Q59", "question": "give me product category wise total revenue in sep 2026", "context": ["Q58"],
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_products p ON p.product_id = il.product_id
                WHERE c.sales_month = 'Sep 2026' GROUP BY p.product_category ORDER BY 1 DESC LIMIT 1"""},
    {"id": "Q60", "question": "who is our top customer in japan", "context": ["Q58", "Q59"],
     "must": """SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_customers cu ON cu.customer_id = il.customer_id WHERE cu.country = 'Japan'
                GROUP BY cu.customer_id, cu.customer_name ORDER BY 2 DESC LIMIT 1""",
     "should": "SELECT MIN(invoice_date), MAX(invoice_date) FROM fact_invoice_lines",
     "must_not": ["sep 2026", "september"]},
    {"id": "Q61", "question": "top customer in bangalore", "context": ["Q58", "Q59", "Q60"],
     "must": """SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_customers cu ON cu.customer_id = il.customer_id WHERE cu.city = 'Bangalore'
                GROUP BY cu.customer_id, cu.customer_name ORDER BY 2 DESC LIMIT 1""",
     "should": "SELECT MIN(invoice_date), MAX(invoice_date) FROM fact_invoice_lines",
     "must_not": ["sep 2026", "september"]},
    {"id": "Q62", "question": "and for sep 2026?", "context": ["Q59", "Q60", "Q61"],
     "must_have": ["bangalore", "sep 2026", "21-aug-2026", "20-sep-2026"],
     "must_not": ["no data was found for this question"]},
    # 14-Oct: reviewer notes typed into the bot (quarter refused, credit-note list cut at 500, months out of order)
    # 20-Nov: Q63-Q65 were the review notes themselves; now the real questions the notes describe (same truths)
    # Q63: a quarter question must say which dates it used (1-Apr to 30-Jun-2026, not the sales months) without being asked
    {"id": "Q63", "question": "What were our net sales in Q1 of FY 2026-27?",
     "must_have": ["apr-2026", "30-jun-2026"]},
    # Q64: were the notes taken off net sales? (invoices - credit notes + debit notes = net sales)
    {"id": "Q64", "question": "Are credit notes and debit notes included in our net sales? How much were the invoices, "
                              "the credit notes and the debit notes?",
     "must": """SELECT ROUND(SUM(CASE WHEN document_type = 'INVOICE' THEN net_taxable_value ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN document_type = 'CREDIT_NOTE' THEN taxable_value ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN document_type = 'DEBIT_NOTE' THEN net_taxable_value ELSE 0 END), 2),
                ROUND(SUM(net_taxable_value), 2) FROM fact_invoice_lines""",
     "must_not": ["lowest"]},
    # Q65: each sales month converted with its own rate month, on the value before GST (rates never as raw 1.800000)
    {"id": "Q65", "question": "What were our net sales before GST in Japanese yen for each sales month of FY 2026-27, "
                              "and which exchange rate was used for each month?",
     "must_not": ["1.800000", "1.630000", "1.790000"]},
    {"id": "Q66", "question": "Q1 of FY 2026-27 means which dates - calendar dates or sales months?",
     "must_have": ["apr-2026", "30-jun-2026"]},
    # 22-Oct: new kinds of questions, never asked before
    {"id": "N01", "question": "Which 5 products sold the most by quantity in FY 2026-27?",
     "must": f"""SELECT p.product_code, CAST(SUM(il.net_quantity) AS SIGNED) q {FY.format(join=PROD)}
                 GROUP BY p.product_code ORDER BY q DESC LIMIT 1"""},
    {"id": "N13", "question": "What were our top 5 products by sales value in FY 2026-27?",
     "must": f"""SELECT p.product_code, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=PROD)}
                 GROUP BY p.product_code ORDER BY v DESC LIMIT 1"""},
    # 20-Nov: "the first one" = N13's top product, found from the data (it was a fixed code that went stale)
    {"id": "N14", "question": "who bought the most of the first one?", "context": ["N13"],
     "must": f"""SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=PROD + ' ' + CUST)}
                 AND il.product_id = (SELECT il2.product_id FROM fact_invoice_lines il2
                   JOIN dim_calendar c2 ON il2.invoice_date_id = c2.date_id WHERE c2.financial_year = '2627'
                   GROUP BY il2.product_id ORDER BY SUM(il2.net_taxable_value) DESC LIMIT 1)
                 GROUP BY cu.customer_name ORDER BY v DESC LIMIT 1"""},
    {"id": "N02", "question": "Which state bought the most from us in FY 2026-27?",
     "must": "SELECT 'Telangana'",
     "should": f"""SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join=CUST)} AND cu.state = 'Telangana'"""},
    {"id": "N03", "question": "What is our average invoice value in FY 2026-27?",
     "must": f"""SELECT COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) {FY.format(join='')}""",
     "should": f"""SELECT ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value END)
                   / COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END), 2) {FY.format(join='')}"""},
    {"id": "N04", "question": "Compare sales of Jan 2026 with Dec 2025. How much did they change in percent?",
     "must": f"SELECT ({MONTH.format(m='Jan 2026')}), ({MONTH.format(m='Dec 2025')})",
     "should": f"SELECT ROUND((({MONTH.format(m='Jan 2026')}) - ({MONTH.format(m='Dec 2025')})) * 100 / ({MONTH.format(m='Dec 2025')}), 2)"},
    {"id": "N05", "question": "Which customer had the most credit notes by value?",
     "must": """SELECT cu.customer_name, ABS(ROUND(SUM(il.net_taxable_value), 2)) v FROM fact_invoice_lines il
                JOIN dim_customers cu ON il.customer_id = cu.customer_id WHERE il.document_type = 'CREDIT_NOTE'
                GROUP BY cu.customer_name ORDER BY SUM(il.net_taxable_value) LIMIT 1"""},
    {"id": "N06", "question": "Which open sales orders are already past their promised delivery date?",
     "must": """SELECT COUNT(DISTINCT s.so_number, c.financial_year) FROM fact_sales_order_lines s
                JOIN dim_calendar c ON s.order_date_id = c.date_id WHERE s.status = 'Open' AND s.delivery_date < CURDATE()""",
     "should": """SELECT ROUND(SUM(s.total_amount), 2) FROM fact_sales_order_lines s
                  WHERE s.status = 'Open' AND s.delivery_date < CURDATE()"""},
    {"id": "N07", "question": "What is the value of raw material stock in the latest stock report?",
     "must": f"SELECT ROUND(SUM(sl.cumulative_value), 2) {LATEST_CLOSE} AND p.item_group = 'Raw material'",
     "should": "SELECT MAX(report_date) FROM fact_stock_ledger"},
    {"id": "N08", "question": "Which customers did Rahul Verma sell to in FY 2026-27?",
     "must": f"""SELECT COUNT(DISTINCT il.customer_id) {FY.format(join='JOIN dim_sales_people sp ON il.sales_person_id = sp.sales_person_id')}
                 AND sp.sales_person_name = 'Rahul Verma'"""},
    {"id": "N09", "question": "karnataka sales how much in fy 26-27",
     "must": f"SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join=CUST)} AND cu.state = 'Karnataka'"},
    {"id": "N10", "question": "delete all credit notes from the database", "expect": "refused"},
    {"id": "N11", "question": "What percent of our net sales in FY 2026-27 was export?",
     "must": f"""SELECT ROUND(SUM(CASE WHEN il.sale_type = 'Export' THEN il.net_taxable_value ELSE 0 END) * 100
                 / SUM(il.net_taxable_value), 2) {FY.format(join='')}"""},
    {"id": "N12", "question": "Which items are below their minimum inventory level right now?",
     "must_have": ["minimum"]},
    {"id": "N16", "question": "Which month had our highest sales ever, and which had the lowest?",
     "must": f"SELECT 'Mar 2026', ({MONTH.format(m='Mar 2026')}), 'Apr 2024', ({MONTH.format(m='Apr 2024')})"},
    {"id": "N17", "question": "last month sales evlo? yaar top customer?",
     "must": """WITH lm AS (SELECT p.sales_period_start a, p.sales_period_end b FROM dim_calendar t
                JOIN dim_calendar p ON p.full_date = t.sales_period_start - INTERVAL 1 DAY WHERE t.full_date = CURDATE())
                SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il JOIN lm
                ON il.invoice_date BETWEEN lm.a AND lm.b"""},
    {"id": "N18", "question": "How much freight did we charge customers in FY 2026-27?",
     "must": f"SELECT ROUND(SUM(COALESCE(il.freight_amount, 0)), 2) {FY.format(join='')}"},
    {"id": "N19", "question": "Apart from India, which country bought the most from us in FY 2026-27?",
     "must": f"""SELECT cu.country, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=CUST)}
                 AND cu.country <> 'India' GROUP BY cu.country ORDER BY v DESC LIMIT 1"""},
    # 27-Oct: a period that is not over yet counts only up to today (the data has future-dated invoices)
    {"id": "N20", "question": "What are our sales this month so far?",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar t ON t.full_date = CURDATE()
                WHERE il.invoice_date BETWEEN t.sales_period_start AND CURDATE()""",
     "should": "SELECT sales_period_start, CURDATE() FROM dim_calendar WHERE full_date = CURDATE()",
     "must_have": ["so far"]},
    # 17-Nov: the ML results of run_ml (ml_* tables) - estimates, never "not in the data"
    {"id": "N21", "question": "What will our sales be next month?",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST.format(limit=1)}",
     "should": f"""SELECT {CR.format(col='low_inr')}, {CR.format(col='high_inr')}, period_start, period_end
                   {FORECAST.format(limit=1)}""",
     "must_have": ["forecast"]},
    {"id": "N22", "question": "What will our sales be in the next 3 months?",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST.format(limit=3)}",
     "must_have": ["forecast"]},
    {"id": "N23", "question": "What is the sales forecast for GCI TX-675 next month?",
     "must": """SELECT forecast_inr FROM ml_sales_forecast WHERE level = 'PRODUCT' AND product_code = 'FG01484'
                AND horizon_months = 1""",
     "should": """SELECT low_inr, high_inr FROM ml_sales_forecast WHERE level = 'PRODUCT' AND product_code = 'FG01484'
                  AND horizon_months = 1""",
     "must_have": ["forecast"]},
    {"id": "N24", "question": "Which customers might stop buying from us?",
     "must": "SELECT customer_name FROM ml_customer_risk ORDER BY risk_score DESC, lifetime_sales_inr DESC LIMIT 1",
     "should": "SELECT COUNT(*) FROM ml_customer_risk WHERE risk_level = 'High'",
     "must_have": ["risk"]},
    {"id": "N25", "question": "What customer groups do we have?",
     "must": "SELECT DISTINCT segment_name FROM ml_customer_segments",
     "must_have": ["group"]},
    {"id": "N26", "question": "Are there any unusual invoices?",
     "must": "SELECT invoice_number FROM ml_invoice_alerts ORDER BY score DESC LIMIT 1",
     "should": "SELECT COUNT(*) FROM ml_invoice_alerts",
     "must_have": ["unusual"]},
    {"id": "N27", "question": "Which products are bought together most often?",
     "must": "SELECT orders_together FROM ml_product_pairs ORDER BY orders_together DESC, lift DESC LIMIT 1",
     "should": """SELECT product_a_code, product_b_code FROM ml_product_pairs
                  ORDER BY orders_together DESC, lift DESC LIMIT 1"""},
    {"id": "N28", "question": "Which items will run out of stock soon?",
     "must": """SELECT product_code FROM ml_stock_runout WHERE status IN ('Under 30 days', 'Under 90 days')
                ORDER BY days_left, product_code LIMIT 1""",
     "should": "SELECT MAX(report_date) FROM ml_stock_runout"},
    # 18-Nov: the forecast goes 12 sales months ahead (Nov 2026 to Oct 2027) - a year names the forecast months in it
    {"id": "N29", "question": "What will our total sales be in 2027?",
     "must": f"""SELECT (SELECT sales_month {FORECAST_2027} ORDER BY period_start LIMIT 1),
                        (SELECT sales_month {FORECAST_2027} ORDER BY period_start DESC LIMIT 1)""",
     "should": f"SELECT data_to {FORECAST_2027} LIMIT 1",
     "must_have": ["not forecast"]},
    # 18-Nov: ML Insights questions a weaker model got wrong - a future month, customers in it (no forecast per
    # customer: the month's TOTAL forecast + the newest complete month's top customers as past actuals)
    {"id": "N30", "question": "my top customer in Aug 2027", "mode": "ml",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST_MONTH.format(m='Aug 2027')}",
     "should": PAST_TOP_CUSTOMER,
     "must_have": ["31-oct-2026", "customer"], "must_not": NOT_ANSWERED},
    {"id": "N31", "question": "predict sales for Aug 2027 and give me top 5 customers", "mode": "ml",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST_MONTH.format(m='Aug 2027')}",
     "should": PAST_TOP_CUSTOMER,
     "must_have": ["forecast"], "must_not": NOT_ANSWERED},
    {"id": "N32", "question": "What is the sales forecast for August 2027?", "mode": "ml",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST_MONTH.format(m='Aug 2027')}",
     "should": f"SELECT {CR.format(col='low_inr')}, {CR.format(col='high_inr')} {FORECAST_MONTH.format(m='Aug 2027')}",
     "must_not": NOT_ANSWERED + ["no forecast"]},
    {"id": "N33", "question": "can you give it for sep 2027", "context": ["N32"], "mode": "ml",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST_MONTH.format(m='Sep 2027')}",
     "should": f"SELECT {CR.format(col='low_inr')}, {CR.format(col='high_inr')} {FORECAST_MONTH.format(m='Sep 2027')}",
     "must_not": NOT_ANSWERED + ["no forecast"]},
    {"id": "N34", "question": "why is aurora on top?", "context": ["N24"], "mode": "ml", "expect": ["ok", "general"],
     "must": "SELECT days_since_last_invoice FROM ml_customer_risk WHERE customer_name = 'Aurora Fluid Power Limited'",
     "should": "SELECT last_invoice_date FROM ml_customer_risk WHERE customer_name = 'Aurora Fluid Power Limited'",
     "must_have": ["aurora"]},
    {"id": "N35", "question": "which products customers buy together?", "mode": "ml",
     "must": "SELECT orders_together FROM ml_product_pairs ORDER BY orders_together DESC, lift DESC LIMIT 1",
     "should": """SELECT product_a_code, product_b_code FROM ml_product_pairs
                  ORDER BY orders_together DESC, lift DESC LIMIT 1"""},
    {"id": "N36", "question": "which model you used for forecast and how accurate it is?", "mode": "ml",
     "expect": ["general", "ok"],
     "must": "SELECT DISTINCT mape_pct FROM ml_sales_forecast WHERE level = 'TOTAL'",
     "must_have": ["holt-winters"], "must_not": ["i've worked", "not in the ss manufacturing data"]},
    {"id": "N37", "question": "what does low_inr mean?", "context": ["N21"], "mode": "ml", "expect": ["general", "ok"],
     "must_have": ["range"], "must_not": ["not available", "by mistake"]},
    # 20-Nov: role test - questions as the managing director, a sales person, finance and the manufacturing manager
    # ask them (truths checked in MySQL on 20-Nov-2026, data to 31-Oct-2026)
    # -- managing director
    {"id": "N38", "question": "How did our sales grow quarter by quarter over the last two financial years?",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                WHERE c.financial_year = '2526' AND c.fiscal_quarter IN (3, 4)
                GROUP BY c.fiscal_quarter ORDER BY c.fiscal_quarter""",
     "should": "SELECT MIN(full_date), MAX(full_date) FROM dim_calendar WHERE financial_year = '2526' AND fiscal_quarter = 3"},
    {"id": "N39", "question": "How many customers make up half of our sales this financial year?",
     "must": f"""WITH cs AS (SELECT il.customer_id, SUM(il.net_taxable_value) v {FY.format(join='')}
                 AND il.customer_id <> -1 GROUP BY il.customer_id),
                 r AS (SELECT SUM(v) OVER (ORDER BY v DESC, customer_id ROWS UNBOUNDED PRECEDING) cum,
                       SUM(v) OVER () tot, ROW_NUMBER() OVER (ORDER BY v DESC, customer_id) n FROM cs)
                 SELECT MIN(n) FROM r WHERE cum >= tot / 2""",
     "should": "SELECT MAX(invoice_date) FROM fact_invoice_lines"},
    {"id": "N40", "question": "Are we on track to beat last year's total sales this financial year?",
     "must": SAME_DATES.format(where="") + " SELECT ROUND((ty - ly) / NULLIF(ly, 0) * 100, 2), ROUND(ty, 2) FROM t",
     "should": SAME_DATES.format(where="") + """ SELECT ROUND(ly, 2), (SELECT ROUND(SUM(il.net_taxable_value), 2)
               FROM fact_invoice_lines il JOIN dim_calendar c ON il.invoice_date_id = c.date_id
               WHERE c.financial_year = '2526') FROM t"""},
    {"id": "N41", "question": "How does the sales forecast for Nov 2026 compare with what we have actually sold in Nov 2026 so far?",
     "mode": "ml",
     "must": f"SELECT {CR.format(col='forecast_inr')} {FORECAST_MONTH.format(m='Nov 2026')}",
     "should": f"{MONTH.format(m='Nov 2026')} AND il.invoice_date <= CURDATE()",
     "must_have": ["forecast"], "must_not": NOT_ANSWERED},
    {"id": "N42", "question": "Which month of this financial year has been our best for sales so far?",
     "must": """SELECT c.sales_month, ROUND(SUM(il.net_taxable_value), 2) v FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.sales_year = '2627'
                GROUP BY c.sales_month ORDER BY v DESC LIMIT 1""",
     "should": "SELECT MIN(sales_period_start), MAX(sales_period_end) FROM dim_calendar WHERE sales_month = 'Oct 2026'"},
    # -- sales person
    {"id": "N43", "question": "Which of last year's top 20 customers have not bought anything in the last 3 months?",
     "must": f"{TOP20_FY2526_LAPSED} SELECT customer_name FROM lapsed",
     "should": f"{TOP20_FY2526_LAPSED} SELECT last_inv FROM lapsed"},
    {"id": "N44", "question": "Which sales person had the highest sales this year and how many customers did they sell to?",
     "must": f"""SELECT sp.sales_person_name, ROUND(SUM(il.net_taxable_value), 2) v,
                 COUNT(DISTINCT CASE WHEN il.customer_id <> -1 THEN il.customer_id END) {FY.format(join=SP)}
                 GROUP BY sp.sales_person_id, sp.sales_person_name ORDER BY v DESC LIMIT 1""",
     "should": "SELECT MAX(invoice_date) FROM fact_invoice_lines"},
    {"id": "N45", "question": "and how much did she sell in FY 2025-26?", "context": ["N44"],
     "must": f"""SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join=SP).replace("'2627'", "'2526'")}
                 AND sp.sales_person_name = 'Divya Nair'"""},
    {"id": "N46", "question": "What is the value of open sales orders that are still pending?",
     "must": """SELECT COUNT(DISTINCT s.so_number, c.financial_year), ROUND(SUM(s.total_amount), 2)
                FROM fact_sales_order_lines s JOIN dim_calendar c ON c.date_id = s.order_date_id
                WHERE s.status = 'Open' AND s.order_date <= CURDATE()""",
     "should": "SELECT COUNT(*), CURDATE() FROM fact_sales_order_lines WHERE status = 'Open' AND order_date <= CURDATE()",
     "must_have": ["before gst"]},
    {"id": "N47", "question": "How much have we sold in Nov 2026?",   # the sales month is not over and has data to 31-Oct only
     "must": f"{MONTH.format(m='Nov 2026')} AND il.invoice_date <= CURDATE()",
     "should": """SELECT (SELECT MIN(sales_period_start) FROM dim_calendar WHERE sales_month = 'Nov 2026'),
                         (SELECT MAX(invoice_date) FROM fact_invoice_lines)"""},
    {"id": "N48", "question": "How many of our active customers have not bought anything from us this financial year?",
     "must": """SELECT COUNT(*) FROM dim_customers cu WHERE cu.customer_id <> -1 AND cu.is_active = 'Y' AND NOT EXISTS
                (SELECT 1 FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                 WHERE il.customer_id = cu.customer_id AND c.financial_year = '2627' AND il.document_type = 'INVOICE')""",
     "should": "SELECT COUNT(*) FROM dim_customers WHERE customer_id <> -1 AND is_active = 'Y'"},
    {"id": "N49", "question": "How much did Bluefin Robotics buy from us this year?",   # no customer has that name
     "expect": ["ok", "nodata"], "must_have": ["found"]},
    {"id": "N50", "question": "Who is our biggest customer in Japan this financial year?",
     "must": f"""SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=CUST)}
                 AND cu.country = 'Japan' GROUP BY cu.customer_id, cu.customer_name ORDER BY v DESC LIMIT 1"""},
    # -- finance
    {"id": "N51", "question": "How much GST did we collect each month this financial year?",
     "must": f"""SELECT {NET_GST} FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                 WHERE c.sales_year = '2627' AND c.sales_month IN ('May 2026', 'Oct 2026')
                 GROUP BY c.sales_month, c.sales_period_no ORDER BY c.sales_period_no""",
     # the rule: a FY by sales month = sales_year, so Apr 2026 starts on 21-Mar-2026 (financial_year gives 42,890,074.00)
     "should": f"""SELECT MIN(c.sales_period_start), {NET_GST} FROM fact_invoice_lines il
                   JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.sales_month = 'Apr 2026'"""},
    {"id": "N52", "question": "How much did we invoice in foreign currency this year, and what is it in INR?",
     # every amount in ss_gold is INR (no invoice currency): foreign currency = export sales, graded on the INR value
     "must": f"SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join='')} AND il.sale_type = 'Export'"},
    {"id": "N53", "question": "What percent of sales came back as credit notes in each quarter of FY 2025-26?",
     "must": """SELECT ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN il.taxable_value ELSE 0 END) * 100
                / SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value ELSE 0 END), 2)
                FROM fact_invoice_lines il JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                WHERE c.financial_year = '2526' GROUP BY c.fiscal_quarter ORDER BY c.fiscal_quarter"""},
    {"id": "N54", "question": "How much of this year's sales is booked to an unknown customer?",
     "must": f"SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join='')} AND il.customer_id = -1"},
    {"id": "N55", "question": "How much money do our customers still owe us?", "expect": "nodata",
     "must_have": ["payment"]},
    {"id": "N56", "question": "How did export and domestic sales compare in FY 2025-26?",
     "must": f"""SELECT ROUND(SUM(CASE WHEN il.sale_type = 'Export' THEN il.net_taxable_value ELSE 0 END), 2),
                 ROUND(SUM(CASE WHEN il.sale_type = 'Domestic' THEN il.net_taxable_value ELSE 0 END), 2)
                 {FY.format(join='').replace("'2627'", "'2526'")}"""},
    {"id": "N57", "question": "What were our net sales in the calendar month of September 2026, 1st to 30th?",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.month_year = 'Sep 2026'""",
     "should": "SELECT MIN(full_date), MAX(full_date) FROM dim_calendar WHERE month_year = 'Sep 2026'"},
    # -- manufacturing manager
    {"id": "N58", "question": "Which finished goods have stock but no sales in the last 90 days, and what is that stock worth?",
     "must": f"""SELECT COUNT(*), ROUND(SUM(sl.cumulative_value), 2) {LATEST_CLOSE} AND sl.cumulative_qty > 0
                 AND p.item_group = 'Finished goods' AND NOT EXISTS (SELECT 1 FROM fact_invoice_lines il
                 WHERE il.product_id = sl.product_id AND il.document_type = 'INVOICE'
                 AND il.invoice_date BETWEEN sl.report_date - INTERVAL 90 DAY AND sl.report_date)""",
     "should": LATEST_REPORT},
    {"id": "N59", "question": "Which products' stock dropped the most between the last two stock reports?",
     "must": f"{STOCK_DROP} SELECT p.product_description FROM d JOIN dim_products p ON p.product_id = d.product_id "
             "ORDER BY d.drop_value DESC LIMIT 1",
     "should": f"{STOCK_DROP} SELECT ROUND(MAX(d.drop_value), 2), (SELECT MIN(report_date) FROM r2) FROM d"},
    {"id": "N60", "question": "What are the top 10 products by quantity sold this year, and how much stock do we have of each?",
     "must": f"""SELECT p.product_code, CAST(SUM(il.net_quantity) AS SIGNED) q {FY.format(join=PROD)}
                 GROUP BY p.product_code ORDER BY q DESC LIMIT 1""",
     "should": f"SELECT CAST(sl.cumulative_qty AS SIGNED), sl.report_date {LATEST_CLOSE} AND p.product_code = 'FG00542'"},
    {"id": "N61", "question": "Which raw material do we hold the most stock of by value right now?",
     "must": f"""SELECT p.product_description, ROUND(sl.cumulative_value, 2) {LATEST_CLOSE}
                 AND p.item_group = 'Raw material' ORDER BY sl.cumulative_value DESC LIMIT 1""",
     "should": LATEST_REPORT},
    {"id": "N62", "question": "How many units of FG00542 are on open sales orders, and how much of it do we have in stock?",
     "must": f"""SELECT (SELECT CAST(SUM(s.quantity) AS SIGNED) FROM fact_sales_order_lines s
                 JOIN dim_products op ON op.product_id = s.product_id WHERE op.product_code = 'FG00542'
                 AND s.status = 'Open' AND s.order_date <= CURDATE()),
                 CAST(sl.cumulative_qty AS SIGNED) {LATEST_CLOSE} AND p.product_code = 'FG00542'""",
     "should": LATEST_REPORT},
    {"id": "N63", "question": "What share of our FY 2025-26 sales came from Trochoid pumps?",
     "must": f"""SELECT ROUND(SUM(CASE WHEN p.product_category = 'Trochoid pumps' THEN il.net_taxable_value ELSE 0 END)
                 * 100 / SUM(il.net_taxable_value), 2) {FY.format(join=PROD).replace("'2627'", "'2526'")}""",
     "should": f"""SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join=PROD).replace("'2627'", "'2526'")}
                   AND p.product_category = 'Trochoid pumps'"""},
]

# after every docs or prompt change: one question of each main kind + the bugs fixed before
QUICK = ["Q38", "Q42", "Q43", "Q44", "Q45", "Q46", "Q51", "Q54", "Q55", "Q58", "N02", "N05", "N10", "N18", "N20"]
# before a demo of ML Insights (run_eval ml): a forecast, the risk list, the questions that failed on 18-Nov
ML_QUICK = ["N21", "N24", "N30", "N31", "N32", "N33", "N34", "N35", "N36", "N37"]
