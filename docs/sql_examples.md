# Example questions with their correct SQL (ai_gold, MySQL 8)

Each example: the question, the correct read-only SELECT, why it is written that way, and the key result
it returns on the BASE data (inputdata/ only, loaded by `load_gold.py` without --batch; checked as nop_ai_reader).
After an incremental batch is loaded most totals are bigger: reuse the SQL pattern, never copy an Expected
number into an answer - every number in an answer must come from the rows the query returns.

## Q: What were net sales in each NOP sales month of FY 2026-27?

Also asked as: monthly sales for FY 2026-27; month-wise net sales this financial year (NOP months, 21st to 20th).

```sql
SELECT c.nop_sales_month,
       MIN(c.nop_sales_period_start) AS period_start,
       MAX(c.nop_sales_period_end) AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.nop_sales_year = '2627'
GROUP BY c.nop_sales_period_no, c.nop_sales_month
ORDER BY c.nop_sales_period_no;
```

Why: net sales = SUM(net_taxable_value) (credit notes already negative); a FY split by NOP sales month filters nop_sales_year so each month (21st to 20th) is complete.
Expected: (base data) 6 rows - Apr 2026 7,950,880.00; May 2026 5,806,675.00; Jun 2026 12,767,485.00; Jul 2026 5,424,475.00; Aug 2026 7,604,315.00; Sep 2026 1,955,500.00 (total 41,509,330.00; no invoices after 13-Sep-2026).

## Q: What was the sales value including freight in NOP sales month Sep 2026?

Also asked as: sales incl. freight for Sep 2026; how much did we bill including freight and packing in that month.

```sql
SELECT MIN(c.nop_sales_period_start) AS period_start,
       MAX(c.nop_sales_period_end) AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,
       ROUND(SUM(COALESCE(il.freight_amount, 0)), 2) AS freight_inr,
       ROUND(SUM(il.net_taxable_value) + SUM(COALESCE(il.freight_amount, 0)), 2) AS sales_value_incl_freight_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.nop_sales_month = 'Sep 2026';
```

Why: sales value incl. freight = net_taxable_value + freight_amount (freight is NULL on credit notes); NOP month 'Sep 2026' = 21-Aug-2026 to 20-Sep-2026.
Expected: (base data) 2026-08-21 to 2026-09-20 - net sales 1,955,500.00 + freight 8,000.00 = sales value 1,963,500.00.

## Q: Who were the top 5 customers by invoice value in Aug 2026?

Also asked as: biggest customers in August 2026; top customers by sales for the month Aug 2026.

```sql
SELECT cu.customer_name,
       ROUND(SUM(il.net_taxable_value), 2) AS invoice_value_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_customers cu ON cu.customer_id = il.customer_id
WHERE c.nop_sales_month = 'Aug 2026'
GROUP BY cu.customer_id, cu.customer_name
ORDER BY invoice_value_inr DESC
LIMIT 5;
```

Why: a month name means the NOP sales month (21-Jul-2026 to 20-Aug-2026); invoice value = SUM(net_taxable_value); customer name from dim_customers.
Expected: (base data) Aurora Fluid Power Limited 1,730,000.00; Meridian Engineering Works Private Limited 1,316,700.00; Pioneer Star Precision Components GmbH 1,238,350.00; Meridian Hydraulics Limited 747,750.00; Tejas Industrial Solutions Private Limited 450,000.00.

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

Why: a FY total uses dim_calendar.financial_year (1-Apr to 31-Mar) of the invoice date; credit and debit notes count in the FY of the note date, so invoiced + credit notes (negative) + debit notes = net sales. data_from / data_to are the first and last invoice date of each FY in the data: FY 2025-26 has invoices only from 21-Dec-2025 and the current FY is not over, so the answer must say which dates each total covers.
Expected: (base data) FY 2025-26 net 33,851,075.00 (invoiced 34,125,455.00, credit notes -274,380.00, debit notes 0.00; invoices only from 21-Dec-2025); FY 2026-27 net 38,985,740.00 (invoiced 39,260,620.00, credit notes -274,880.00, debit notes 0.00). (data of 14-Oct-2026, base + batch_001) FY 2026-27 net 21,490,309,878.78 = invoiced 21,518,589,799.00, credit notes -28,333,209.22, debit notes 53,289.00 (data 01-Apr-2026 to 20-Mar-2027).

