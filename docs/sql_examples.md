# Example questions with their correct SQL (ss_gold, MySQL 8)

Each example: the question, the correct read-only SELECT, why it is written that way, and the key result
it returns on the data loaded on 17-Nov-2026 (invoices 02-Apr-2024 to 31-Oct-2026; checked as ss_ai_reader).
A newer load changes the totals: reuse the SQL pattern, never copy an Expected
number into an answer - every number in an answer must come from the rows the query returns.

## Q: What were net sales in each sales month of FY 2026-27?

Also asked as: monthly sales for FY 2026-27; month-wise net sales this financial year (sales months, 21st to 20th).

```sql
SELECT c.sales_month,
       MIN(c.sales_period_start) AS period_start,
       MAX(c.sales_period_end) AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_year = '2627'
GROUP BY c.sales_period_no, c.sales_month
ORDER BY c.sales_period_no;
```

Why: net sales = SUM(net_taxable_value) (credit notes already negative); a FY split by sales month filters sales_year so each month (21st to 20th) is complete.
Expected: 8 rows - Apr 2026 506,116,320.50; May 2026 459,457,491.70; Jun 2026 514,347,284.15; Jul 2026 434,659,336.50; Aug 2026 466,556,045.75; Sep 2026 472,683,542.23; Oct 2026 517,494,492.75; Nov 2026 189,269,525.00 (only 21-31 Oct: the data ends on 31-Oct-2026).

## Q: What was the sales value including freight in sales month Sep 2026?

Also asked as: sales incl. freight for Sep 2026; how much did we bill including freight and packing in that month.

```sql
SELECT MIN(c.sales_period_start) AS period_start,
       MAX(c.sales_period_end) AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,
       ROUND(SUM(COALESCE(il.freight_amount, 0)), 2) AS freight_inr,
       ROUND(SUM(il.net_taxable_value) + SUM(COALESCE(il.freight_amount, 0)), 2) AS sales_value_incl_freight_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_month = 'Sep 2026';
```

Why: sales value incl. freight = net_taxable_value + freight_amount (freight is NULL on credit notes); sales month 'Sep 2026' = 21-Aug-2026 to 20-Sep-2026.
Expected: 21-Aug-2026 to 20-Sep-2026: net sales 472,683,542.23 + freight 304,500.00 = 472,988,042.23.

## Q: Who were the top 5 customers by invoice value in Aug 2026?

Also asked as: biggest customers in August 2026; top customers by sales for the month Aug 2026.

```sql
SELECT cu.customer_name,
       ROUND(SUM(il.net_taxable_value), 2) AS invoice_value_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE c.sales_month = 'Aug 2026'
GROUP BY cu.customer_id, cu.customer_name
ORDER BY invoice_value_inr DESC
LIMIT 5;
```

Why: a month name means the sales month (21-Jul-2026 to 20-Aug-2026); invoice value = SUM(net_taxable_value); customer name from dim_customers.
Expected: Crescent Tech Industries Limited 16,264,499.50; Sakura Pump Japan Co., Ltd. 12,319,318.00; Delta Forgings LLP 9,405,952.50; Lotus Hydraulics Limited 9,392,120.00; Everest Tooling Limited 7,780,526.50.

## Q: What were the total net sales in each financial year?

Also asked as: yearly sales; FY-wise turnover after credit notes; annual revenue per financial year.

```sql
SELECT c.financial_year_label,
       MIN(il.invoice_date) AS data_from,
       MAX(il.invoice_date) AS data_to,
       ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value ELSE 0 END), 2) AS invoiced_inr,
       ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN il.net_taxable_value ELSE 0 END), 2) AS credit_notes_inr,
       ROUND(SUM(CASE WHEN il.document_type = 'DEBIT_NOTE' THEN il.net_taxable_value ELSE 0 END), 2) AS debit_notes_inr,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
GROUP BY c.financial_year, c.financial_year_label
ORDER BY c.financial_year;
```

Why: a FY total uses dim_calendar.financial_year (1-Apr to 31-Mar) of the invoice date; credit and debit notes count in the FY of the note date, so invoiced + credit notes (negative) + debit notes = net sales. data_from / data_to are the first and last invoice date of each FY in the data: the first FY starts with the data (invoices from 02-Apr-2024) and the current FY is not over, so the answer must say which dates each total covers.
Expected: FY 2024-25 net 4,412,464,971.85 (02-Apr-2024 to 31-Mar-2025; invoiced 4,415,883,077.00, credit notes -3,440,000.32, debit notes 21,895.17); FY 2025-26 net 5,169,611,634.51 (01-Apr-2025 to 31-Mar-2026); FY 2026-27 net 3,360,017,609.08 (01-Apr-2026 to 31-Oct-2026, the year is not over).

## Q: How many sales orders are open and what is their value?

Also asked as: order backlog; pending orders not yet invoiced; value of open orders.

```sql
SELECT COUNT(DISTINCT s.so_number, c.financial_year) AS open_orders,
       COUNT(*) AS open_order_lines,
       ROUND(SUM(s.total_amount), 2) AS open_value_before_gst_inr,
       ROUND(SUM(s.total_amount + s.tax_total), 2) AS open_value_incl_gst_inr,
       CURDATE() AS as_of_date
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
WHERE s.status = 'Open'
  AND s.order_date <= CURDATE();
```

Why: an order = so_number + financial year (SO numbers restart every FY); order value before GST = total_amount; only orders dated up to today (the data also has test orders dated after today) - the answer says "as of" today's date.
Expected: (17-Nov-2026) 429 open orders, 1,326 lines, 198,408,619.50 INR before GST (225,243,962.97 incl. GST).

## Q: Which customers have open sales orders, and for how much?

Also asked as: open orders by customer; customer-wise pending order value.

```sql
SELECT cu.customer_name,
       COUNT(DISTINCT s.so_number, c.financial_year) AS open_orders,
       ROUND(SUM(s.total_amount), 2) AS open_value_before_gst_inr,
       CURDATE() AS as_of_date
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
JOIN dim_customers cu ON cu.customer_id = s.customer_id
WHERE s.status = 'Open'
  AND s.order_date <= CURDATE()
GROUP BY cu.customer_id, cu.customer_name
ORDER BY open_value_before_gst_inr DESC;
```

Why: open = status 'Open', only orders dated up to today; orders counted by so_number + financial year; value before GST.
Expected: (17-Nov-2026) 310 customers; biggest Sakura Pump Japan Co., Ltd. 21 orders 11,436,172.50; Prithvi Motors Pvt. Ltd. 6 orders 4,950,897.50; Delta Forgings LLP 10 orders 4,931,435.00.

## Q: Which credit notes (sales returns and rate differences) were issued in FY 2026-27?

Also asked as: list of credit notes this year with customer and value; sales returns / rate differences.

```sql
SELECT il.note_number,
       il.note_date,
       cu.customer_name,
       il.original_invoice_number,
       ROUND(SUM(il.taxable_value), 2) AS credit_taxable_value_inr,
       ROUND(SUM(il.line_total_incl_gst), 2) AS credit_incl_gst_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE il.document_type = 'CREDIT_NOTE'
  AND c.financial_year = '2627'
GROUP BY il.note_number, il.note_date, cu.customer_name, il.original_invoice_number
ORDER BY il.note_date;
```

Why: credit notes are fact_invoice_lines rows with document_type 'CREDIT_NOTE'; their invoice_date is the note date; taxable_value is the positive printed amount (net_taxable_value is the negative one).
Expected: 63 credit note lines in FY 2026-27; the first SSMI/CN/2627/1 on 06-Apr-2026, Pioneer Valves LLC, 225,024.00 (invoice SSMI/E/2526/2327).

## Q: What were export, domestic and service sales in FY 2026-27?

Also asked as: export vs domestic sales; sales split by sale type.

```sql
SELECT il.sale_type,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.financial_year = '2627'
GROUP BY il.sale_type
ORDER BY net_sales_inr DESC;
```

