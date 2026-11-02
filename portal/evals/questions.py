"""The golden set: questions people really asked (and new kinds), each with how to check its answer.

Keys of one item (see grading.py): id, question, must, should, must_have, must_not, allow, expect,
context = ids of earlier questions in the same chat (the item is then a follow-up).
Q.. = questions from the 09-Oct to 14-Oct evaluations, N.. = new kinds of questions (22-Oct on).
QUICK = the short set to ask after every docs or prompt change (about 100,000 Groq tokens).
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
NOP_FEB_2027 = "SELECT MIN(full_date), MAX(full_date) FROM dim_calendar WHERE nop_sales_month = 'Feb 2027'"
LATEST_REPORT = "SELECT MAX(report_date) FROM fact_stock_ledger"
CUSTOMER_FEB_2027 = """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE cu.customer_name LIKE '{name}' AND c.nop_sales_month = 'Feb 2027'"""
FY = ("FROM fact_invoice_lines il JOIN dim_calendar c ON il.invoice_date_id = c.date_id "
      "{join} WHERE c.financial_year = '2627'")
PROD = "JOIN dim_products p ON il.product_id = p.product_id"
CUST = "JOIN dim_customers cu ON il.customer_id = cu.customer_id"
LATEST_CLOSE = ("FROM fact_stock_ledger sl JOIN dim_stock_movement_types mt ON sl.movement_type_id = mt.movement_type_id "
                "JOIN dim_products p ON sl.product_id = p.product_id WHERE mt.movement_type = 'Closing balance' "
                "AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)")
MONTH = ("SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il JOIN dim_calendar c "
         "ON il.invoice_date_id = c.date_id WHERE c.nop_sales_month = '{m}'")

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
    {"id": "Q02", "question": "How much did Allied Castings buy in Feb 2027?",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
                WHERE cu.customer_name LIKE '%Allied Castings%' AND c.nop_sales_month = 'Feb 2027' GROUP BY cu.customer_name""",
     "should": NOP_FEB_2027},
    {"id": "Q17", "question": "What is our cost of goods sold now?",
     "must": """SELECT ROUND(SUM(-sl.transaction_value), 2) FROM fact_stock_ledger sl
                JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
                WHERE t.movement_type = 'COGS' AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)""",
     "should": LATEST_REPORT},
    {"id": "Q03", "question": "How much did Eastern Machine Tools buy in Feb 2027?",
     "must": CUSTOMER_FEB_2027.format(name="%Eastern Machine Tools%"), "should": NOP_FEB_2027},
    {"id": "Q31", "question": "What was the purchase value in the latest stock report?",
     "must": """SELECT ROUND(SUM(sl.transaction_value), 2) FROM fact_stock_ledger sl
                JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
                WHERE t.movement_type = 'Purchase' AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)""",
     "should": LATEST_REPORT},
    # 12-Oct: "last month" must come from TODAY (CURDATE), not from sorting the month names as text
    {"id": "Q45", "question": "what is the last month sales and which customer we got more revanu",
     "must": """WITH lm AS (SELECT p.nop_sales_period_start s, p.nop_sales_period_end e FROM dim_calendar t
                JOIN dim_calendar p ON p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY WHERE t.full_date = CURDATE()),
                cs AS (SELECT il.customer_id, SUM(il.net_taxable_value) v FROM fact_invoice_lines il
                JOIN lm ON il.invoice_date BETWEEN lm.s AND lm.e GROUP BY il.customer_id)
                SELECT (SELECT ROUND(SUM(v), 2) FROM cs), (SELECT ROUND(MAX(v), 2) FROM cs)""",
     "should": """SELECT p.nop_sales_period_start, p.nop_sales_period_end FROM dim_calendar t
                  JOIN dim_calendar p ON p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY
                  WHERE t.full_date = CURDATE()"""},
    # 13-Oct: Vishnu's own questions that went wrong (quarter dates, lowest month, since, Not given, category)
    {"id": "Q46", "question": "Which state had the highest net sales in the first quarter of FY 2026-27?",
     "must": """SELECT cu.state, ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_customers cu ON cu.customer_id = il.customer_id
                WHERE c.financial_year = '2627' AND c.fiscal_quarter = 1 GROUP BY cu.state ORDER BY 2 DESC LIMIT 1""",
     "must_have": ["30-jun-2026"], "must_not": ["31-mar-2027"]},
    {"id": "Q47", "question": "Show net sales month by month from Jan 2026 to Mar 2027, after credit notes and debit notes",
     "should": """SELECT ROUND(MIN(s), 2), ROUND(MAX(s), 2) FROM (SELECT SUM(il.net_taxable_value) s FROM fact_invoice_lines il
                  JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                  WHERE c.nop_sales_period_start >= '2025-12-21' AND c.nop_sales_period_end <= '2027-03-20'
                  GROUP BY c.nop_sales_month) x""",
     "must_have": ["21-dec-2025"], "must_not": ["01-jan-2026", "jul 2026 (", "july 2026"]},
    {"id": "Q48", "question": "Which customers bought from us between Jan 2026 and Jun 2026 but have bought nothing since Oct 2026?",
     "must": """SELECT 975200.00, 68000.00""",
     "must_have": ["21-sep-2026"],
     "must_not": ["lotus", "apex machine", "blue ridge", "granite", "unknown customer", "20-oct-2026"]},
    {"id": "Q49", "question": "Which product category sold the most quantity in FY 2026-27?",
     "must_have": ["trochoid pumps", "not classified"]},
    {"id": "Q50", "question": "How much did OEM customers buy compared to after-market customers in each quarter of FY 2026-27?",
     "should": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                  JOIN dim_calendar c ON c.date_id = il.invoice_date_id
                  WHERE c.financial_year = '2627' AND c.fiscal_quarter = 3 AND il.customer_type IS NULL""",
     "must_have": ["not given"]},
    {"id": "Q51", "question": "Which finished goods had no sales between 21-Dec-2026 and 20-Mar-2027?",
     "must": """SELECT COUNT(*) FROM dim_products p WHERE p.item_group = 'Finished goods' AND NOT EXISTS
                (SELECT 1 FROM fact_invoice_lines il WHERE il.product_id = p.product_id
                 AND il.invoice_date BETWEEN '2026-12-21' AND '2027-03-20')""",
     "must_have": ["21-dec-2026", "20-mar-2027"], "must_not": ["nop sales month mar 2027"]},
    {"id": "Q52", "question": "What was our total stock value on 20-Mar-2027, by warehouse?",
     "must": """SELECT ROUND(SUM(sl.cumulative_value), 2) FROM fact_stock_ledger sl JOIN dim_stock_movement_types t
                ON t.movement_type_id = sl.movement_type_id WHERE t.movement_type = 'Closing balance' AND sl.report_date = '2027-03-20'""",
     "must_have": ["warehouse"]},
    {"id": "Q53", "question": "Which items had the biggest increase in stock value between 20-Sep-2026 and 20-Mar-2027?",
     "must": "SELECT 11157980.13", "must_have": ["52"]},
    {"id": "Q54", "question": "Which items were in stock on 20-Mar-2027 but had no sales between 21-Sep-2026 and 20-Mar-2027?",
     "must_have": ["4,097", "872"], "must_not": ["ca0092", "test bench"]},
    {"id": "Q55", "question": "How many sales orders are still open, and what is their total value?",
     "must": "SELECT ROUND(SUM(total_amount), 2) FROM fact_sales_order_lines WHERE status = 'Open'",
     "must_have": ["before gst"]},
    {"id": "Q56", "question": "Which orders in FY 2026-27 had a delivery date more than 30 days after the order date",
     "must_not": ["delivered on"]},
    {"id": "Q57", "question": "What were our export sales in Japanese yen for each month of FY 2026-27, using that month's exchange rate?",
     "must_have": ["sep 2026"]},
    # 14-Oct: a question of its own in a chat must not take the earlier questions' month (13-Oct: Japan -> "No data")
    {"id": "Q58", "question": "give me sep 2026 revanue",
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id WHERE c.nop_sales_month = 'Sep 2026'"""},
    {"id": "Q59", "question": "give me product category wise total revenue in sep 2026", "context": ["Q58"],
     "must": """SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
                JOIN dim_calendar c ON c.date_id = il.invoice_date_id JOIN dim_products p ON p.product_id = il.product_id
                WHERE c.nop_sales_month = 'Sep 2026' GROUP BY p.product_category ORDER BY 1 DESC LIMIT 1"""},
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
    {"id": "Q63", "question": "“Quarter” is ambiguous (Q3, Q6, Q14). Q1 of FY 2026-27 could mean 1-Apr to 30-Jun-2026 or the "
                              "NOP months Apr–Jun (21-Mar to 20-Jun-2026). Check which one the app chose and whether it told "
                              "you. Both are reasonable, but choosing silently is a weakness.",
     "must_have": ["apr-2026", "30-jun-2026"]},
    {"id": "Q64", "question": "Credit and debit notes (Q4, Q5, Q9). Net sales should be invoices minus credit notes plus debit "
                              "notes. If a customer’s or territory’s total looks too high, ask “how much of that was credit "
                              "notes?” to find out whether the notes were left out.",
     "must": """SELECT ROUND(SUM(CASE WHEN document_type = 'INVOICE' THEN net_taxable_value ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN document_type = 'CREDIT_NOTE' THEN taxable_value ELSE 0 END), 2),
                ROUND(SUM(CASE WHEN document_type = 'DEBIT_NOTE' THEN net_taxable_value ELSE 0 END), 2),
                ROUND(SUM(net_taxable_value), 2) FROM fact_invoice_lines""",
     "must_not": ["lowest"]},
    {"id": "Q65", "question": "Exchange rate (Q20). The rates are monthly, so check whether the app matched each NOP month to "
                              "the correct rate month. Also confirm it converted net value and not net value plus GST.",
     "must_not": ["1.800000", "1.630000", "1.790000"]},
    {"id": "Q66", "question": "Q1 of FY 2026-27 means which dates - calendar dates or NOP months?",
     "must_have": ["apr-2026", "30-jun-2026"]},
    # 22-Oct: new kinds of questions, never asked before
    {"id": "N01", "question": "Which 5 products sold the most by quantity in FY 2026-27?",
     "must": f"""SELECT p.product_code, CAST(SUM(il.net_quantity) AS SIGNED) q {FY.format(join=PROD)}
                 GROUP BY p.product_code ORDER BY q DESC LIMIT 1"""},
    {"id": "N13", "question": "What were our top 5 products by sales value in FY 2026-27?",
     "must": f"""SELECT p.product_code, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=PROD)}
                 GROUP BY p.product_code ORDER BY v DESC LIMIT 1"""},
    {"id": "N14", "question": "who bought the most of the first one?", "context": ["N13"],
     "must": f"""SELECT cu.customer_name, ROUND(SUM(il.net_taxable_value), 2) v {FY.format(join=PROD + ' ' + CUST)}
                 AND p.product_code = 'FG03279' GROUP BY cu.customer_name ORDER BY v DESC LIMIT 1"""},
    {"id": "N02", "question": "Which state bought the most from us in FY 2026-27?",
     "must": "SELECT 'Telangana'",
     "should": f"""SELECT ROUND(SUM(il.net_taxable_value), 2) {FY.format(join=CUST)} AND cu.state = 'Telangana'"""},
    {"id": "N03", "question": "What is our average invoice value in FY 2026-27?",
     "must": f"""SELECT COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) {FY.format(join='')}""",
     "should": f"""SELECT ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value END)
                   / COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END), 2) {FY.format(join='')}"""},
    {"id": "N04", "question": "Compare sales of Jan 2027 with Dec 2026. How much did they change in percent?",
     "must": f"SELECT ({MONTH.format(m='Jan 2027')}), ({MONTH.format(m='Dec 2026')})",
     "should": f"SELECT ROUND((({MONTH.format(m='Jan 2027')}) - ({MONTH.format(m='Dec 2026')})) * 100 / ({MONTH.format(m='Dec 2026')}), 2)"},
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
     "must": f"SELECT 'Jan 2027', ({MONTH.format(m='Jan 2027')}), 'Sep 2026', ({MONTH.format(m='Sep 2026')})"},
    {"id": "N17", "question": "last month sales evlo? yaar top customer?",
     "must": """WITH lm AS (SELECT p.nop_sales_period_start a, p.nop_sales_period_end b FROM dim_calendar t
                JOIN dim_calendar p ON p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY WHERE t.full_date = CURDATE())
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
                WHERE il.invoice_date BETWEEN t.nop_sales_period_start AND CURDATE()""",
     "should": "SELECT nop_sales_period_start, CURDATE() FROM dim_calendar WHERE full_date = CURDATE()",
     "must_have": ["so far"]},
]

# after every docs or prompt change: one question of each main kind + the bugs fixed before
QUICK = ["Q38", "Q42", "Q43", "Q44", "Q45", "Q46", "Q51", "Q54", "Q55", "Q58", "N02", "N05", "N10", "N18", "N20"]