## Q: How many sales orders are open and what is their value?

Also asked as: order backlog; pending orders not yet invoiced; value of open orders.

```sql
SELECT COUNT(DISTINCT s.so_number, c.financial_year) AS open_orders,
       COUNT(*) AS open_order_lines,
       ROUND(SUM(s.total_amount), 2) AS open_value_before_gst_inr,
       ROUND(SUM(s.total_amount + s.tax_total), 2) AS open_value_incl_gst_inr
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
WHERE s.status = 'Open';
```

Why: an order = so_number + financial year (SO numbers restart every FY); order value before GST = total_amount.
Expected: (base data) 27 open orders, 50 lines, 16,547,240.00 INR before GST (18,834,723.20 incl. GST).

## Q: Which customers have open sales orders, and for how much?

Also asked as: open orders by customer; customer-wise pending order value.

```sql
SELECT cu.customer_name,
       COUNT(DISTINCT s.so_number, c.financial_year) AS open_orders,
       ROUND(SUM(s.total_amount), 2) AS open_value_before_gst_inr
FROM fact_sales_order_lines s
JOIN dim_calendar c ON c.date_id = s.order_date_id
JOIN dim_customers cu ON cu.customer_id = s.customer_id
WHERE s.status = 'Open'
GROUP BY cu.customer_id, cu.customer_name
ORDER BY open_value_before_gst_inr DESC;
```

Why: open = status 'Open'; orders counted by so_number + financial year; value before GST.
Expected: (base data) 16 customers (total 16,547,240.00); top 3 Zenith Precision Components LLP 2 orders 2,934,000.00; Everest Engineering Works Ltd 3 orders 2,502,125.00; Apex Machine Tools Private Limited 5 orders 2,276,140.00; smallest Neptune Fluid Power Limited 1 order 5,000.00.

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
Expected: (base data) 3 notes - NOPI/CN/2627/1 2026-04-25 Delta Engineering Works Limited 145,000.00 (171,100.00 incl. GST); NOPI/CN/2627/2 2026-05-04 Delta Engineering Works Limited 6,630.00 (7,823.40); NOPI/CN/2627/3 2026-06-24 Granite Automation Pvt Ltd 123,250.00 (145,435.00); total 274,880.00.

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
Expected: (base data) Domestic 31,652,385.00; Export 7,289,105.00; Service 44,250.00 (total 38,985,740.00).

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
Expected: (base data) Karthik Menon 30 invoices 11,723,880.00; Rahul Verma 29 invoices 8,778,175.00; Divya Nair 24 invoices 5,453,135.00; Sanjay Kulkarni 14 invoices 5,208,300.00; Priya Iyer 18 invoices 3,962,740.00; Arjun Rao 15 invoices 3,859,510.00.

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
Expected: (base data) Not classified 9,605,035.00; YTH-PARTS 6,527,120.00; GCI 5,072,375.00; Trochoid pumps 4,704,775.00; Hydraulic motors 4,667,350.00; Coolant pumps 4,348,725.00; Procon Pumps 2,306,800.00; Coolant Units 1,753,560.00 (total 38,985,740.00).

## Q: What is the stock value as on 20-Sep-2026?

Also asked as: inventory value on 20 Sep 2026; closing stock value on a given report date.

```sql
SELECT sl.report_date,
       COUNT(*) AS items,
       ROUND(SUM(sl.cumulative_qty), 3) AS stock_qty,
       ROUND(SUM(sl.cumulative_value), 2) AS stock_value_inr
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'Closing balance'
  AND sl.report_date = '2026-09-20'
GROUP BY sl.report_date;
```

Why: stock value on a date = SUM(cumulative_value) of the 'Closing balance' rows of that report_date only (never SUM every row).
Expected: (base data) 52 items, stock quantity 542.000, stock value 23,856,971.91 INR.

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
Expected: (base data) report 2026-09-20 - 52 items, stock quantity 542.000, stock value 23,856,971.91 INR (with batch_001 loaded: report 2027-03-20 - 5,010 items, 374,137.000 units, 13,997,769,323.98 INR).

## Q: What was the COGS (cost of goods sold) in the stock report as on 20-Sep-2026?