Why: fact_invoice_lines.sale_type splits Domestic / Export / Service (credit notes keep the original invoice's sale_type).
Expected: Domestic 2,678,153,563.78; Export 680,651,545.30; Service 1,212,500.00.

## Q: How did each sales person perform in FY 2026-27?

Also asked as: sales person performance; sales by salesman; which sales person sold the most; sales employee ranking.

```sql
SELECT sp.sales_person_name,
       COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) AS invoices,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_sales_people sp ON sp.sales_person_id = il.sales_person_id
WHERE c.financial_year = '2627'
GROUP BY sp.sales_person_id, sp.sales_person_name
ORDER BY net_sales_inr DESC;
```

Why: sales by person = net_taxable_value per fact_invoice_lines.sales_person_id; invoices counted only on INVOICE rows.
Expected: 31 rows (30 sales people + Unknown); top Divya Nair 867 invoices 397,631,278.00; Karthik Menon 296,294,877.50; Rahul Verma 267,747,072.48.

## Q: What were net sales by product category in FY 2026-27?

Also asked as: sales by product group; category-wise sales; which pump category sells most.

```sql
SELECT COALESCE(p.product_category, 'Not classified') AS category,
       ROUND(SUM(il.net_quantity), 3) AS net_quantity,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_products p ON p.product_id = il.product_id
WHERE c.financial_year = '2627'
GROUP BY COALESCE(p.product_category, 'Not classified')
ORDER BY net_sales_inr DESC;
```

Why: product_category is the client classification; NULL (not classified, incl. service lines with product_id -1) is shown as 'Not classified', never dropped.
Expected: 8 categories; Not classified 1,126,760,793.20; GCI 404,260,334.50; Procon Pumps 357,916,886.50; YTH-PARTS 347,939,763.00; Trochoid pumps 315,554,003.23 ...

## Q: What is the stock value as on 30-Sep-2026?

Also asked as: inventory value on 30 Sep 2026; closing stock value on a given report date.

```sql
SELECT sl.report_date,
       COUNT(*) AS items,
       ROUND(SUM(sl.cumulative_qty), 3) AS stock_qty,
       ROUND(SUM(sl.cumulative_value), 2) AS stock_value_inr
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'Closing balance'
  AND sl.report_date = '2026-09-30'
GROUP BY sl.report_date;
```

Why: stock value on a date = SUM(cumulative_value) of the 'Closing balance' rows of that report_date only (never SUM every row).
Expected: 1,612 items, stock quantity 166,536.000, stock value 601,031,749.01 INR.

## Q: What is our current stock value (latest stock report)?

Also asked as: how much stock do we hold; current inventory value; latest closing stock; stock value now.

```sql
SELECT sl.report_date,
       COUNT(*) AS items,
       ROUND(SUM(sl.cumulative_qty), 3) AS stock_qty,
       ROUND(SUM(sl.cumulative_value), 2) AS stock_value_inr
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'Closing balance'
  AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)
GROUP BY sl.report_date;
```

Why: "current" / "latest" stock, or stock without a date, = the newest stock report (MAX(report_date)); new reports arrive with each load, so never hard-code a report date here. The answer names the report date used.
Expected: report 2026-10-31 - 1,613 items, 167,232.000 units, stock value 595,717,536.93 INR (stock reports are quarterly: 30-Jun, 30-Sep, 31-Dec, 31-Mar, plus 31-Oct-2026).

## Q: What was the COGS (cost of goods sold) in the stock report as on 30-Sep-2026?

Also asked as: COGS in the 30-Sep-2026 stock report; COGS rate per item on a given report date.

```sql
SELECT COUNT(*) AS cogs_rows,
       ROUND(COALESCE(SUM(-sl.transaction_value), 0), 2) AS cogs_value_inr,
       ROUND(SUM(-sl.transaction_value) / NULLIF(SUM(-sl.quantity), 0), 2) AS cogs_rate_per_unit
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'COGS'
  AND sl.report_date = '2026-09-30';
```

Why: COGS = movements whose document prefix is IN / CN / DN / RE (movement_type 'COGS'); COGS value = SUM(-transaction_value), rate = SUM(-transaction_value) / SUM(-quantity).
Expected: 1,931 COGS rows, 669,299,878.23 INR, 30,793.65 per unit.

## Q: What were net sales in Japanese yen for each sales month of FY 2026-27?

Also asked as: sales in JPY; yen value of monthly sales; convert sales from INR to JPY.

```sql
SELECT c.sales_month,
       f.exchange_rate,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,
       ROUND(SUM(il.net_taxable_value * f.exchange_rate), 2) AS net_sales_jpy
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_fx_rates f ON f.fx_rate_id = il.fx_rate_id
WHERE c.sales_year = '2627'
GROUP BY c.sales_period_no, c.sales_month, f.exchange_rate
ORDER BY c.sales_period_no;
```

Why: JPY = INR x dim_fx_rates.exchange_rate of the window holding the invoice date (fact_invoice_lines.fx_rate_id); each window is one sales month.
Expected: 8 rows - Apr 2026 rate 1.69, 855,336,581.65 JPY; ...; Oct 2026 rate 1.79, 926,315,142.02 JPY; Nov 2026 (21-31 Oct only) rate 1.74, 329,328,973.50 JPY.

## Q: Are there invoice or sales order lines with an Unknown customer or Unknown product?

Also asked as: unknown customer check; lines with missing master data (-1 keys); data quality of customer and product codes.

```sql
SELECT 'fact_invoice_lines' AS fact_table,
       COUNT(*) AS total_lines,
       SUM(customer_id = -1) AS unknown_customer_lines,
       SUM(product_id = -1) AS unknown_product_lines
FROM fact_invoice_lines
UNION ALL
SELECT 'fact_sales_order_lines', COUNT(*), SUM(customer_id = -1), SUM(product_id = -1)
FROM fact_sales_order_lines;
```

Why: a code not found in the master gets key -1 (Unknown) and the row is kept; count them with SUM(key = -1).
Expected: invoice lines 100,770 (81 Unknown customer, 990 Unknown product); sales order lines 99,701 (92 Unknown customer, 1,042 Unknown product).

## Q: What was the order intake (sales orders booked, excluding cancelled) in each financial year?

Also asked as: order booking per year; orders received per financial year; value of orders booked.

```sql
SELECT c.financial_year_label,
       COUNT(DISTINCT s.so_number, c.financial_year) AS orders,
       ROUND(SUM(s.total_amount), 2) AS order_value_inr
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
WHERE s.status <> 'Canceled'
GROUP BY c.financial_year, c.financial_year_label
ORDER BY c.financial_year;
```

Why: order intake = SUM(total_amount) of fact_sales_order_lines by order date, without 'Canceled' lines; orders counted by so_number + financial year.
Expected: FY 2024-25 11,067 orders 4,525,951,700.00; FY 2025-26 12,461 orders 5,192,894,810.00; FY 2026-27 (to 31-Oct-2026) 7,747 orders 3,420,600,879.00.

## Q: What were net sales by country segment in FY 2026-27?

Also asked as: sales by region of the world; Japan / Asia / America / Europe / Middle East sales.

```sql
SELECT COALESCE(cu.country_segment, 'Unknown') AS segment,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE c.financial_year = '2627'
GROUP BY COALESCE(cu.country_segment, 'Unknown')
ORDER BY segment;
```

Why: the client's country segment is dim_customers.country_segment, joined through fact_invoice_lines.customer_id.
Expected: 2.ASIA 2,789,541,998.28; 1.JAPAN 213,926,499.25; 3.AMERICA 111,981,011.30; 5.MIDDLE EAST 109,561,715.25; 4.EUROPE 54,629,344.00; 8.OTHER 29,753,438.50; Unknown 50,623,602.50.

## Q: How much did OEM and after-market (AFT) customers buy in FY 2026-27?

Also asked as: OEM vs aftermarket sales; sales by customer type; how much did OEM customers buy compared to after-market customers in each quarter / month (add c.fiscal_quarter or the month to the SELECT and GROUP BY).

```sql
SELECT COALESCE(il.customer_type, 'Not given') AS oem_or_aft,
       COUNT(*) AS invoice_line_count,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.financial_year = '2627'
GROUP BY COALESCE(il.customer_type, 'Not given')
ORDER BY net_sales_inr DESC;
```

Why: OEM / AFT is fact_invoice_lines.customer_type and is often blank - blanks are shown as 'Not given', not dropped, also when the user names only OEM and AFT (never filter customer_type IN ('OEM', 'AFT')): 'Not given' is more than half of the sales, and the answer mentions it.
Expected: Not given 1,769,842,430.33 (12,896 lines); OEM 870,891,421.25 (6,720 lines); AFT 719,283,757.50 (5,292 lines).

## Q: Show the lines of sales order 50 of FY 2026-27.

Also asked as: details of SO 50; what was ordered on sales order number 50 this year.

```sql
SELECT s.so_number,
       s.order_date,
       s.status,
       cu.customer_name,
       p.product_code,
       s.item_description,
       s.quantity,
       s.unit_price,
       s.discount_pct,
       s.total_amount,
       s.tax_total
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
JOIN dim_customers cu ON cu.customer_id = s.customer_id
JOIN dim_products p ON p.product_id = s.product_id
WHERE s.so_number = 50
  AND c.financial_year = '2627'
ORDER BY s.sales_order_line_id;
```

Why: SO numbers restart every FY (SO 50 also exists in FY 2024-25 and FY 2025-26), so the FY must be in the filter.
Expected: 2 lines, order date 2026-04-02, status Closed, Pioneer Precision Components LLP - FG02231 12,500.00; FG00654 250,000.00 (order total 262,500.00 before GST).

## Q: How many invoices were issued in calendar month August 2026 (1 to 31 Aug), and for what value?

Also asked as: invoice count in August 2026; number of invoices raised from 1 to 31 Aug 2026.

```sql
SELECT COUNT(DISTINCT il.invoice_number) AS invoices,
       ROUND(SUM(il.net_taxable_value), 2) AS invoiced_value_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE il.document_type = 'INVOICE'
  AND c.month_year = 'Aug 2026';
```

Why: the user asked for the calendar month, so dim_calendar.month_year (1st to last day) is used instead of the sales month; invoices are counted on INVOICE rows only.
Expected: 1,176 invoices, 481,828,141.00 INR.

## Q: Which 5 items had the highest stock value on 30-Sep-2026?

Also asked as: top items by stock value; most valuable items in stock; biggest inventory items.

```sql
SELECT p.product_code,
       p.product_description,
       sl.cumulative_qty AS stock_qty,
       sl.cumulative_value AS stock_value_inr
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
JOIN dim_products p ON p.product_id = sl.product_id
WHERE t.movement_type = 'Closing balance'
  AND sl.report_date = '2026-09-30'
ORDER BY sl.cumulative_value DESC
LIMIT 5;
```

Why: the stock of each item on the report date is its 'Closing balance' row (cumulative_qty / cumulative_value).
Expected: FG01484 GCI TX-675-3A 0.4kW 7,696,934.93; FG00542 5,759,696.49; FG01116 5,652,256.17; RM0130 5,142,443.80; FG01656 4,878,600.34.

## Q: How did each customer's sales grow or drop this year compared with last year?

Also asked as: compare each customer's growth this year vs last year; customer-wise sales growth; which customers grew or declined compared with last year; new and lost customers compared with last year.

```sql
WITH coverage AS (
  SELECT MIN(CASE WHEN il.invoice_date < '2026-04-01' THEN il.invoice_date END) AS last_from,
         MAX(CASE WHEN il.invoice_date < '2026-04-01' THEN il.invoice_date END) AS last_to,
         MIN(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.invoice_date END) AS this_from,
         MAX(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.invoice_date END) AS this_to
  FROM fact_invoice_lines il
  WHERE il.invoice_date BETWEEN '2025-04-01' AND '2027-03-31'
),
compare_window AS (
  SELECT GREATEST(last_from, this_from - INTERVAL 1 YEAR) AS last_start,
         LEAST(last_to, this_to - INTERVAL 1 YEAR) AS last_end
  FROM coverage
),
per_customer AS (
  SELECT il.customer_id,
         SUM(CASE WHEN il.invoice_date BETWEEN w.last_start AND w.last_end
                  THEN il.net_taxable_value ELSE 0 END) AS last_year_inr,
         SUM(CASE WHEN il.invoice_date BETWEEN w.last_start + INTERVAL 1 YEAR AND w.last_end + INTERVAL 1 YEAR
                  THEN il.net_taxable_value ELSE 0 END) AS this_year_inr
  FROM fact_invoice_lines il
  CROSS JOIN compare_window w
  GROUP BY il.customer_id
  HAVING last_year_inr <> 0 OR this_year_inr <> 0
),
classified AS (
  SELECT p.customer_id, cu.customer_name, p.last_year_inr, p.this_year_inr,
         CASE WHEN p.last_year_inr = 0 THEN 'New (no sales last year)'
              WHEN p.this_year_inr = 0 THEN 'Lost (no sales this year)'
              ELSE 'Both years' END AS customer_status,
         CASE WHEN p.last_year_inr > 0
              THEN ROUND((p.this_year_inr - p.last_year_inr) / p.last_year_inr * 100, 2) END AS growth_pct
  FROM per_customer p
  JOIN dim_customers cu ON cu.customer_id = p.customer_id
),
ranked AS (
  SELECT cl.customer_name, cl.last_year_inr, cl.this_year_inr, cl.customer_status, cl.growth_pct,
         ROW_NUMBER() OVER (PARTITION BY cl.customer_status ORDER BY cl.growth_pct DESC, cl.customer_name) AS top_growth_no,
         ROW_NUMBER() OVER (PARTITION BY cl.customer_status ORDER BY cl.growth_pct ASC, cl.customer_name) AS low_growth_no,
         ROW_NUMBER() OVER (PARTITION BY cl.customer_status ORDER BY cl.last_year_inr DESC, cl.customer_name) AS last_year_no,
         ROW_NUMBER() OVER (PARTITION BY cl.customer_status ORDER BY cl.this_year_inr DESC, cl.customer_name) AS this_year_no
  FROM classified cl
),
labelled AS (
  SELECT r.*,
         CASE WHEN r.customer_status = 'Both years' AND r.top_growth_no = 1 THEN 'Highest growth'
              WHEN r.customer_status = 'Both years' AND r.low_growth_no = 1
                   THEN CASE WHEN r.growth_pct < 0 THEN 'Biggest decline' ELSE 'Lowest growth' END
              WHEN r.customer_status = 'Lost (no sales this year)' AND r.last_year_no = 1 THEN 'Biggest lost customer'
              WHEN r.customer_status = 'New (no sales last year)' AND r.this_year_no = 1 THEN 'Biggest new customer'
         END AS highlight
  FROM ranked r
)
SELECT lb.highlight,
       lb.customer_name,
       ROUND(lb.last_year_inr, 2) AS last_year_sales_inr,
       ROUND(lb.this_year_inr, 2) AS this_year_sales_inr,
       lb.customer_status,
       lb.growth_pct,
       SUM(lb.customer_status = 'New (no sales last year)') OVER () AS new_customers,
       SUM(lb.customer_status = 'Lost (no sales this year)') OVER () AS lost_customers,
       SUM(lb.customer_status = 'Both years') OVER () AS customers_in_both_years,
       w.last_start AS last_year_from,
       w.last_end AS last_year_to,
       w.last_start + INTERVAL 1 YEAR AS this_year_from,
       w.last_end + INTERVAL 1 YEAR AS this_year_to
FROM labelled lb
CROSS JOIN compare_window w
ORDER BY CASE lb.highlight WHEN 'Highest growth' THEN 1 WHEN 'Biggest decline' THEN 2 WHEN 'Lowest growth' THEN 2
                           WHEN 'Biggest lost customer' THEN 3 WHEN 'Biggest new customer' THEN 4 ELSE 5 END,
         lb.growth_pct DESC, lb.this_year_inr DESC;
```

Why: this year / last year = the current FY (2026-27) and the previous FY (2025-26). The two FYs have data for different lengths of time, so the query compares the SAME dates in both years (the dates where both have data, shifted by one year) and returns those four dates. Growth % only where last year > 0, with both amounts shown; 'New' / 'Lost' customers are counted with window functions instead of being dropped. The `highlight` column is worked out in SQL with ROW_NUMBER() per customer_status ('Highest growth' and 'Biggest decline' among the both-years customers, 'Biggest lost customer' by last year's sales, 'Biggest new customer' by this year's sales), and those rows come first - the answer names them from the labels, never by scanning the list.
Expected: (17-Nov-2026) this year 01-Apr-2026 to 31-Oct-2026 vs the same dates last year (01-Apr-2025 to 31-Oct-2025): 1,147 customers in both years, 1,497 new, 693 lost; highest growth Summit Coolant Systems Pvt. Ltd. 4,320.00 -> 2,460,260.00; biggest lost Sunrise Fluid Power Pvt Ltd 13,952,041.00 -> 0.00; biggest new Quantum Power Systems Co., Ltd. 4,337,455.00.

## Q: How much did Allied Castings buy in Aug 2026?

Also asked as: sales to Everest Engineering this year; how much did we sell to Everest Engineering in FY 2026-27; sales to <part of a customer name> this financial year; how much did <part of a customer name> buy; sales of a customer whose name is typed partly; customer name search.

```sql
SELECT cu.customer_name,
       ROUND(COALESCE(SUM(il.net_taxable_value), 0), 2) AS net_sales_inr,
       COUNT(*) OVER () AS customers_matched
FROM dim_customers cu
LEFT JOIN fact_invoice_lines il
       ON il.customer_id = cu.customer_id
      AND il.invoice_date_id IN (SELECT c.date_id FROM dim_calendar c WHERE c.sales_month = 'Aug 2026')
WHERE cu.customer_name LIKE '%Allied Castings%'
GROUP BY cu.customer_id, cu.customer_name
ORDER BY net_sales_inr DESC;
```

Why: the user's name is partial, so LIKE '%...%' finds every customer whose name contains it; starting from dim_customers with a LEFT JOIN keeps matching customers without sales (0); customers_matched tells the answer how many customers the name matched, so it names each one instead of adding them up. For a whole financial year use `c.financial_year = '2627'` inside the same ON - still one row per matching customer.
Expected: 2 customers matched - Allied Castings Limited 675,200.00; Allied Castings Pvt Ltd 0.00.

## Q: What is our COGS (cost of goods sold) now, in the latest stock report?

Also asked as: cost of goods sold now; current COGS; COGS value and rate in the newest stock report.

```sql
SELECT r.report_date,
       COUNT(sl.stock_ledger_id) AS cogs_rows,
       ROUND(COALESCE(SUM(-sl.quantity), 0), 3) AS cogs_qty,
       ROUND(COALESCE(SUM(-sl.transaction_value), 0), 2) AS cogs_value_inr,
       ROUND(SUM(-sl.transaction_value) / NULLIF(SUM(-sl.quantity), 0), 2) AS cogs_rate_per_unit_inr
FROM (SELECT MAX(report_date) AS report_date FROM fact_stock_ledger) r
LEFT JOIN fact_stock_ledger sl
       ON sl.report_date = r.report_date
      AND sl.movement_type_id IN (SELECT t.movement_type_id FROM dim_stock_movement_types t
                                  WHERE t.movement_type = 'COGS')
GROUP BY r.report_date;
```

Why: "now" / "current" = the newest stock report (MAX(report_date)); COGS = movements with movement_type 'COGS', value SUM(-transaction_value). The LEFT JOIN from the report date returns one row even when that report has no COGS rows (then 0).
Expected: report 2026-10-31 - 638 COGS rows, 7,918.000 units, 253,254,756.67 INR, 31,984.69 per unit.

## Q: When was the data last loaded, and how many rows did that load add?

Also asked as: last data load; when was ss_gold refreshed; what did the last load add, update or skip; data freshness; load history.

```sql
SELECT l.run_id,
       l.run_type,
       l.batch_name,
       MAX(l.loaded_at) AS loaded_at,
       COUNT(*) AS tables_loaded,
       SUM(l.inserted_rows) AS inserted_rows,
       SUM(l.updated_rows) AS updated_rows,
       SUM(l.skipped_rows) AS skipped_rows,
       GROUP_CONCAT(CONCAT(l.table_name, ' +', l.inserted_rows) ORDER BY l.table_name SEPARATOR '; ') AS inserted_per_table
FROM load_log l
WHERE l.run_id = (SELECT MAX(run_id) FROM load_log)
GROUP BY l.run_id, l.run_type, l.batch_name;
```

Why: load_log has one row per table per load run; the latest run = MAX(run_id). Totals per run come from SUM over its tables, and inserted_per_table names each table with its own count, so the answer never lists bare numbers. On a FULL run inserted_rows = the rows loaded.
Expected: run 1 FULL from 'inputdata' on 17-Nov-2026, 10 tables, 307,850 rows inserted, 0 updated, 0 skipped (one full load, no incremental runs).

## Q: How much GST did we collect in Jan 2026?

Also asked as: GST in Jan 2026; total GST (IGST + CGST + SGST + cess) for a month; net GST after credit notes; tax collected in a sales month.

```sql
SELECT MIN(c.sales_period_start) AS period_start,
       MAX(c.sales_period_end) AS period_end,
       ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN -1 ELSE 1 END
                 * (COALESCE(il.igst_amount, 0) + COALESCE(il.cgst_amount, 0)
                    + COALESCE(il.sgst_amount, 0) + COALESCE(il.cess_amount, 0))), 2) AS net_gst_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_month = 'Jan 2026';
```

Why: a month name means the sales month (here 21-Dec-2025 to 20-Jan-2026), also for GST; GST = igst + cgst + sgst + cess; these amounts are positive as printed on credit notes too, so credit note rows are subtracted (CASE ... THEN -1).
Expected: 21-Dec-2025 to 20-Jan-2026: net GST 63,237,972.34 INR.

## Q: What were the INR to JPY rates for the last 6 rate months?

Also asked as: exchange rate trend; last 6 months of INR to JPY rates; latest exchange rates; how did the yen rate move.

```sql
SELECT last6.rate_month,
       last6.start_date,
       last6.end_date,
       last6.exchange_rate
FROM (SELECT f.rate_month, f.start_date, f.end_date, f.exchange_rate
      FROM dim_fx_rates f
      WHERE f.fx_rate_id <> -1
      ORDER BY f.start_date DESC
      LIMIT 6) AS last6
ORDER BY last6.start_date;
```

Why: rate months come straight from dim_fx_rates (one row per rate month), newest 6 by start_date, then shown oldest first; joining dim_calendar would repeat each month once per day.
Expected: Jun 2026 1.64; Jul 2026 1.72; Aug 2026 1.65; Sep 2026 1.69; Oct 2026 1.79; Nov 2026 1.74 (window 21-Oct-2026 to 31-Oct-2026).

## Q: What were total net sales this year and last year, and how much did they grow?

Also asked as: last year and current year revenue; revenue growth % compared with last year; how much did our sales increase this year; last year vs this year revenue; profit percentage this year vs last year (profit itself is not in the data - give the revenue growth and say so).

```sql
WITH coverage AS (
  SELECT MIN(CASE WHEN il.invoice_date < '2026-04-01' THEN il.invoice_date END) AS last_from,
         MAX(CASE WHEN il.invoice_date < '2026-04-01' THEN il.invoice_date END) AS last_to,
         MIN(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.invoice_date END) AS this_from,
         MAX(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.invoice_date END) AS this_to,
         SUM(CASE WHEN il.invoice_date < '2026-04-01' THEN il.net_taxable_value ELSE 0 END) AS last_fy_inr,
         SUM(CASE WHEN il.invoice_date >= '2026-04-01' THEN il.net_taxable_value ELSE 0 END) AS this_fy_inr
  FROM fact_invoice_lines il
  WHERE il.invoice_date BETWEEN '2025-04-01' AND '2027-03-31'
),
compare_window AS (
  SELECT GREATEST(last_from, this_from - INTERVAL 1 YEAR) AS last_start,
         LEAST(last_to, this_to - INTERVAL 1 YEAR) AS last_end
  FROM coverage
),
same_dates AS (
  SELECT SUM(CASE WHEN il.invoice_date <= w.last_end THEN il.net_taxable_value ELSE 0 END) AS last_inr,
         SUM(CASE WHEN il.invoice_date >= w.last_start + INTERVAL 1 YEAR THEN il.net_taxable_value ELSE 0 END) AS this_inr
  FROM fact_invoice_lines il
  CROSS JOIN compare_window w
  WHERE il.invoice_date BETWEEN w.last_start AND w.last_end
     OR il.invoice_date BETWEEN w.last_start + INTERVAL 1 YEAR AND w.last_end + INTERVAL 1 YEAR
)
SELECT cv.last_from AS fy2526_data_from, cv.last_to AS fy2526_data_to, ROUND(cv.last_fy_inr, 2) AS fy2526_sales_inr,
       cv.this_from AS fy2627_data_from, cv.this_to AS fy2627_data_to, ROUND(cv.this_fy_inr, 2) AS fy2627_sales_inr,
       w.last_start AS same_dates_last_year_from, w.last_end AS same_dates_last_year_to,
       w.last_start + INTERVAL 1 YEAR AS same_dates_this_year_from, w.last_end + INTERVAL 1 YEAR AS same_dates_this_year_to,
       ROUND(sd.last_inr, 2) AS same_dates_last_year_inr, ROUND(sd.this_inr, 2) AS same_dates_this_year_inr,
       ROUND((sd.this_inr - sd.last_inr) / NULLIF(sd.last_inr, 0) * 100, 2) AS revenue_growth_pct
FROM coverage cv
CROSS JOIN compare_window w
CROSS JOIN same_dates sd;
```

Why: "this year" / "last year" = the current and the previous FY. The query gives BOTH: each FY's total with the dates the data covers (the current FY is not over), and a fair growth % on the SAME dates in both years (the dates where both years have data, shifted by one year), calculated in SQL (revenue_growth_pct). The answer gives the two FY totals with their dates first, then the same-dates growth. When the user said "profit %", the reply also has the line "MISSING: true profit - the SS Manufacturing data has selling prices but not the cost of the items sold", and the answer calls the % revenue growth, never profit.
Expected: (17-Nov-2026) FY 2025-26 5,169,611,634.51 (01-Apr-2025 to 31-Mar-2026); FY 2026-27 3,360,017,609.08 (01-Apr-2026 to 31-Oct-2026); same dates 01-Apr..31-Oct: 2,798,457,848.67 last year vs 3,360,017,609.08 this year = +20.07%.

## Q: How many new customers did we get in FY 2026-27, and how much did they buy?

Also asked as: new customers this year and their revenue; how many customers bought from us for the first time; first-time customers this year; revenue from new customers.

```sql
WITH fy AS (
  SELECT MIN(c.full_date) AS fy_start, MAX(c.full_date) AS fy_end
  FROM dim_calendar c
  WHERE c.financial_year = '2627'
),
first_invoice AS (
  SELECT il.customer_id, MIN(il.invoice_date) AS first_invoice_date
  FROM fact_invoice_lines il
  GROUP BY il.customer_id
),
period_sales AS (
  SELECT il.customer_id, SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  JOIN fy ON il.invoice_date BETWEEN fy.fy_start AND fy.fy_end
  GROUP BY il.customer_id
)
SELECT fy.fy_start AS period_from,
       fy.fy_end AS period_to,
       (SELECT MIN(d.invoice_date) FROM fact_invoice_lines d) AS invoice_history_starts,
       SUM(ps.customer_id <> -1 AND fi.first_invoice_date >= fy.fy_start) AS new_customers,
       ROUND(SUM(CASE WHEN ps.customer_id <> -1 AND fi.first_invoice_date >= fy.fy_start
                      THEN ps.sales_inr ELSE 0 END), 2) AS new_customers_sales_inr,
       SUM(ps.customer_id <> -1) AS customers_buying,
       ROUND(SUM(ps.sales_inr), 2) AS all_sales_inr,
       ROUND(SUM(CASE WHEN ps.customer_id = -1 THEN ps.sales_inr ELSE 0 END), 2) AS unknown_customer_sales_inr
FROM fy
CROSS JOIN period_sales ps
JOIN first_invoice fi ON fi.customer_id = ps.customer_id
GROUP BY fy.fy_start, fy.fy_end;
```

Why: a new customer = the customer's FIRST invoice line in the data falls in the period; their sales = net sales in the period. Always return invoice_history_starts (where the invoice data starts, 02-Apr-2024): "first" is checked against all invoices since that date (a customer who bought only before it looks new). The answer says e.g. "876 customers bought for the first time in FY 2026-27 (checked against all invoices since 02-Apr-2024, where our data starts)" - never that the period's data starts on that date. The Unknown customer (-1) is not counted as a customer; its sales are shown separately (unknown_customer_sales_inr). customers_buying and all_sales_inr show how big the new customers are compared with everyone who bought.
Expected: 01-Apr-2026 to 31-Mar-2027, invoice_history_starts 02-Apr-2024: 876 new customers, 517,895,758.50 INR, out of 2,643 customers buying and 3,360,017,609.08 INR.

## Q: Which customers stopped buying from us?

Also asked as: customers who have not bought for a while; lapsed or inactive customers; customers with no orders in the last 3 months; which customers we lost.

```sql
WITH latest AS (
  SELECT MAX(invoice_date) AS newest_invoice_date,
         MAX(invoice_date) - INTERVAL 3 MONTH AS cutoff_date
  FROM fact_invoice_lines
),
per_customer AS (
  SELECT il.customer_id,
         MAX(il.invoice_date) AS last_invoice_date,
         SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  WHERE il.customer_id <> -1
  GROUP BY il.customer_id
)
SELECT cu.customer_name,
       pc.last_invoice_date,
       ROUND(pc.sales_inr, 2) AS sales_in_data_inr,
       l.cutoff_date AS no_invoice_on_or_after,
       DATEDIFF(l.newest_invoice_date, l.cutoff_date) AS days_before_newest_invoice,
       l.newest_invoice_date,
       COUNT(*) OVER () AS stopped_customers
FROM per_customer pc
JOIN dim_customers cu ON cu.customer_id = pc.customer_id
CROSS JOIN latest l
WHERE pc.last_invoice_date < l.cutoff_date
ORDER BY pc.sales_inr DESC;
```

Why: "stopped buying" = the customer bought before but has no invoice in the last 3 months of the data: no invoice on or after no_invoice_on_or_after (the newest invoice date minus 3 months; days_before_newest_invoice = how many days that is), unless the user gives another period (then change INTERVAL 3 MONTH). The newest invoice date comes from the data (MAX(invoice_date)), never a fixed date. The Unknown customer (-1) is not a customer. Biggest customers first; stopped_customers is the count of all of them (also when the list is longer than the rows shown). The answer says e.g. "2,482 customers bought before but have no invoice on or after 31-Jul-2026 (92 days before the newest invoice, 31-Oct-2026)" and that the period can be changed.
Expected: newest invoice 31-Oct-2026, no invoice on or after 31-Jul-2026 (92 days before): 2,482 customers; biggest Aurora Fluid Power Limited (last invoice 17-Jul-2026, 119,592,664.50 in the data).

## Q: How many items have zero stock right now?

Also asked as: items out of stock; zero stock items now; items with no stock in the latest stock report; negative stock items.

```sql
SELECT sl.report_date,
       SUM(sl.cumulative_qty = 0) AS zero_stock_items,
       SUM(sl.cumulative_qty < 0) AS negative_stock_items,
       COUNT(*) AS items_in_report
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'Closing balance'
  AND sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)
GROUP BY sl.report_date;
```

Why: "right now" = the newest stock report (MAX(report_date)); count the 'Closing balance' rows of that report by cumulative_qty = 0 (and < 0 for negative stock). Always return report_date - the answer must say which stock report was used.
Expected: report 2026-10-31: 0 items with zero stock, 0 negative, 1,613 items in the report.

## Q: What were last month's sales, and which customer bought the most?

Also asked as: last month sales and the top customer; which customer gave us the most revenue last month; previous month net sales.

```sql
WITH last_month AS (
  SELECT p.sales_month, p.sales_period_start, p.sales_period_end
  FROM dim_calendar t
  JOIN dim_calendar p ON p.full_date = t.sales_period_start - INTERVAL 1 DAY
  WHERE t.full_date = CURDATE()
),
customer_sales AS (
  SELECT cu.customer_name, SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  JOIN last_month lm ON il.invoice_date BETWEEN lm.sales_period_start AND lm.sales_period_end
  JOIN dim_customers cu ON cu.customer_id = il.customer_id
  GROUP BY cu.customer_id, cu.customer_name
)
SELECT lm.sales_month AS sales_month,
       lm.sales_period_start AS period_from,
       lm.sales_period_end AS period_to,
       (SELECT ROUND(SUM(sales_inr), 2) FROM customer_sales) AS net_sales_inr,
       cs.customer_name AS top_customer,
       ROUND(cs.sales_inr, 2) AS top_customer_sales_inr
FROM last_month lm
LEFT JOIN customer_sales cs ON TRUE
ORDER BY cs.sales_inr DESC
LIMIT 1;
```

Why: "last month" is worked out from TODAY (CURDATE()) in dim_calendar - never from the newest invoice and never by sorting sales_month, which is text ('Sep 2026' sorts after 'Mar 2027'). Last month = the sales month that ends the day before today's sales month starts: on 12-Oct-2026 today is in 'Oct 2026', so last month = 'Sep 2026' (21-Aug-2026 to 20-Sep-2026). For "this month" use the SQL of the example "What are our sales this month so far?" (only up to today). The answer states the month and its dates.
Expected: (17-Nov-2026) Oct 2026 (21-Sep-2026 to 20-Oct-2026) 517,494,492.75; top customer Sakura Pump Japan Co., Ltd. 28,239,876.00.

## Q: What are our sales this month so far?

Also asked as: current month sales; this month's net sales; sales of the running month; how much did we sell this month; MTD (month to date) sales; sales so far this month; this month top customer.

```sql
WITH this_month AS (
  SELECT sales_month, sales_period_start, LEAST(sales_period_end, CURDATE()) AS so_far_to
  FROM dim_calendar
  WHERE full_date = CURDATE()
)
SELECT tm.sales_month AS sales_month,
       tm.sales_period_start AS period_from,
       tm.so_far_to AS period_to,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_so_far_inr,
       COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) AS invoices_so_far
FROM this_month tm
LEFT JOIN fact_invoice_lines il ON il.invoice_date BETWEEN tm.sales_period_start AND tm.so_far_to
GROUP BY tm.sales_month, tm.sales_period_start, tm.so_far_to;
```

Why: this month is not over yet, so it counts only from its first day up to TODAY (CURDATE()) - never to the month's last day: data dated after today must not be counted. The answer says "so far" with both dates, e.g. "In sales month Nov 2026 so far (21-Oct-2026 to 27-Oct-2026) net sales were ...". For a top customer, a product or a split, keep the same dates (invoice_date BETWEEN period_from AND period_to).
Expected: (17-Nov-2026) Nov 2026, 21-Oct-2026 to 17-Nov-2026: 189,269,525.00 from 456 invoices (the data ends on 31-Oct-2026).

## Q: Who are our new customers this month so far?

Also asked as: new customers this month; who is our new customer in this month; first-time buyers this month; how many new customers did we get this month; the biggest new customer this month; new customers month to date.

```sql
WITH this_month AS (
  SELECT sales_month, sales_period_start, LEAST(sales_period_end, CURDATE()) AS so_far_to
  FROM dim_calendar
  WHERE full_date = CURDATE()
),
first_invoice AS (
  SELECT il.customer_id, MIN(il.invoice_date) AS first_invoice_date
  FROM fact_invoice_lines il
  WHERE il.customer_id <> -1
  GROUP BY il.customer_id
),
month_sales AS (
  SELECT il.customer_id, SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  JOIN this_month tm ON il.invoice_date BETWEEN tm.sales_period_start AND tm.so_far_to
  GROUP BY il.customer_id
)
SELECT tm.sales_month AS sales_month,
       tm.sales_period_start AS period_from,
       tm.so_far_to AS period_to,
       cu.customer_name,
       fi.first_invoice_date,
       ROUND(ms.sales_inr, 2) AS sales_so_far_inr,
       COUNT(*) OVER () AS new_customers,
       (SELECT MIN(d.invoice_date) FROM fact_invoice_lines d) AS invoice_history_starts
FROM this_month tm
JOIN first_invoice fi ON fi.first_invoice_date BETWEEN tm.sales_period_start AND tm.so_far_to
JOIN month_sales ms ON ms.customer_id = fi.customer_id
JOIN dim_customers cu ON cu.customer_id = fi.customer_id
ORDER BY ms.sales_inr DESC, cu.customer_name;
```

Why: this month is not over yet, so the month counts only up to TODAY (LEAST(sales_period_end, CURDATE())) - invoices dated after today must not be counted, neither as a first invoice nor as sales. A new customer = the customer's FIRST invoice line in the data falls in the period (see "How many new customers did we get in FY 2026-27"); the Unknown customer (-1) is not a customer. One row per new customer, the biggest sales first, with the count of all of them in new_customers (COUNT(*) OVER (), so it is right even when only the first 500 rows are shown). The answer says "so far" with both dates and that "first" is checked against all invoices since invoice_history_starts.
Expected: (17-Nov-2026) Nov 2026 so far: 31 new customers; biggest Royal Fabricators Private Limited (first invoice 28-Oct-2026, 1,960,650.00).

## Q: Who were our new customers last month?

Also asked as: new customers in the previous month; first-time buyers last month; how many new customers did we get last month; the biggest new customer last month.

```sql
WITH last_month AS (
  SELECT p.sales_month, p.sales_period_start, p.sales_period_end
  FROM dim_calendar t
  JOIN dim_calendar p ON p.full_date = t.sales_period_start - INTERVAL 1 DAY
  WHERE t.full_date = CURDATE()
),
first_invoice AS (
  SELECT il.customer_id, MIN(il.invoice_date) AS first_invoice_date
  FROM fact_invoice_lines il
  WHERE il.customer_id <> -1
  GROUP BY il.customer_id
),
month_sales AS (
  SELECT il.customer_id, SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  JOIN last_month lm ON il.invoice_date BETWEEN lm.sales_period_start AND lm.sales_period_end
  GROUP BY il.customer_id
)
SELECT lm.sales_month AS sales_month,
       lm.sales_period_start AS period_from,
       lm.sales_period_end AS period_to,
       cu.customer_name,
       fi.first_invoice_date,
       ROUND(ms.sales_inr, 2) AS sales_inr,
       COUNT(*) OVER () AS new_customers,
       (SELECT MIN(d.invoice_date) FROM fact_invoice_lines d) AS invoice_history_starts
FROM last_month lm
JOIN first_invoice fi ON fi.first_invoice_date BETWEEN lm.sales_period_start AND lm.sales_period_end
JOIN month_sales ms ON ms.customer_id = fi.customer_id
JOIN dim_customers cu ON cu.customer_id = fi.customer_id
ORDER BY ms.sales_inr DESC, cu.customer_name;
```

Why: "last month" is the sales month before today's one, worked out from CURDATE() in dim_calendar (as in "What were last month's sales"). It is over, so its whole period counts. A new customer = the customer's FIRST invoice line in the data falls in that month; one row per new customer, the biggest first, with the count of all of them in new_customers.
Expected: (17-Nov-2026) Oct 2026: 109 new customers; biggest Ganga Gear Works Pvt Ltd (first invoice 12-Oct-2026, 1,337,810.00).

## Q: Show net sales month by month from Jan 2026 to Oct 2026.

Also asked as: monthly sales from Jan 2026 to Oct 2026; month by month sales between two months; month-wise net sales from Apr 2026 to Sep 2026 after credit and debit notes; monthly sales trend from one month to another; sales of each month in a range of months.

```sql
SELECT c.sales_month,
       c.sales_period_start AS period_start,
       c.sales_period_end AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.sales_period_start >= (SELECT MIN(sales_period_start) FROM dim_calendar WHERE sales_month = 'Jan 2026')
  AND c.sales_period_end <= (SELECT MAX(sales_period_end) FROM dim_calendar WHERE sales_month = 'Oct 2026')
GROUP BY c.sales_month, c.sales_period_start, c.sales_period_end
ORDER BY c.sales_period_start;
```

Why: a range of named months is a range of sales months (21st to 20th), one row per sales month: 'Jan 2026' starts on 21-Dec-2025 and 'Oct 2026' ends on 20-Oct-2026. The first and last month are looked up by name (no date arithmetic). period_start / period_end are the sales month's own dates from dim_calendar - never MIN / MAX of the invoice dates. Order by sales_period_start, never by the month text. net_taxable_value already has credit notes negative and debit notes positive. Use calendar months (c.month_year) only when the user says "calendar month" or gives exact dates.
Expected: 10 rows from Jan 2026 (21-Dec-2025 to 20-Jan-2026) 470,037,262.50 to Oct 2026 (21-Sep-2026 to 20-Oct-2026) 517,494,492.75; highest Mar 2026 534,303,216.00; lowest Jul 2026 434,659,336.50.

## Q: Which customers bought from us between Jan 2026 and Jun 2026 but have bought nothing since Oct 2026?

Also asked as: customers who bought in one period but not since a month; customers who bought earlier but have not bought since Oct 2026; bought in H1 but nothing after that; customers missing since a month.

```sql
WITH bounds AS (
  SELECT (SELECT MIN(sales_period_start) FROM dim_calendar WHERE sales_month = 'Jan 2026') AS bought_from,
         (SELECT MAX(sales_period_end) FROM dim_calendar WHERE sales_month = 'Jun 2026') AS bought_to,
         (SELECT MIN(sales_period_start) FROM dim_calendar WHERE sales_month = 'Oct 2026') AS nothing_since
),
per_customer AS (
  SELECT il.customer_id,
         SUM(CASE WHEN il.invoice_date BETWEEN b.bought_from AND b.bought_to THEN il.net_taxable_value ELSE 0 END) AS sales_in_period,
         SUM(il.document_type = 'INVOICE' AND il.invoice_date BETWEEN b.bought_from AND b.bought_to) AS invoices_in_period,
         SUM(il.document_type = 'INVOICE' AND il.invoice_date >= b.nothing_since) AS invoices_since,
         MAX(CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_date END) AS last_invoice_date
  FROM fact_invoice_lines il
  CROSS JOIN bounds b
  WHERE il.customer_id <> -1
  GROUP BY il.customer_id
)
SELECT b.bought_from, b.bought_to, b.nothing_since AS no_invoice_on_or_after,
       cu.customer_name, pc.last_invoice_date,
       ROUND(pc.sales_in_period, 2) AS sales_in_period_inr,
       COUNT(*) OVER () AS matching_customers
FROM per_customer pc
JOIN dim_customers cu ON cu.customer_id = pc.customer_id
CROSS JOIN bounds b
WHERE pc.invoices_in_period > 0 AND pc.invoices_since = 0
ORDER BY pc.sales_in_period DESC;
```

Why: month names are sales months, looked up by name: "between Jan 2026 and Jun 2026" = 21-Dec-2025 to 20-Jun-2026; "nothing since Oct 2026" = no invoice on or after the FIRST day of Oct 2026 (21-Sep-2026) - October itself counts, so never compare with the month's last day. Buying = an INVOICE line; a later credit / debit note is not a purchase. The Unknown customer (-1) is not a customer and gets no row. The answer states the three dates and matching_customers.
Expected: 1,669 customers bought 21-Dec-2025 to 20-Jun-2026 and have no invoice on or after 21-Sep-2026; biggest Aurora Fluid Power Limited 23,158,082.50 (last invoice 17-Jul-2026).

## Q: Which items had the biggest increase in stock value between 30-Jun-2026 and 31-Oct-2026?

Also asked as: stock value change per item between two stock reports; items whose stock grew the most; compare stock of two report dates; which items' inventory dropped the most (ORDER BY increase_inr ASC).

```sql
WITH v AS (
  SELECT sl.product_id,
         SUM(CASE WHEN sl.report_date = '2026-06-30' THEN sl.cumulative_value END) AS value_before,
         SUM(CASE WHEN sl.report_date = '2026-10-31' THEN sl.cumulative_value END) AS value_after
  FROM fact_stock_ledger sl
  JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
  WHERE t.movement_type = 'Closing balance' AND sl.report_date IN ('2026-06-30', '2026-10-31')
  GROUP BY sl.product_id
)
SELECT p.product_code, p.product_description,
       ROUND(v.value_before, 2) AS stock_value_before_inr,
       ROUND(v.value_after, 2) AS stock_value_after_inr,
       ROUND(v.value_after - v.value_before, 2) AS increase_inr,
       (SELECT COUNT(*) FROM v WHERE value_before IS NOT NULL AND value_after IS NOT NULL) AS items_in_both_reports,
       (SELECT COUNT(*) FROM v WHERE value_before IS NULL) AS items_only_in_newer_report,
       (SELECT COUNT(*) FROM v WHERE value_after IS NULL) AS items_only_in_older_report
FROM v
JOIN dim_products p ON p.product_id = v.product_id
WHERE v.value_before IS NOT NULL AND v.value_after IS NOT NULL
ORDER BY increase_inr DESC
LIMIT 5;
```

Why: stock on a date = the 'Closing balance' rows of that report. Only items in BOTH reports can be compared - an item can be missing from one report - so return items_in_both_reports and the items found in one report only, and the answer says e.g. "1,604 items are in both stock reports (9 are only in the 31-Oct-2026 report)".
Expected: 1,604 items in both reports, 9 only in the newer one, 0 only in the older one; biggest increase CO00045 Packing tape 45 from 1,519,817.20 to 5,173,657.97 (+3,653,840.77), then RM0135 (+2,525,280.61) and CO00222 (+2,524,647.51).

## Q: Which items were in stock on 31-Oct-2026 but had no sales between 01-May-2026 and 31-Oct-2026?

Also asked as: unsold stock; slow-moving or dead stock; items in stock with no sales; stock not sold since a date; non-moving inventory; finished goods in stock but not sold.

```sql
WITH stock AS (
  SELECT sl.product_id, sl.cumulative_qty, sl.cumulative_value, p.product_code, p.product_description, p.item_group
  FROM fact_stock_ledger sl
  JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
  JOIN dim_products p ON p.product_id = sl.product_id
  WHERE t.movement_type = 'Closing balance' AND sl.report_date = '2026-10-31'
    AND sl.cumulative_qty > 0 AND sl.product_id <> -1
),
unsold AS (
  SELECT st.product_id, st.cumulative_qty, st.cumulative_value, st.product_code, st.product_description, st.item_group
  FROM stock st
  WHERE NOT EXISTS (SELECT 1 FROM fact_invoice_lines il
                    WHERE il.product_id = st.product_id AND il.invoice_date BETWEEN '2026-05-01' AND '2026-10-31')
),
summary AS (
  SELECT (SELECT COUNT(*) FROM stock WHERE item_group = 'Finished goods') AS finished_goods_in_stock,
         (SELECT COUNT(*) FROM unsold WHERE item_group = 'Finished goods') AS finished_goods_without_sales,
         (SELECT COUNT(*) FROM unsold WHERE COALESCE(item_group, '') <> 'Finished goods') AS other_items_not_sold
)
SELECT sm.finished_goods_in_stock, sm.finished_goods_without_sales, sm.other_items_not_sold,
       sm.finished_goods_in_stock - sm.finished_goods_without_sales AS finished_goods_sold_in_period,
       CONCAT(CASE WHEN sm.finished_goods_without_sales = 0 THEN 'every finished good in stock was sold in the period'
                   ELSE 'the finished goods listed had no sales in the period' END,
              '; the ', sm.other_items_not_sold, ' other items in stock are raw materials, consumables and ',
              'capital items, which are not for sale') AS finished_goods_result,
       u.product_code, u.product_description, u.cumulative_qty AS stock_qty,
       ROUND(u.cumulative_value, 2) AS stock_value_inr
FROM summary sm
LEFT JOIN unsold u ON u.item_group = 'Finished goods'
ORDER BY u.cumulative_value DESC;
```

Why: only finished goods are sold - raw materials, consumables and capital items are never invoiced, so listing them as "unsold" is noise. The rows are the finished goods in stock with no invoice in the period (biggest stock value first); the summary columns always come back (one row with empty item columns when every finished good sold), so the answer can say e.g. "all 4,097 finished goods in stock were sold in this period; the 872 other items in stock are raw materials, consumables and capital items, which are not for sale". finished_goods_sold_in_period and finished_goods_result say the same as a plain count and a sentence, so 0 without sales is never read as "no sales" (27-Oct: it was). Dates the user gives are exact dates.
Expected: 820 finished goods in stock on 31-Oct-2026: 808 sold and 12 without sales from 01-May-2026 (biggest FG01434 Coolant Unit CP-294-1B 0.75kW, 466,320.00); 793 other items not sold.

## Q: How much of our net sales were invoices, credit notes and debit notes?

Also asked as: were credit notes deducted from sales; net sales = invoices minus credit notes plus debit notes; how much of the sales were credit notes or sales returns; check that net sales include the credit and debit notes; how much of a customer's, territory's or month's sales were credit notes (add that filter - a customer name with LIKE, grouped by the customer as the names rule says).

```sql
SELECT MIN(il.invoice_date) AS data_from,
       MAX(il.invoice_date) AS data_to,
       ROUND(SUM(CASE WHEN il.document_type = 'INVOICE' THEN il.net_taxable_value ELSE 0 END), 2) AS invoices_inr,
       ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN il.taxable_value ELSE 0 END), 2) AS credit_notes_inr,
       ROUND(SUM(CASE WHEN il.document_type = 'DEBIT_NOTE' THEN il.net_taxable_value ELSE 0 END), 2) AS debit_notes_inr,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,
       COUNT(DISTINCT CASE WHEN il.document_type = 'CREDIT_NOTE' THEN il.note_number END) AS credit_note_count,
       COUNT(DISTINCT CASE WHEN il.document_type = 'DEBIT_NOTE' THEN il.note_number END) AS debit_note_count
FROM fact_invoice_lines il;
```

Why: net sales already include the notes - net_taxable_value is negative on credit notes and positive on debit notes - so net_sales_inr = invoices_inr - credit_notes_inr + debit_notes_inr (credit notes shown as a positive amount from taxable_value). ONE summary row answers "were the notes deducted?"; never list every customer for it (thousands of rows, cut at 500). data_from / data_to say which dates the totals cover.
Expected: 02-Apr-2024 to 31-Oct-2026: invoices 12,953,990,174.50; credit notes 11,964,477.14 (213 notes); debit notes 68,518.08 (19 notes); net sales 12,942,094,215.44 = 12,953,990,174.50 - 11,964,477.14 + 68,518.08.

## Q: Which dates does Q1 of FY 2026-27 cover?

Also asked as: dates of quarter 1 / Q2 / Q3 / Q4 of this FY; does a quarter use calendar dates or sales months; which quarter definition does the app use; is Q1 April to June or 21-Mar to 20-Jun (for Q2 use fiscal_quarter = 2 and the sales months Jul, Aug and Sep 2026; Q3 = Oct-Dec; Q4 = Jan-Mar 2027).

```sql
SELECT 'Q1 of FY 2026-27 (the quarter Manufacturing Intelligence uses)' AS quarter_meaning,
       MIN(c.full_date) AS period_from,
       MAX(c.full_date) AS period_to
FROM dim_calendar c
WHERE c.financial_year = '2627' AND c.fiscal_quarter = 1
UNION ALL
SELECT 'sales months Apr, May and Jun 2026', MIN(c.sales_period_start), MAX(c.sales_period_end)
FROM dim_calendar c
WHERE c.sales_month IN ('Apr 2026', 'May 2026', 'Jun 2026');
```

Why: Manufacturing Intelligence's quarter is the FY quarter by calendar dates (dim_calendar.fiscal_quarter: Q1 = 1-Apr to 30-Jun), and every answer about a quarter states its dates; the sales months of the same quarter start on the 21st, so they are shown next to it. A question about which dates a period covers is an SS Manufacturing data question - answer it from dim_calendar, never with NO_SQL.
Expected: Q1 of FY 2026-27 = 01-Apr-2026 to 30-Jun-2026 (used by Manufacturing Intelligence); sales months Apr-Jun 2026 = 21-Mar-2026 to 20-Jun-2026.

## Q: Which items are below their minimum inventory level right now?

Also asked as: items below minimum stock; items under the reorder level; which items need reordering; stock below the safety stock; items short of their minimum quantity.

```sql
WITH latest AS (
  SELECT MAX(report_date) AS report_date FROM fact_stock_ledger
),
stock AS (
  SELECT sl.product_id, sl.cumulative_qty AS stock_qty
  FROM fact_stock_ledger sl
  JOIN latest l ON l.report_date = sl.report_date
  JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
  WHERE t.movement_type = 'Closing balance'
)
SELECT l.report_date,
       COUNT(p.product_id) AS items_with_a_minimum_set,
       COALESCE(SUM(COALESCE(s.stock_qty, 0) < p.minimum_inventory_qty), 0) AS items_below_minimum,
       GROUP_CONCAT(CASE WHEN COALESCE(s.stock_qty, 0) < p.minimum_inventory_qty THEN p.product_code END
                    ORDER BY p.product_code SEPARATOR ', ') AS items_below_minimum_codes
FROM latest l
LEFT JOIN dim_products p ON p.product_id <> -1 AND p.minimum_inventory_qty > 0
LEFT JOIN stock s ON s.product_id = p.product_id
GROUP BY l.report_date;
```

Why: the minimum level IS in the SS Manufacturing data: dim_products.minimum_inventory_qty, the minimum set in SAP, where 0 means no minimum is set for that item - never write a MISSING line for it. Compare it with the stock of the newest stock report ('Closing balance' rows; an item with no closing row has 0 stock). ONE summary row, also when nothing is below: items_with_a_minimum_set tells "no item has a minimum set in SAP" (0) apart from "every item is above its minimum". Always return report_date.
Expected: report 2026-10-31: 1,545 items with a minimum set, 122 below their minimum (CO00001, CO00006, CO00013 ...).

## Q: What will our sales be next month?

Also asked as: sales forecast for next month; expected / projected sales next month; how much will we sell next month; revenue prediction for the coming month.

```sql
WITH f AS (
  SELECT sales_month, period_start, period_end, forecast_inr, low_inr, high_inr, mape_pct, model_name, data_to
  FROM ml_sales_forecast
  WHERE level = 'TOTAL'
  ORDER BY period_start
  LIMIT 1
)
SELECT f.sales_month,
       f.period_start,
       f.period_end,
       f.forecast_inr,
       f.low_inr,
       f.high_inr,
       f.mape_pct,
       f.model_name,
       f.data_to,
       (SELECT ROUND(SUM(il.net_taxable_value), 2) FROM fact_invoice_lines il
        WHERE il.invoice_date BETWEEN f.period_start AND LEAST(f.period_end, CURDATE())) AS actual_so_far_inr,
       (SELECT MAX(il.invoice_date) FROM fact_invoice_lines il
        WHERE il.invoice_date BETWEEN f.period_start AND LEAST(f.period_end, CURDATE())) AS actual_to
FROM f;
```

Why: a forecast is in the ML results (ml_sales_forecast, an estimate made by run_ml from the invoices up to data_to) - never NO_DATA. 'TOTAL' rows = the whole company; "next month" = the first forecast sales month (the sales month after the newest complete one in the data - the same month as the product forecasts). The answer calls it a forecast and gives forecast_inr with its range (low_inr to high_inr, an 80 % range), the model's average error (mape_pct %), the sales month's dates and data_to. When that month has already started, its actual sales so far (actual_so_far_inr, invoices up to actual_to) are given next to the forecast - never added to it.
Expected: (run of 18-Nov-2026, data to 31-Oct-2026) sales month Nov 2026 (21-Oct-2026 to 20-Nov-2026): forecast 534,887,655.19 (range 498,487,638.37 to 571,287,672.01), mape_pct 4.16, Holt-Winters; actual so far 189,269,525.00 (invoices up to 31-Oct-2026).

## Q: What are the sales forecasts for the next 3 months?

Also asked as: sales forecast for the next 3 sales months; expected sales Nov 2026 to Jan 2027; what will sales be in the coming months; forecast vs actual this month; forecast for the next 6 / 12 months (change the LIMIT).

```sql
WITH actual AS (
  SELECT f.sales_month,
         ROUND(SUM(il.net_taxable_value), 2) AS actual_so_far_inr,
         MAX(il.invoice_date) AS actual_to
  FROM ml_sales_forecast f
  JOIN fact_invoice_lines il ON il.invoice_date BETWEEN f.period_start AND f.period_end
  WHERE f.level = 'TOTAL'
    AND il.invoice_date <= CURDATE()
  GROUP BY f.sales_month
)
SELECT f.sales_month,
       f.period_start,
       f.period_end,
       f.forecast_inr,
       f.low_inr,
       f.high_inr,
       f.mape_pct,
       f.data_to,
       a.actual_so_far_inr,
       a.actual_to
FROM ml_sales_forecast f
LEFT JOIN actual a ON a.sales_month = f.sales_month
WHERE f.level = 'TOTAL'
ORDER BY f.period_start
LIMIT 3;
```

Why: the 'TOTAL' rows of ml_sales_forecast are the next 12 sales months after the data (data_to), Nov 2026 to Oct 2027; the first 3 in period order are the next 3 sales months. For another number of months change the LIMIT (the next 6 months = LIMIT 6; the next 12 months / all forecast months = no LIMIT); more than 12 months ahead is not forecast. A forecast month that already has invoices (sales month Nov 2026 = 21-Oct-2026 to 20-Nov-2026: invoices of 21-31 Oct only) also gets its actual so far from fact_invoice_lines, in its own column - never added to forecast_inr. Each month: forecast_inr, low_inr to high_inr, mape_pct.
Expected: (run of 18-Nov-2026, data to 31-Oct-2026) 3 rows, mape_pct 4.16 - Nov 2026 534,887,655.19 (498,487,638.37 to 571,287,672.01; actual so far 189,269,525.00, invoices up to 31-Oct-2026); Dec 2026 520,192,526.92 (481,252,539.80 to 559,132,514.04); Jan 2027 546,371,110.54 (501,753,327.90 to 590,988,893.18).

## Q: What will our total sales be in 2027?

Also asked as: sales of next year; total sales of 2027; forecast for the whole year; sales this quarter / next quarter (forecast); full-year forecast.

```sql
SELECT f.sales_month, f.period_start, f.period_end,
       ROUND(f.forecast_inr, 2) AS forecast_inr,
       ROUND(f.low_inr, 2) AS low_inr,
       ROUND(f.high_inr, 2) AS high_inr,
       f.mape_pct, f.data_to,
       COUNT(*) OVER () AS forecast_months_in_period
FROM ml_sales_forecast f
WHERE f.level = 'TOTAL' AND f.period_end >= '2027-01-01' AND f.period_start <= '2027-12-31'
ORDER BY f.period_start;
```

Why: there are no actual sales after data_to (31-Oct-2026), and the forecast covers only the next 12 sales months (Nov 2026 to Oct 2027) - so a year (or quarter) question gets the forecast months INSIDE the period, one row per month, with range, accuracy and data_to, and forecast_months_in_period says how many. The answer names those months with their amounts and says the rest of the period is not forecast; never add the months up into the year's total, and the data date is data_to, never a period end.
Expected: (run of 18-Nov-2026, data to 31-Oct-2026) 10 rows, mape_pct 4.16, data_to 2026-10-31 - sales months Jan 2027 to Oct 2027 (21-Dec-2026 to 20-Oct-2027) are forecast in 2027: Jan 2027 about 54.6 Cr (range 50.2 - 59.1 Cr), Feb 2027 54.0 Cr (49.2 - 58.7), Mar 2027 62.8 Cr (56.8 - 68.8), Apr 2027 57.6 Cr (51.7 - 63.4), May 2027 54.6 Cr (48.7 - 60.6), Jun 2027 56.3 Cr (49.8 - 62.9), Jul 2027 50.0 Cr (43.9 - 56.1), Aug 2027 53.7 Cr (46.8 - 60.7), Sep 2027 56.3 Cr (48.6 - 64.0), Oct 2027 58.3 Cr (50.0 - 66.7); Nov and Dec 2027 are not forecast and have no actual sales yet.

## Q: What is the sales forecast for GCI TX-675 next month?

Also asked as: forecast for product FG01484; how much of this product will we sell next month; which products will sell the most next month; product-wise sales forecast.

```sql
SELECT f.product_code,
       f.product_description,
       f.sales_month,
       f.period_start,
       f.period_end,
       f.forecast_inr,
       f.low_inr,
       f.high_inr,
       f.mape_pct,
       f.data_to,
       COUNT(*) OVER () AS matches
FROM ml_sales_forecast f
WHERE f.level = 'PRODUCT'
  AND f.horizon_months = 1
  AND (f.product_description LIKE '%GCI TX-675%' OR f.product_code LIKE '%GCI TX-675%')
ORDER BY f.forecast_inr DESC;
```

Why: product forecasts ('PRODUCT' rows) exist only for the top 10 products by sales, for the next 3 sales months (Nov 2026, Dec 2026, Jan 2027; one row per product and month). "Next month" = horizon_months = 1; for the next 3 months of a product leave that filter out and ORDER BY f.product_code, f.period_start (a later month has no product forecast). Match the typed name with LIKE on the description and the code, one row per product. No row = no forecast for that product (it is not one of the top 10) - say so, never estimate one from past sales. "Which products will sell the most next month" = the same without the LIKE.
Expected: (run of 18-Nov-2026, data to 31-Oct-2026) 1 row: FG01484 GCI TX-675-3A 0.4kW (415V 50Hz), sales month Nov 2026: forecast 16,517,213.63 (14,327,784.52 to 18,862,236.33), mape_pct 6.48. 'Coolant pump' gives no row (no coolant pump is in the top 10).

## Q: Which customers might stop buying from us?

Also asked as: customers at risk; churn risk; which customers are we likely to lose; customers whose buying is dropping; at-risk customers.

```sql
SELECT r.customer_name,
       r.risk_score,
       r.risk_level,
       r.reason,
       r.last_invoice_date,
       r.days_since_last_invoice,
       r.sales_last_3m_inr,
       r.sales_prev_3m_inr,
       r.change_pct,
       r.lifetime_sales_inr,
       SUM(r.risk_level = 'High') OVER () AS high_risk_customers,
       (SELECT MAX(l.data_to) FROM ml_run_log l) AS data_to
FROM ml_customer_risk r
ORDER BY r.risk_score DESC, r.lifetime_sales_inr DESC
LIMIT 20;
```

Why: "might stop buying" is a prediction: the risk score of ml_customer_risk (0-100, an estimate from recency, frequency and the sales trend up to data_to), highest first, with the reason. high_risk_customers = how many customers are 'High' in all (not only the 20 rows). Not the same as "Which customers stopped buying from us?" (no invoice in the last 3 months - fact_invoice_lines).
Expected: (run of 17-Nov-2026, data to 31-Oct-2026) 118 High-risk customers (25 with risk 100.00); first Aurora Fluid Power Limited (risk 100.00, last invoice 17-Jul-2026, 106 days, lifetime 119,592,664.50), then Sunrise Fluid Power Pvt Ltd and Tejas Fabricators Pvt. Ltd.

## Q: What customer groups do we have?

Also asked as: customer segments; kinds of customers by buying behaviour; group our customers; customer clusters; which segment is the biggest.

```sql
SELECT s.segment_no,
       s.segment_name,
       COUNT(*) AS customers,
       ROUND(SUM(s.sales_inr), 2) AS segment_sales_inr,
       ROUND(AVG(s.sales_inr), 2) AS avg_sales_per_customer_inr,
       ROUND(AVG(s.invoices), 1) AS avg_invoices,
       ROUND(AVG(s.recency_days), 0) AS avg_days_since_last_invoice
FROM ml_customer_segments s
GROUP BY s.segment_no, s.segment_name
ORDER BY segment_sales_inr DESC;
```

Why: customer groups by buying behaviour (how recently, how often, how much) are the segments of ml_customer_segments, found by a clustering model - one row per segment with its customers and sales. SAP's own customer_group ('Local Customer' / 'Foreign Customer', dim_customers) only when the user says local / foreign / SAP group. The customers of one segment: SELECT customer_name, sales_inr ... WHERE segment_name = '...'.
Expected: (run of 17-Nov-2026, data to 31-Oct-2026) 5 groups: Big regular buyers 387 customers, 8,698,526,132.79; Regular buyers 1,330, 2,641,732,728.45; New customers 1,395, 1,066,053,204.50; Lapsed 678, 513,159,072.20; Occasional buyers 284, 10,488,744.00.

## Q: Are there any unusual invoices?

Also asked as: strange or suspicious invoices; invoices with odd prices; unusual quantities; large credit notes; anomalies in billing; invoices to check.

```sql
SELECT a.alert_type,
       a.invoice_number,
       a.invoice_date,
       a.customer_name,
       a.product_code,
       a.product_description,
       a.value_inr,
       a.typical_inr,
       a.score,
       a.reason,
       COUNT(*) OVER () AS alerts,
       COUNT(*) OVER (PARTITION BY a.alert_type) AS alerts_of_this_type
FROM ml_invoice_alerts a
ORDER BY a.score DESC
LIMIT 20;
```

Why: unusual invoice lines are found by a model (ml_invoice_alerts): 'Unusual price', 'Unusual quantity' or 'Large credit note', most unusual first (score), with the value, the typical value and the reason. They are lines to check, not proven errors. alerts = all alerts, alerts_of_this_type = per alert type.
Expected: (run of 17-Nov-2026, data to 31-Oct-2026) 172 alerts (100 Unusual price, 60 Unusual quantity, 12 Large credit note); most unusual SSMI/D/2425/3672 of 21-Sep-2024, Nilgiri Tech Industries Pvt. Ltd., FG02665: unit price 26,827.50 vs usual 38,880.00 (score 7.42).

## Q: Which products are bought together?

Also asked as: products often bought together; what else do customers buy with FG00040; cross-sell; product pairs; market basket.

```sql
SELECT pp.product_a_code,
       pp.product_a_description,
       pp.product_b_code,
       pp.product_b_description,
       pp.orders_together,
       pp.support_pct,
       pp.confidence_pct,
       pp.lift
FROM ml_product_pairs pp
ORDER BY pp.orders_together DESC, pp.lift DESC
LIMIT 10;
```

Why: pairs of products on the same sales orders (ml_product_pairs, cancelled orders left out; each pair once, product A = the one with fewer orders): orders_together = sales orders with both, confidence_pct = of the orders with product A the % that also have B, lift above 1 = bought together more often than by chance. With one product X ("bought with X"): WHERE pp.product_a_description LIKE '%X%' OR pp.product_b_description LIKE '%X%' OR pp.product_a_code LIKE '%X%' OR pp.product_b_code LIKE '%X%', and name the other product of each pair.
Expected: (run of 17-Nov-2026, data to 31-Oct-2026) 242 pairs; top FG00580 Coolant Unit HM-132-3A + FG01116 Procon Pump PR-317-3A on 146 orders (confidence 27.92 %, lift 11.77), then FG00542 + FG01484 on 144 orders (lift 1.98).

## Q: Which items will run out of stock soon?

Also asked as: items running out of stock; days of stock left; when will we run out; stock-out risk; items to reorder before they run out.

```sql
SELECT r.product_code,
       r.product_description,
       r.report_date,
       r.stock_qty,
       r.avg_daily_sales_qty,
       r.days_left,
       r.runout_date,
       DATEDIFF(r.runout_date, CURDATE()) AS days_from_today,
       r.status,
       SUM(r.status = 'Under 30 days') OVER () AS items_under_30_days,
       SUM(r.status = 'Under 90 days') OVER () AS items_under_90_days,
       (SELECT COUNT(*) FROM ml_stock_runout o WHERE o.status = 'Out of stock') AS items_out_of_stock
FROM ml_stock_runout r
WHERE r.status IN ('Under 30 days', 'Under 90 days')
ORDER BY r.days_left, r.product_code
LIMIT 50;
```

Why: run-out = the stock of the latest stock report (report_date) divided by the recent average daily sales (ml_stock_runout, an estimate): soonest first, with the estimated runout_date counted from report_date, not today: days_from_today < 0 = the run-out date is already past - say the item would have run out by then (before today) unless new stock arrived. 'Out of stock' items have run out already (counted apart); 'No recent sales' items are not running out. Always keep the count columns (items_under_30_days ...) - the list is cut at 50, so the answer says e.g. "349 items are under 30 days; the 50 soonest are shown", never "the full list". Always say the report_date.
Expected: (run of 17-Nov-2026, data to 31-Oct-2026) stock report 31-Oct-2026: 349 items under 30 days, 357 under 90 days, 0 out of stock; first FG00966 Coolant pump GX-597-1B 3.7kW (stock 4, 0.600 sold a day, 6.7 days, runs out 06-Nov-2026 = days_from_today -11 on 17-Nov-2026: already past); 50 rows shown of 349 + 357.