Also asked as: COGS in the 20-Sep-2026 stock report; COGS rate per item on a given report date.

```sql
SELECT COUNT(*) AS cogs_rows,
       ROUND(COALESCE(SUM(-sl.transaction_value), 0), 2) AS cogs_value_inr,
       ROUND(SUM(-sl.transaction_value) / NULLIF(SUM(-sl.quantity), 0), 2) AS cogs_rate_per_unit
FROM fact_stock_ledger sl
JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
WHERE t.movement_type = 'COGS'
  AND sl.report_date = '2026-09-20';
```

Why: COGS = movements whose document prefix is IN / CN / DN / RE (movement_type 'COGS'); COGS value = SUM(-transaction_value), rate = SUM(-transaction_value) / SUM(-quantity).
Expected: (base data) 0 COGS rows, COGS value 0.00, rate NULL - the report's stock-outs are 'SI' documents = Production (-1,181,063.91), not COGS.

## Q: What were net sales in Japanese yen for each NOP sales month of FY 2026-27?

Also asked as: sales in JPY; yen value of monthly sales; convert sales from INR to JPY.

```sql
SELECT c.nop_sales_month,
       f.exchange_rate,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr,
       ROUND(SUM(il.net_taxable_value * f.exchange_rate), 2) AS net_sales_jpy
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
JOIN dim_fx_rates f ON f.fx_rate_id = il.fx_rate_id
WHERE c.nop_sales_year = '2627'
GROUP BY c.nop_sales_period_no, c.nop_sales_month, f.exchange_rate
ORDER BY c.nop_sales_period_no;
```

Why: JPY = INR x dim_fx_rates.exchange_rate of the window holding the invoice date (fact_invoice_lines.fx_rate_id); each window is one NOP sales month.
Expected: (base data) Apr 2026 rate 1.69 13,436,987.20 JPY; May 2026 1.79 10,393,948.25; Jun 2026 1.64 20,938,675.40; Jul 2026 1.72 9,330,097.00; Aug 2026 1.65 12,547,119.75; Sep 2026 1.69 3,304,795.00.

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
Expected: (base data) fact_invoice_lines 343 lines - 0 Unknown customer, 14 Unknown product (service lines); fact_sales_order_lines 1,098 lines - 0 Unknown customer, 36 Unknown product (service lines).

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
Expected: (base data) FY 2024-25 264 orders 103,113,900.00; FY 2025-26 288 orders 100,822,640.00; FY 2026-27 135 orders 52,835,870.00.

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
Expected: (base data) 1.JAPAN 2,802,640.00; 2.ASIA 31,689,510.00; 3.AMERICA 321,500.00; 4.EUROPE 527,750.00; 5.MIDDLE EAST 3,644,340.00.

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
Expected: (base data) Not given 136 lines 28,834,295.00; OEM 48 lines 9,462,245.00; AFT 5 lines 689,200.00.

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
Expected: (base data) 3 lines, order date 2026-06-05, status Closed, Granite Automation Pvt Ltd - FG00007 123,250.00; FG00047 76,500.00; FG00063 183,600.00 (order total 383,350.00 before GST).

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

Why: the user asked for the calendar month, so dim_calendar.month_year (1st to last day) is used instead of the NOP sales month; invoices are counted on INVOICE rows only.
Expected: (base data) 17 invoices, 5,440,490.00 INR.

## Q: Which 5 items had the highest stock value on 20-Sep-2026?

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
  AND sl.report_date = '2026-09-20'
ORDER BY sl.cumulative_value DESC
LIMIT 5;
```

Why: the stock of each item on the report date is its 'Closing balance' row (cumulative_qty / cumulative_value).
Expected: (base data) FG00013 40 units 4,508,274.80; FG00097 33 units 4,274,468.55; FG00078 23 units 2,639,677.11; FG00040 20 units 1,620,174.20; FG00066 13 units 1,603,787.77.

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
Expected: (base data) no rows - the base data has no dates with sales in both years (last year's invoices start 21-Dec-2025, this year's end 13-Sep-2026). With batch_001 loaded: 21-Dec-2025 to 20-Mar-2026 vs 21-Dec-2026 to 20-Mar-2027; 24 customers in both years, 3,370 new, 12 lost; Highest growth Everest Engineering Works Ltd 2,500.00 -> 9,795,712.50 (391,728.50 %); Biggest decline Coral Industrial Solutions Pvt. Ltd. 616,000.00 -> 2,500.00 (-99.59 %); Biggest lost customer Orion Precision Components Pvt. Ltd. 1,006,150.00 -> 0.00; Biggest new customer Allied Castings Limited 0.00 -> 370,019,228.00.

## Q: How much did Allied Castings buy in Feb 2027?

Also asked as: sales to Everest Engineering this year; how much did we sell to Everest Engineering in FY 2026-27; sales to <part of a customer name> this financial year; how much did <part of a customer name> buy; sales of a customer whose name is typed partly; customer name search.

```sql
SELECT cu.customer_name,
       ROUND(COALESCE(SUM(il.net_taxable_value), 0), 2) AS net_sales_inr,
       COUNT(*) OVER () AS customers_matched
FROM dim_customers cu
LEFT JOIN fact_invoice_lines il
       ON il.customer_id = cu.customer_id
      AND il.invoice_date_id IN (SELECT c.date_id FROM dim_calendar c WHERE c.nop_sales_month = 'Feb 2027')
WHERE cu.customer_name LIKE '%Allied Castings%'
GROUP BY cu.customer_id, cu.customer_name
ORDER BY net_sales_inr DESC;
```

Why: the user's name is partial, so LIKE '%...%' finds every customer whose name contains it; starting from dim_customers with a LEFT JOIN keeps matching customers without sales (0); customers_matched tells the answer how many customers the name matched, so it names each one instead of adding them up. For a whole financial year use `c.financial_year = '2627'` inside the same ON - still one row per matching customer.
Expected: (base data) no rows - no base customer is called 'Allied Castings'. With batch_001 loaded: 2 customers matched - Allied Castings Limited 134,734,470.50; Allied Castings Pvt Ltd 1,332,000.00 (NOP Feb 2027 = 21-Jan-2027 to 20-Feb-2027). Same SQL for 'Everest Engineering' in FY 2026-27: 4 matched - 15,796,419.50 / 300,630.00 / 0.00 / 0.00.

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
Expected: (base data) report 2026-09-20 - 0 COGS rows, 0.00 (its stock-outs are 'SI' = Production). With batch_001 loaded: report 2027-03-20 - 31,667 rows, 168,348.000 units, 6,402,963,668.89 INR, rate 38,034.09 per unit.

## Q: When was the data last loaded, and how many rows did that load add?

Also asked as: last data load; when was ai_gold refreshed; what did the last load add, update or skip; data freshness; load history.

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
Expected: (base data) run 1 FULL from 'inputdata', 10 tables, 2,929 rows inserted, 0 updated, 0 skipped. With batch_001 loaded: run 2 INCREMENTAL 'batch_001' at 2026-10-06 19:10:45, 8 tables, 318,461 inserted, 57 updated, 573 skipped (fact_invoice_lines +100,377; fact_sales_order_lines +100,162; fact_stock_ledger +108,084; dim_customers +4,957; dim_products +4,850 ...).

## Q: How much GST did we collect in Jan 2027?

Also asked as: GST in Jan 2027; total GST (IGST + CGST + SGST + cess) for a month; net GST after credit notes; tax collected in a NOP sales month.

```sql
SELECT MIN(c.nop_sales_period_start) AS period_start,
       MAX(c.nop_sales_period_end) AS period_end,
       ROUND(SUM(CASE WHEN il.document_type = 'CREDIT_NOTE' THEN -1 ELSE 1 END
                 * (COALESCE(il.igst_amount, 0) + COALESCE(il.cgst_amount, 0)
                    + COALESCE(il.sgst_amount, 0) + COALESCE(il.cess_amount, 0))), 2) AS net_gst_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.nop_sales_month = 'Jan 2027';
```

Why: a month name means the NOP sales month (here 21-Dec-2026 to 20-Jan-2027), also for GST; GST = igst + cgst + sgst + cess; these amounts are positive as printed on credit notes too, so credit note rows are subtracted (CASE ... THEN -1).
Expected: (base data) no invoices in NOP Jan 2027 (base invoices end 13-Sep-2026) - net_gst_inr NULL. With batch_001 loaded: 2026-12-21 to 2027-01-20, net GST 565,748,776.09 INR (the calendar month 1-31 Jan would give 565,689,314.54 - a different figure).

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
Expected: (base data) May 2026 1.79; Jun 2026 1.64; Jul 2026 1.72; Aug 2026 1.65; Sep 2026 1.69; Oct 2026 1.79. With batch_001 loaded: Oct 2026 1.79; Nov 2026 1.74; Dec 2026 1.77; Jan 2027 1.71; Feb 2027 1.68; Mar 2027 1.73.

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

Why: "this year" / "last year" = the current and the previous FY. The query gives BOTH: each FY's total with the dates the data covers (FY 2025-26 has invoice data only from 21-Dec-2025, and the current FY is not over), and a fair growth % on the SAME dates in both years (the dates where both years have data, shifted by one year), calculated in SQL (revenue_growth_pct). The answer gives the two FY totals with their dates first, then the same-dates growth. When the user said "profit %", the reply also has the line "MISSING: true profit - the NOP data has selling prices but not the cost of the items sold", and the answer calls the % revenue growth, never profit.
Expected: (base + batch_001, 08-Oct-2026) FY 2025-26 INR 33,851,075.00 (21-Dec-2025 to 31-Mar-2026); FY 2026-27 INR 21,490,309,878.78 (01-Apr-2026 to 20-Mar-2027); same dates 21-Dec-2025 to 20-Mar-2026 INR 31,327,485.00 vs 21-Dec-2026 to 20-Mar-2027 INR 11,320,219,385.78, revenue_growth_pct 36,035.10.

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

Why: a new customer = the customer's FIRST invoice line in the data falls in the period; their sales = net sales in the period. Always return invoice_history_starts (where the invoice data starts, 21-Dec-2025): "first" is checked against all invoices since that date (a customer who bought only before it looks new). The answer says e.g. "4,158 customers bought for the first time in FY 2026-27 (checked against all invoices since 21-Dec-2025, where our data starts)" - never that the period's data starts on that date. The Unknown customer (-1) is not counted as a customer; its sales are shown separately (unknown_customer_sales_inr). customers_buying and all_sales_inr show how big the new customers are compared with everyone who bought.
Expected: (base + batch_001, 08-Oct-2026) 01-Apr-2026 to 31-Mar-2027, invoice_history_starts 21-Dec-2025: 4,158 new customers, INR 21,261,429,447.28, out of 4,196 customers buying and INR 21,490,309,878.78 in all; Unknown customer INR 62,652,560.00.

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

Why: "stopped buying" = the customer bought before but has no invoice in the last 3 months of the data: no invoice on or after no_invoice_on_or_after (the newest invoice date minus 3 months; days_before_newest_invoice = how many days that is), unless the user gives another period (then change INTERVAL 3 MONTH). The newest invoice date comes from the data (MAX(invoice_date)), never a fixed date. The Unknown customer (-1) is not a customer. Biggest customers first; stopped_customers is the count of all of them (also when the list is longer than the rows shown). The answer says e.g. "786 customers bought before but have no invoice on or after 20-Dec-2026 (90 days before the newest invoice, 20-Mar-2027)" and that the period can be changed.
Expected: (base + batch_001, 08-Oct-2026) newest invoice 20-Mar-2027, no invoice on or after 20-Dec-2026 (90 days before): 786 customers; biggest Nova Robotics LLP (last invoice 14-Dec-2026, INR 10,792,380.00), then Vertex Equipment Limited (03-Dec-2026, INR 9,221,710.00).

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
Expected: (base + batch_001) report 2027-03-20: 31 items with zero stock, 0 negative, 5,010 items in the report (base data: report 2026-09-20 - 6 zero of 52).

## Q: What were last month's sales, and which customer bought the most?

Also asked as: last month sales and the top customer; which customer gave us the most revenue last month; previous month net sales.

```sql
WITH last_month AS (
  SELECT p.nop_sales_month, p.nop_sales_period_start, p.nop_sales_period_end
  FROM dim_calendar t
  JOIN dim_calendar p ON p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY
  WHERE t.full_date = CURDATE()
),
customer_sales AS (
  SELECT cu.customer_name, SUM(il.net_taxable_value) AS sales_inr
  FROM fact_invoice_lines il
  JOIN last_month lm ON il.invoice_date BETWEEN lm.nop_sales_period_start AND lm.nop_sales_period_end
  JOIN dim_customers cu ON cu.customer_id = il.customer_id
  GROUP BY cu.customer_id, cu.customer_name
)
SELECT lm.nop_sales_month AS nop_month,
       lm.nop_sales_period_start AS period_from,
       lm.nop_sales_period_end AS period_to,
       (SELECT ROUND(SUM(sales_inr), 2) FROM customer_sales) AS net_sales_inr,
       cs.customer_name AS top_customer,
       ROUND(cs.sales_inr, 2) AS top_customer_sales_inr
FROM last_month lm
LEFT JOIN customer_sales cs ON TRUE
ORDER BY cs.sales_inr DESC
LIMIT 1;
```

Why: "last month" is worked out from TODAY (CURDATE()) in dim_calendar - never from the newest invoice and never by sorting nop_sales_month, which is text ('Sep 2026' sorts after 'Mar 2027'). Last month = the NOP sales month that ends the day before today's NOP month starts: on 12-Oct-2026 today is in 'Oct 2026', so last month = 'Sep 2026' (21-Aug-2026 to 20-Sep-2026). For "this month" use the SQL of the example "What are our sales this month so far?" (only up to today). The answer states the month and its dates.
Expected: (asked on 12-Oct-2026) Sep 2026, 21-Aug-2026 to 20-Sep-2026: net sales 1,955,500.00; top customer Meridian Hydraulics Limited 1,070,100.00.

## Q: What are our sales this month so far?

Also asked as: current month sales; this month's net sales; sales of the running month; how much did we sell this month; MTD (month to date) sales; sales so far this month; this month top customer.

```sql
WITH this_month AS (
  SELECT nop_sales_month, nop_sales_period_start, LEAST(nop_sales_period_end, CURDATE()) AS so_far_to
  FROM dim_calendar
  WHERE full_date = CURDATE()
)
SELECT tm.nop_sales_month AS nop_month,
       tm.nop_sales_period_start AS period_from,
       tm.so_far_to AS period_to,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_so_far_inr,
       COUNT(DISTINCT CASE WHEN il.document_type = 'INVOICE' THEN il.invoice_number END) AS invoices_so_far
FROM this_month tm
LEFT JOIN fact_invoice_lines il ON il.invoice_date BETWEEN tm.nop_sales_period_start AND tm.so_far_to
GROUP BY tm.nop_sales_month, tm.nop_sales_period_start, tm.so_far_to;
```

Why: this month is not over yet, so it counts only from its first day up to TODAY (CURDATE()) - never to the month's last day: data dated after today must not be counted. The answer says "so far" with both dates, e.g. "In NOP sales month Nov 2026 so far (21-Oct-2026 to 27-Oct-2026) net sales were ...". For a top customer, a product or a split, keep the same dates (invoice_date BETWEEN period_from AND period_to).
Expected: (asked on 27-Oct-2026) Nov 2026, 21-Oct-2026 to 27-Oct-2026: net sales so far 827,149,042.00 (the whole month in the test data, to 20-Nov-2026, would be 3,869,959,327.00 - wrong).

## Q: Show net sales month by month from Jan 2026 to Mar 2027.

Also asked as: monthly sales from Jan 2026 to Mar 2027; month by month sales between two months; month-wise net sales from Apr 2026 to Sep 2026 after credit and debit notes; monthly sales trend from one month to another; sales of each month in a range of months.

```sql
SELECT c.nop_sales_month,
       c.nop_sales_period_start AS period_start,
       c.nop_sales_period_end AS period_end,
       ROUND(SUM(il.net_taxable_value), 2) AS net_sales_inr
FROM fact_invoice_lines il
JOIN dim_calendar c ON c.date_id = il.invoice_date_id
WHERE c.nop_sales_period_start >= (SELECT MIN(nop_sales_period_start) FROM dim_calendar WHERE nop_sales_month = 'Jan 2026')
  AND c.nop_sales_period_end <= (SELECT MAX(nop_sales_period_end) FROM dim_calendar WHERE nop_sales_month = 'Mar 2027')
GROUP BY c.nop_sales_month, c.nop_sales_period_start, c.nop_sales_period_end
ORDER BY c.nop_sales_period_start;
```

Why: a range of named months is a range of NOP sales months (21st to 20th), one row per NOP month: 'Jan 2026' starts on 21-Dec-2025 and 'Mar 2027' ends on 20-Mar-2027. The first and last month are looked up by name (no date arithmetic). period_start / period_end are the NOP month's own dates from dim_calendar - never MIN / MAX of the invoice dates. Order by nop_sales_period_start, never by the month text. net_taxable_value already has credit notes negative and debit notes positive. Use calendar months (c.month_year) only when the user says "calendar month" or gives exact dates.
Expected: (data of 13-Oct-2026) 15 rows from Jan 2026 (21-Dec-2025 to 20-Jan-2026) 13,356,235.00 to Mar 2027 (21-Feb-2027 to 20-Mar-2027) 3,503,352,034.65; lowest Sep 2026 1,955,500.00; highest Jan 2027 3,953,546,625.88.

## Q: Which customers bought from us between Jan 2026 and Jun 2026 but have bought nothing since Oct 2026?

Also asked as: customers who bought in one period but not since a month; customers who bought earlier but have not bought since Oct 2026; bought in H1 but nothing after that; customers missing since a month.

```sql
WITH bounds AS (
  SELECT (SELECT MIN(nop_sales_period_start) FROM dim_calendar WHERE nop_sales_month = 'Jan 2026') AS bought_from,
         (SELECT MAX(nop_sales_period_end) FROM dim_calendar WHERE nop_sales_month = 'Jun 2026') AS bought_to,
         (SELECT MIN(nop_sales_period_start) FROM dim_calendar WHERE nop_sales_month = 'Oct 2026') AS nothing_since
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

Why: month names are NOP sales months, looked up by name: "between Jan 2026 and Jun 2026" = 21-Dec-2025 to 20-Jun-2026; "nothing since Oct 2026" = no invoice on or after the FIRST day of Oct 2026 (21-Sep-2026) - October itself counts, so never compare with the month's last day. Buying = an INVOICE line; a later credit / debit note is not a purchase. The Unknown customer (-1) is not a customer and gets no row. The answer states the three dates and matching_customers.
Expected: (data of 13-Oct-2026) 5 customers, no invoice on or after 21-Sep-2026: Demo Pump Japan Co., Ltd. 1,255,250.00 (last invoice 08-Aug-2026); Tejas Machine Tools LLC 1,188,155.00; Zenith Precision Components LLP 975,200.00; Coral Fluid Power Pvt. Ltd. 180,840.00; Pioneer Star Grinding Machines Inc. 68,000.00.

## Q: Which items had the biggest increase in stock value between 20-Sep-2026 and 20-Mar-2027?

Also asked as: stock value change per item between two stock reports; items whose stock grew the most; compare stock of two report dates; which items' inventory dropped the most (ORDER BY increase_inr ASC).

```sql
WITH v AS (
  SELECT sl.product_id,
         SUM(CASE WHEN sl.report_date = '2026-09-20' THEN sl.cumulative_value END) AS value_before,
         SUM(CASE WHEN sl.report_date = '2027-03-20' THEN sl.cumulative_value END) AS value_after
  FROM fact_stock_ledger sl
  JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
  WHERE t.movement_type = 'Closing balance' AND sl.report_date IN ('2026-09-20', '2027-03-20')
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

Why: stock on a date = the 'Closing balance' rows of that report. Only items in BOTH reports can be compared - the 20-Sep-2026 report has far fewer items than the 20-Mar-2027 one - so return items_in_both_reports and the items found in one report only, and the answer says e.g. "only 52 items are in both stock reports (4,949 are only in the 20-Mar-2027 report)".
Expected: (data of 13-Oct-2026) 52 items in both reports, 4,949 only in the newer one, 0 only in the older one; biggest increase FG00013 Hydraulic motor GX-981-3A 0.4kW from 4,508,274.80 to 15,666,254.93 (+11,157,980.13), then FG00031 (+11,100,168.72) and FG00027 (+10,185,379.94).

## Q: Which items were in stock on 20-Mar-2027 but had no sales between 21-Sep-2026 and 20-Mar-2027?

Also asked as: unsold stock; slow-moving or dead stock; items in stock with no sales; stock not sold since a date; non-moving inventory; finished goods in stock but not sold.

```sql
WITH stock AS (
  SELECT sl.product_id, sl.cumulative_qty, sl.cumulative_value, p.product_code, p.product_description, p.item_group
  FROM fact_stock_ledger sl
  JOIN dim_stock_movement_types t ON t.movement_type_id = sl.movement_type_id
  JOIN dim_products p ON p.product_id = sl.product_id
  WHERE t.movement_type = 'Closing balance' AND sl.report_date = '2027-03-20'
    AND sl.cumulative_qty > 0 AND sl.product_id <> -1
),
unsold AS (
  SELECT st.product_id, st.cumulative_qty, st.cumulative_value, st.product_code, st.product_description, st.item_group
  FROM stock st
  WHERE NOT EXISTS (SELECT 1 FROM fact_invoice_lines il
                    WHERE il.product_id = st.product_id AND il.invoice_date BETWEEN '2026-09-21' AND '2027-03-20')
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
Expected: (data of 13-Oct-2026) 4,097 finished goods in stock on 20-Mar-2027, 4,097 sold and 0 without sales from 21-Sep-2026 (13 without sales from 21-Dec-2026, biggest FG02641 Trochoid pump TX-676-2C 0.75kW, 6,739,600.00); 872 other items not sold.

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
Expected: (data of 14-Oct-2026, base + batch_001) 21-Dec-2025 to 20-Mar-2027: invoices 21,552,715,254.00; credit notes 28,607,589.22 (232 notes); debit notes 53,289.00 (14 notes); net sales 21,524,160,953.78 = 21,552,715,254.00 - 28,607,589.22 + 53,289.00. One customer: Prime Auto Components LLP invoices 300,477,802.50, credit notes 1,911,325.00 (8 notes), net 298,566,477.50.

## Q: Which dates does Q1 of FY 2026-27 cover?

Also asked as: dates of quarter 1 / Q2 / Q3 / Q4 of this FY; does a quarter use calendar dates or NOP sales months; which quarter definition does the app use; is Q1 April to June or 21-Mar to 20-Jun (for Q2 use fiscal_quarter = 2 and the NOP months Jul, Aug and Sep 2026; Q3 = Oct-Dec; Q4 = Jan-Mar 2027).

```sql
SELECT 'Q1 of FY 2026-27 (the quarter Ask NOP uses)' AS quarter_meaning,
       MIN(c.full_date) AS period_from,
       MAX(c.full_date) AS period_to
FROM dim_calendar c
WHERE c.financial_year = '2627' AND c.fiscal_quarter = 1
UNION ALL
SELECT 'NOP sales months Apr, May and Jun 2026', MIN(c.nop_sales_period_start), MAX(c.nop_sales_period_end)
FROM dim_calendar c
WHERE c.nop_sales_month IN ('Apr 2026', 'May 2026', 'Jun 2026');
```

Why: Ask NOP's quarter is the FY quarter by calendar dates (dim_calendar.fiscal_quarter: Q1 = 1-Apr to 30-Jun), and every answer about a quarter states its dates; the NOP sales months of the same quarter start on the 21st, so they are shown next to it. A question about which dates a period covers is a NOP data question - answer it from dim_calendar, never with NO_SQL.
Expected: Q1 of FY 2026-27 = 01-Apr-2026 to 30-Jun-2026 (used by Ask NOP); NOP sales months Apr-Jun 2026 = 21-Mar-2026 to 20-Jun-2026.

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

Why: the minimum level IS in the NOP data: dim_products.minimum_inventory_qty, the minimum set in SAP, where 0 means no minimum is set for that item - never write a MISSING line for it. Compare it with the stock of the newest stock report ('Closing balance' rows; an item with no closing row has 0 stock). ONE summary row, also when nothing is below: items_with_a_minimum_set tells "no item has a minimum set in SAP" (0) apart from "every item is above its minimum". Always return report_date.
Expected: (data of 22-Oct-2026) stock report 20-Mar-2027: 0 items with a minimum set (minimum_inventory_qty is 0 for all 5,001 items), so no item is below its minimum - the answer says no minimum levels are set in SAP yet.
