# NOP business rules for ai_gold

How NOP counts things, and which ai_gold tables and columns give the right number.
Every rule names the exact tables and columns to use. Amounts are INR unless a rule says otherwise.

## Financial year (FY) - 1 April to 31 March, written '2627'

- NOP's financial year runs from 1-Apr to 31-Mar. FY 2026-27 = 01-Apr-2026 to 31-Mar-2027.
- It is stored as `dim_calendar.financial_year` = '2627' (label `dim_calendar.financial_year_label` = 'FY 2026-27'). FY 2025-26 = '2526', FY 2024-25 = '2425'.
- Filter or group a fact by FY through its date key: `JOIN dim_calendar c ON c.date_id = fact_invoice_lines.invoice_date_id WHERE c.financial_year = '2627'` (orders: `fact_sales_order_lines.order_date_id`).
- Quarters inside the FY: `dim_calendar.fiscal_quarter` (1 = Apr-Jun ... 4 = Jan-Mar); month inside the FY: `dim_calendar.fiscal_period` (1 = April).
- A quarter uses calendar dates, not NOP sales months: Q1 of FY 2026-27 = 01-Apr-2026 to 30-Jun-2026 (not 21-Mar to 20-Jun). Always state the quarter's dates in the answer. "Which dates is Q1 of FY 2026-27?" is a NOP data question: `SELECT MIN(full_date) AS period_from, MAX(full_date) AS period_to FROM dim_calendar WHERE financial_year = '2627' AND fiscal_quarter = 1`.
- "This FY" / "current FY": `SELECT financial_year FROM dim_calendar WHERE full_date = CURDATE()`.
- The dates of a FY filter (`c.financial_year = '2627'`) are 01-Apr to 31-Mar: return them as `MIN(c.full_date)` / `MAX(c.full_date)` (or the data dates MIN / MAX(invoice_date)), never `MIN(c.nop_sales_period_start)` - the NOP sales month of 1-Apr starts on 21-Mar, so that would show 21-Mar-2026 for FY 2026-27.
- A FY total (not split by NOP sales month) uses `dim_calendar.financial_year`. Invoice data for FY 2025-26 starts only on 21-Dec-2025. Return the first and last invoice date of each FY (data_from, data_to), so the answer says which dates each total really covers.

## NOP sales month - which dates a month like 'Oct 2026' covers

- A NOP sales month runs from the 21st of the previous month to the 20th, and is named after the month it ENDS in.
- 'Oct 2026' = 21-Sep-2026 to 20-Oct-2026. 'Sep 2026' = 21-Aug-2026 to 20-Sep-2026. So 06-Oct-2026 and 25-Sep-2026 are both in NOP month 'Oct 2026'; 15-Sep-2026 is in 'Sep 2026'.
- Columns: `dim_calendar.nop_sales_month` ('Oct 2026'), `dim_calendar.nop_sales_period_start` (2026-09-21), `dim_calendar.nop_sales_period_end` (2026-10-20), `dim_calendar.nop_sales_period_no` (1 = April ... 12 = March), `dim_calendar.nop_sales_year` ('2627').
- Which NOP month is a date: `SELECT nop_sales_month, nop_sales_period_start, nop_sales_period_end FROM dim_calendar WHERE full_date = '2026-10-06'`.
- "This month" / "last month" / "previous month" come from TODAY (CURDATE()), not from the data: this month = the NOP month of `dim_calendar WHERE full_date = CURDATE()`; last month = the NOP month that ends the day before this month starts (`p.full_date = t.nop_sales_period_start - INTERVAL 1 DAY`). Never find the latest month by sorting nop_sales_month - it is text ('Sep 2026' sorts after 'Mar 2027'); sort months by nop_sales_period_start. Return the month and its first / last date. Use the SQL of the example "What were last month's sales, and which customer bought the most?".
- A period that is not over yet - this month, this quarter, this FY, this year - counts only up to TODAY: `invoice_date <= CURDATE()`, period_to = `LEAST(<period end>, CURDATE())`, and the answer says "so far" with both dates (e.g. "Nov 2026 so far (21-Oct-2026 to 27-Oct-2026)"). Never add data dated after today. Use the SQL of the example "What are our sales this month so far?".
- For sales, invoices, credit notes and sales orders, a month name like "sales in Aug 2026" means the NOP sales month (`dim_calendar.nop_sales_month = 'Aug 2026'`, 21-Jul-2026 to 20-Aug-2026) unless the user says "calendar month" or gives exact dates. Always state the date range in the answer.
- A range of named months ("month by month from Jan 2026 to Mar 2027", "monthly sales Apr to Sep 2026") = NOP sales months, one row per NOP month ('Jan 2026' starts on 21-Dec-2025); period_start / period_end are c.nop_sales_period_start / c.nop_sales_period_end, never MIN / MAX of the invoice dates. Use the SQL of the example "Show net sales month by month from Jan 2026 to Mar 2027.".
- Words around a month: "since / from Oct 2026" = on or after the month's FIRST day (21-Sep-2026 - October itself counts); "after Oct 2026" = after its LAST day (20-Oct-2026); "before Oct 2026" = before its first day; "until / up to Oct 2026" = up to its last day. Look the days up by name: `MIN(nop_sales_period_start)` / `MAX(nop_sales_period_end)` `WHERE nop_sales_month = 'Oct 2026'`. Use the SQL of the example "Which customers bought from us between Jan 2026 and Jun 2026 but have bought nothing since Oct 2026?".
- dim_fx_rates.rate_month uses the same naming: the rate window 'Oct 2026' = 21-Sep-2026 to 20-Oct-2026.

## Calendar month (1st to last day) - only when the user asks for it

- `dim_calendar.month_year` = 'Aug 2026' means 01-Aug-2026 to 31-Aug-2026 (the normal calendar month).
- Use it only when the user says "calendar month", "1 to 31 Aug", or gives dates; otherwise sales months are NOP sales months (21st to 20th).
- Alternative: filter the plain date column, e.g. `fact_invoice_lines.invoice_date BETWEEN '2026-08-01' AND '2026-08-31'`.
- Calendar year: `dim_calendar.calendar_year`; calendar quarter: `dim_calendar.calendar_quarter` (1 = Jan-Mar).

## NOP sales year vs financial year in month-by-month reports

- `dim_calendar.nop_sales_year` = '2627' covers the NOP sales months Apr 2026 .. Mar 2027 = 21-Mar-2026 to 20-Mar-2027.
- When a FY is split by NOP sales month, filter `c.nop_sales_year = '2627'` and order by `c.nop_sales_period_no`, so every month is complete (NOP month 'Apr 2026' starts on 21-Mar-2026).
- Months of more than one FY (e.g. every month in the data): `GROUP BY` and `ORDER BY c.nop_sales_year, c.nop_sales_period_no` - ordering by `nop_sales_period_no` alone puts Jan 2026 next to Jan 2027.
- When the user asks for a FY total, use `c.financial_year` (1-Apr to 31-Mar).
- The two totals differ by the 21-31 March days: nop_sales_year '2627' includes 21-31 Mar 2026 and leaves out 21-31 Mar 2027; financial_year '2627' does the opposite.

## Sales amounts - which column to SUM (net sales, invoice value, sales value incl. freight)

- Default for "sales", "net sales", "revenue", "turnover", "billing" and "invoice value": `SUM(fact_invoice_lines.net_taxable_value)` - INR, before GST and freight. Credit notes are negative in net_taxable_value, so they subtract automatically. Do not filter document_type for sales totals.
- "Sales value including freight" (the NOP sales report figure): `SUM(fact_invoice_lines.net_taxable_value) + SUM(COALESCE(fact_invoice_lines.freight_amount, 0))` (freight is NULL on credit notes).
- "Including GST" / gross: `SUM(fact_invoice_lines.net_line_total_incl_gst)`.
- Quantity sold: `SUM(fact_invoice_lines.net_quantity)`.
- Gross invoiced before credit notes: `SUM(net_taxable_value)` with `document_type = 'INVOICE'`.
- Never SUM `taxable_value`, `quantity` or `line_total_incl_gst` over credit notes - they are positive as printed. Never SUM `invoice_total_incl_gst` (the whole-invoice total is repeated on every line).
- Orders booked are a different number: `fact_sales_order_lines.total_amount` (see the sales order rules).

## Credit notes and debit notes in fact_invoice_lines

- Credit notes are rows of `fact_invoice_lines` with `document_type = 'CREDIT_NOTE'` (`invoice_series = 'CN'`, `source_format = 'CREDIT_NOTE'`). Debit notes are rows with `document_type = 'DEBIT_NOTE'` (`invoice_series = 'DN'`); their net_* values are positive, so they add to sales.
- On a credit note row `quantity`, `taxable_value`, `line_total_incl_gst` and `note_value` are POSITIVE as printed, while `net_quantity`, `net_taxable_value` and `net_line_total_incl_gst` are NEGATIVE. Use the net_* columns for totals.
- `invoice_date` (and `invoice_date_id`) of a credit note = the NOTE date (`note_date`), so the note reduces sales in the month and FY it is issued, not the month of the original invoice.
- `invoice_number` on a note row is the ORIGINAL invoice (same as `original_invoice_number`); the note's own number is `note_number`, e.g. 'NOPI/CN/2627/1' (`note_series` 'CN/2627').
- Customer, product, sales person, SO number, territory and sale_type of a note are copied from the original invoice.
- Count credit notes with `COUNT(DISTINCT note_number) ... WHERE document_type = 'CREDIT_NOTE'`. Count invoices with `COUNT(DISTINCT invoice_number) ... WHERE document_type = 'INVOICE'`.
- Credit note value as a positive number: `SUM(taxable_value) WHERE document_type = 'CREDIT_NOTE'` (= -SUM(net_taxable_value)).
- Debit note value: `SUM(net_taxable_value) WHERE document_type = 'DEBIT_NOTE'`. Count debit notes with `COUNT(DISTINCT note_number) ... WHERE document_type = 'DEBIT_NOTE'`.
- Net sales = invoices - credit notes + debit notes = `SUM(net_taxable_value)` (credit notes are already negative there, debit notes positive). "Were credit notes deducted?" / "how much of the sales were credit notes?" = ONE summary row (invoices, credit notes, debit notes, net sales), not a list of every customer: use the SQL of the example "How much of our net sales were invoices, credit notes and debit notes?" (for one customer, territory or month add that filter).

## JPY conversion with dim_fx_rates (INR to Japanese yen)

- JPY value = INR value x `dim_fx_rates.exchange_rate` of the rate window holding the date (1 INR = exchange_rate JPY).
- Invoices: `JOIN dim_fx_rates f ON f.fx_rate_id = fact_invoice_lines.fx_rate_id` (window of invoice_date), then `ROUND(SUM(il.net_taxable_value * f.exchange_rate), 2)`. Orders: `fact_sales_order_lines.fx_rate_id` (window of the order date).
- Each window is one NOP sales month (21st to 20th); `dim_fx_rates.rate_month` is named like `dim_calendar.nop_sales_month` ('Oct 2026').
- The first rate window starts on 21-Dec-2024 ('Jan 2025'). Sales orders dated before that, and any date outside every window, have `fx_rate_id = -1`, and the -1 row has `exchange_rate` NULL: say "no exchange rate for that date" instead of dropping those rows silently.
- Which rate months exist: `SELECT rate_month, exchange_rate FROM dim_fx_rates WHERE fx_rate_id <> -1` (new months arrive with each load - never assume a last month).
- The rate of one month: `SELECT exchange_rate FROM dim_fx_rates WHERE rate_month = 'Oct 2026'`.
- List rate months straight from `dim_fx_rates`, ordered by `start_date` (latest first = `ORDER BY start_date DESC`). Never join `dim_calendar` to list rate months - that repeats each month once per day.

## Sales orders - SO number + financial year identifies an order

- `fact_sales_order_lines.so_number` RESTARTS every financial year (SO 50 exists in FY 2024-25, FY 2025-26 and FY 2026-27). Never identify or count orders by so_number alone.
- One order = `so_number` + `dim_calendar.financial_year` of `order_date_id` (or so_number + order_date).
- Count orders: `COUNT(DISTINCT s.so_number, c.financial_year)` with `JOIN dim_calendar c ON c.date_id = s.order_date_id`.
- Find one order: `WHERE s.so_number = 50 AND c.financial_year = '2627'`.
- Invoices of an order: `fact_invoice_lines.so_number = fact_sales_order_lines.so_number AND fact_invoice_lines.so_date = fact_sales_order_lines.order_date`.
- Order value before GST = `SUM(fact_sales_order_lines.total_amount)`; GST = `SUM(tax_total)`; ordered quantity = `SUM(quantity)`.
- Name order value columns with the GST basis (open_value_before_gst_inr, ..._incl_gst_inr) so the answer says "before GST". `delivery_date` is the PROMISED delivery date on the order - there is no actual delivery date in ai_gold.
- Order dates start on 02-Apr-2024; the last order date grows with each load: `SELECT MIN(order_date), MAX(order_date) FROM fact_sales_order_lines`.

## Sales order status - open, closed and cancelled orders

- `fact_sales_order_lines.status`: 'Open' = ordered, not yet (fully) invoiced; 'Closed' = completed; 'Canceled' = cancelled (spelt with one L).
- Open orders / order backlog / pending orders: `WHERE s.status = 'Open'`; value = `SUM(s.total_amount)` before GST (add `tax_total` for incl. GST).
- Order intake / orders booked: leave out cancelled lines with `s.status <> 'Canceled'`.
- The status is the same on every line of one order.
- Overdue open lines: `status = 'Open' AND delivery_date < CURDATE()`.
- Closed orders from before Dec-2025 have no invoice lines in ai_gold (invoice data starts 21-Dec-2025).

## Export, domestic and service sales; invoice series

- Split sales with `fact_invoice_lines.sale_type`: 'Domestic', 'Export' or 'Service'. Credit notes carry the sale_type of their original invoice, so the split stays correct after credit notes.
- `fact_invoice_lines.invoice_series` comes from the invoice number ('NOPI/D/2526/169' -> 'D'): D = domestic, E = export, S = service, DU = duplicate; CN = credit note, DN = debit note.
- Prefer sale_type over invoice_series for export vs domestic (a credit note has series CN but keeps the original sale_type).
- Sales territory: `fact_invoice_lines.territory` ('Export', 'South Region - 1', 'South Region - 2', 'South Region', 'North-East-West Region', 'West Region - Gujarat', 'West Region - Maharashtra').
- Foreign vs local customers: `dim_customers.customer_group` ('Foreign Customer', 'Local Customer', 'Customers'); country: `dim_customers.country`, `dim_customers.country_segment`.

## Unknown (-1) keys - keep them in totals

- An Unknown key (-1) means the code or date was not found in the master. The row is kept and points to the -1 'Unknown' row of the dimension.
- Never drop -1 rows from totals: a normal JOIN keeps them (the -1 row exists in every dimension). Do not add `WHERE customer_id <> -1` unless the user asks to leave Unknown out. Exception: when COUNTING customers (e.g. new customers), the Unknown customer is not one customer - leave it out of the count and show its sales separately (see 'New customers'). In a LIST of customers (e.g. who stopped buying) just leave it out - never add an 'Unknown customer' row. Show them as 'Unknown customer' / 'UNKNOWN' product.
- Check for Unknown keys with `SUM(customer_id = -1)` / `SUM(product_id = -1)` on fact_invoice_lines or fact_sales_order_lines; trace them with the src_* columns (src_customer_code, src_product_code).
- Service lines (no item code) always have product_id -1; sales orders dated before 21-Dec-2024 have fx_rate_id -1 (no exchange rate). Count the Unknown keys in the data with the SUM(... = -1) query above - never assume a fixed number.

## Names in a question - customer, product or sales person written partly or differently

- Users type names partly or differently ('Everest Engineering', 'allied castings', 'Anand'). Never filter with `customer_name = '<the user's words>'`: match with `cu.customer_name LIKE '%<words>%'` (case does not matter in ai_gold).
- Start from dim_customers and LEFT JOIN the fact (put the period filter inside the ON), so every matching customer is listed - with 0 when it has no sales - and return `COUNT(*) OVER () AS customers_matched`.
- When several customers match, the answer names each one with its own amount; never add them up silently as if they were one customer.
- The same for products (`p.product_description LIKE '%...%'` or `p.product_code`) and sales people (`sp.sales_person_name LIKE '%...%'`).
- If nothing matches, say that no customer / product / person with that name was found (not "no sales").

## Customers - names, groups, country segment and sheet-only customers

- Report customers by `dim_customers.customer_name`, grouped by `dim_customers.customer_id` (not `fact_invoice_lines.customer_billing_name` or `fact_sales_order_lines.src_customer_name`).
- Join: `fact_invoice_lines.customer_id = dim_customers.customer_id` or `fact_sales_order_lines.customer_id = dim_customers.customer_id`.
- `dim_customers.source_system`: 'CUSTOMER_MASTER' = SAP customers from the Customer Master Report (customer_code like 'C0001'); 'CLIENT_SHEET' = customers that exist only in the client's Customer list sheet (no customer_code, no orders or invoices yet); 'UNKNOWN' = the -1 row. Count customers with `COUNT(*) ... WHERE customer_id <> -1`.
- `dim_customers.customer_group`: 'Local Customer', 'Foreign Customer' or 'Customers'. Country: `dim_customers.country`, `country_iso_code`, `country_segment` ('1.JAPAN', '2.ASIA', '3.AMERICA', '4.EUROPE', '5.MIDDLE EAST', '8.OTHER'; NULL = not in the client's Country master).
- The customer of an invoice line was found through its sales order (SO number + financial year).

## Sales by state (Karnataka, Telangana ...) - the customer's state, not the GST code

- A state's sales, "which state bought the most", "Karnataka sales" = the customer's bill-to state: JOIN dim_customers and use `dim_customers.state`, which holds full names ('Karnataka', 'Telangana', 'Tamil Nadu'). Foreign customers have no state (NULL).
- Never use `fact_invoice_lines.place_of_supply_state` for a state's sales: it holds only the 2-letter GST place-of-supply code ('KA', 'TS') and is NULL on exports, so a LIKE '%Karnataka%' on it finds nothing. Use it only when the user asks about the GST place of supply.

## Products - product category, SAP segment and item group

- `dim_products.product_category` is the CLIENT (NOP Japan) classification from sheets PTC_NOPI / PCT_NOPJ: 'Trochoid pumps', 'GCI', 'Coolant pumps', 'YTH-PARTS', 'Coolant Units', 'Hydraulic motors', 'Procon Pumps'. NULL = not classified (every raw material, consumable and capital item, plus the finished goods the client has not classified): show it as `COALESCE(p.product_category, 'Not classified')`, never drop it. 'Not classified' is by far the biggest group (most invoice lines), so "which category sold the most" returns the top 5 categories (LIMIT 5, not 1) and the answer names the top real category as well as the Not classified amount.
- `dim_products.sap_segment` is SAP's own product family with the same names, filled for every finished-goods item. Use it when the user says "product family" or "SAP segment".
- `dim_products.item_group` / product_code prefix: FG = 'Finished goods', RM = 'Raw material', CO = 'Consumables', CA = 'Capital Item'.
- Only finished goods are sold: raw materials, consumables and capital items are never on an invoice. "Items with no sales", unsold / slow-moving / dead stock = finished goods only, with a count of the other items in stock (not for sale). Use the SQL of the example "Which items were in stock on 20-Mar-2027 but had no sales between 21-Sep-2026 and 20-Mar-2027?".
- Join: `fact_invoice_lines.product_id = dim_products.product_id` (also fact_sales_order_lines, fact_stock_ledger). Service lines have product_id -1 (they land in 'Not classified').

## Stock value on a date - Closing balance rows only

- `fact_stock_ledger` holds, per item, a 'Closing balance' row, an 'Opening Balance' row, then the movements. Never SUM every row.
- Stock value on a date = `SUM(fact_stock_ledger.cumulative_value)` of the rows with `dim_stock_movement_types.movement_type = 'Closing balance'` and `fact_stock_ledger.report_date` = that date (join `fact_stock_ledger.movement_type_id = dim_stock_movement_types.movement_type_id`). Stock quantity: `SUM(cumulative_qty)` of the same rows.
- Opening stock = the same on 'Opening Balance' rows.
- There is one stock report per Inventory Audit Report file, and new reports arrive with each load. List them with `SELECT DISTINCT report_date FROM fact_stock_ledger ORDER BY report_date`.
- "Current stock", "latest stock", "stock now" or a stock question without a date = the NEWEST report: `sl.report_date = (SELECT MAX(report_date) FROM fact_stock_ledger)`. Always return report_date so the answer can say which report was used.
- Zero / negative stock now: count the 'Closing balance' rows of the newest report with cumulative_qty = 0 (and < 0), and return report_date (example "How many items have zero stock right now?").
- For a date that has no report, say there is no stock report for that date and name the report dates that exist.
- `dim_products.in_stock_qty` is the item master export, not stock on a date.
- Stock balances have no warehouse: `warehouse_code` ('02', '03') is only on movement rows and NULL on 'Closing balance' / 'Opening Balance' rows. "Stock value by warehouse" cannot be answered: give the total stock value and write MISSING: stock value per warehouse - the stock report gives balances per item only.
- Comparing two stock reports (stock change per item): only items in BOTH reports can be compared (the 20-Sep-2026 report has far fewer items than the 20-Mar-2027 one). Return items_in_both_reports and the items found in one report only, and say it in the answer. Use the SQL of the example "Which items had the biggest increase in stock value between 20-Sep-2026 and 20-Mar-2027?".
- Check for the 20-Sep-2026 report: opening 3,070,707.07 + purchases 21,967,328.75 - production 1,181,063.91 = closing 23,856,971.91.

## Stock movements, the movement map and COGS

- Movement map (letters before the number in `fact_stock_ledger.document_no`): PD / PU / PC = Purchase; IF = Landed cost; IN / CN / DN / RE = COGS; IM = Inventory transfer; SO / SI / MR = Production. Stored in `dim_stock_movement_types` (movement_type, doc_prefixes, row_kind).
- Movements are rows with `dim_stock_movement_types.row_kind = 'MOVEMENT'`; `quantity` + = into stock, - = out; `transaction_value` in INR.
- COGS value = `SUM(-transaction_value)` of rows with movement_type = 'COGS'. COGS rate per item = `ROUND(SUM(-transaction_value) / SUM(-quantity), 2)` of the COGS rows, grouped by product.
- Always filter COGS by report_date (the newest report when no date is given) - each report has its own movements.
- The 20-Sep-2026 report has NO COGS rows: its stock going out is written as 'SI <number>' documents, which NOP's real map counts as Production (10 rows, -33 qty, -1,181,063.91 INR), so COGS for that report = 0.00. Never relabel SI rows as COGS. Other reports can have COGS rows - compute them, never assume 0.

## OEM and after-market (AFT) sales

- OEM / AFT is `fact_invoice_lines.customer_type`: 'OEM' or 'AFT' (after-market). It is NULL on most lines - show it as `COALESCE(customer_type, 'Not given')`, never drop those lines. Keep the 'Not given' row also when the user names only OEM and AFT - it is more than half of the sales.
- It is not a column of `dim_customers`.

## Sales people - who sold what

- Sales by person: `fact_invoice_lines.sales_person_id = dim_sales_people.sales_person_id`, report `dim_sales_people.sales_person_name`, amount `SUM(fact_invoice_lines.net_taxable_value)`. Credit notes carry the sales person of the original invoice.
- Orders booked by person: `fact_sales_order_lines.sales_person_id`.
- List the sales people with `SELECT sales_person_name FROM dim_sales_people WHERE sales_person_id <> -1` (the -1 row is 'Unknown'); new people arrive with each load.

## GST on invoices and sales orders

- Invoice GST: `fact_invoice_lines.igst_amount` (inter-state; 0 on exports), `cgst_amount` + `sgst_amount` (intra-state halves), `cess_amount` (note rows only). Rates in igst_rate / cgst_rate / sgst_rate (percent).
- These GST amounts are positive as printed, also on credit notes: subtract rows with `document_type = 'CREDIT_NOTE'` for a net figure.
- A month name in a GST question means the NOP sales month (`c.nop_sales_month`, 21st of the previous month to the 20th), the same as for sales; use the calendar month only when the user says "calendar month" or gives exact dates.
- Sales order GST: `fact_sales_order_lines.tax_total`; the code via `fact_sales_order_lines.tax_code_id = dim_tax_codes.tax_code_id` (e.g. 'IGST18', 'CSGST18', 'IGST0', 'IGST12', 'CSGST12').

## Growth and comparisons - this year vs last year (a fair comparison)

- "This year" / "last year" = the current financial year (`dim_calendar.financial_year` of CURDATE()) and the one before it, unless the user names the years, months or dates.
- The two years usually have data for different lengths of time (invoice data starts on 21-Dec-2025, and the newest data stops before the year ends). Comparing two whole FYs would then compare about 3 months with about 12 and give meaningless growth. Compare the SAME dates in both years instead: the dates where both years have data, shifted by one year - use the SQL of the example "How did each customer's sales grow or drop this year compared with last year?".
- Return the four dates used (last_year_from, last_year_to, this_year_from, this_year_to) so the answer can say exactly which dates were compared.
- Growth % = (this year - last year) / last year x 100, only when last year > 0. Return BOTH amounts next to every growth %, so a growth from a tiny base (e.g. INR 2,500) is visible.
- Customers with no sales last year are 'New' (no growth %); customers with no sales this year are 'Lost' (-100 %). Never leave them out silently: return how many are new, lost and in both years.
- The highest growth, the biggest decline, the biggest lost and the biggest new customer are labelled IN SQL in a `highlight` column (ROW_NUMBER() per customer_status) and those rows come first - use the example's SQL. The answer names them from the labels.
- When the user names the periods (e.g. "Jan-Mar 2027 vs Jan-Mar 2026", "Aug 2026 vs Aug 2025"), compare exactly those periods (month names = NOP sales months) and still return the new / lost counts.
- If the query returns no rows, the two years have no dates with data in common: say so and suggest naming the months to compare.
- The same rules apply to growth by product, sales person, country or category.

## New customers and customers who stopped buying

- A new customer in a period = a customer whose FIRST invoice line in ai_gold (MIN(fact_invoice_lines.invoice_date) over all their lines) falls inside that period. Their sales = their net sales (SUM(net_taxable_value)) in that period. Use the SQL of the example "How many new customers did we get in FY 2026-27, and how much did they buy?".
- Invoice data starts on 21-Dec-2025, so "new" means "no invoice in the data before the period": a customer who last bought before the data starts also looks new. Always SELECT the first invoice date of all the data as invoice_history_starts; the answer says e.g. "4,158 customers bought for the first time in FY 2026-27 (checked against all invoices since 21-Dec-2025, where our data starts)" - never that the period's data starts on that date.
- The Unknown customer (-1) is not one customer: leave it out of the new-customer count and their sales, and return its sales in the period separately (unknown_customer_sales_inr) so nothing is hidden. Also return how many customers bought in the period (customers_buying) and all sales (all_sales_inr), so the new customers can be seen as a share.
- This is not the same as 'New (no sales last year)' in a growth comparison, which compares the same dates of two years.
- Customers who stopped buying (lapsed, inactive): no invoice in the last 3 months of the data - their last invoice is before the newest invoice date (MAX(invoice_date)) minus 3 months - unless the user gives another period. List them biggest first with their last invoice date and their sales, plus the cut-off date (no_invoice_on_or_after) and how many days before the newest invoice it is; the answer says e.g. "786 customers bought before but have no invoice on or after 20-Dec-2026 (90 days before the newest invoice, 20-Mar-2027)". Use the SQL of the example "Which customers stopped buying from us?". (In a growth comparison 'Lost' means no sales on the same dates this year - a different question.)
- "Last year and this year revenue": give each FY's total with the dates the data covers AND the same-dates growth - use the SQL of the example "What were total net sales this year and last year, and how much did they grow?".

## What is NOT in the NOP data - profit, payments, purchases, people

- Users are business people and often ask for things ai_gold does not hold. Answer every part that CAN be answered; for the rest, say plainly what is missing and why - never refuse the whole question.
- **Profit, margin, gross profit %, cost of sales per invoice**: NOT available - invoices and orders carry selling prices only, not what the sold items cost. (The stock ledger has movement costs and COGS per stock report, but they are not linked to invoices.) Offer: net sales, sales growth, average selling price, COGS value in a stock report. When the user asks for a profit % or profit growth BETWEEN two periods (e.g. this year vs last year), answer with the revenue of both periods and the revenue growth % (column revenue_growth_pct, calculated in SQL; this year vs last year on the same dates - see the example "What were total net sales this year and last year, and how much did they grow?") and add the MISSING line for true profit. The answer calls it revenue growth, never profit.
- **Payments received, outstanding / receivables, ageing, overdue payments**: NOT available - there is no payment data. Offer: invoiced value, open sales orders (orders not yet invoiced).
- **Purchase orders, suppliers, purchase prices**: NOT available as orders - only stock purchase movements (document prefixes PD / PU / PC) with their values in the stock ledger.
- **Employees, salaries, targets, budgets, forecasts, competitors, market share**: NOT available. Sales people exist only as names on orders and invoices (dim_sales_people).
- Mixed question example: "last year vs this year revenue and the profit percentage" -> answer the revenue comparison (same dates in both years) and add: "Profit % cannot be calculated: the NOP data has selling prices but not the cost of the items sold."

## Data coverage - which dates have data

- ai_gold grows with every load (a full load, then incremental batches), so never assume a fixed last date - check the data itself:
  - invoices and notes: `SELECT document_type, MIN(invoice_date), MAX(invoice_date) FROM fact_invoice_lines GROUP BY document_type`
  - sales orders: `SELECT MIN(order_date), MAX(order_date) FROM fact_sales_order_lines`
  - stock reports: `SELECT DISTINCT report_date FROM fact_stock_ledger`
  - exchange rates: `SELECT rate_month FROM dim_fx_rates WHERE fx_rate_id <> -1`
  - load history: `load_log` (one row per table per run: run_type 'FULL' / 'INCREMENTAL', batch_name, loaded_at)
- Fixed starts: invoice data starts on 21-Dec-2025; sales orders on 02-Apr-2024; dim_calendar covers 01-Apr-2024 to 31-Mar-2027 (a date outside it has date_id -1).
- When a query for a period returns no rows, say there is no data for that period in ai_gold instead of reporting 0 sales.

## Writing the SQL for ai_gold (MySQL 8)

- Write ONE read-only SELECT (WITH ... SELECT is fine) on ai_gold tables only.
- Table names: dimensions start with dim_ (dim_calendar, dim_customers, dim_products, dim_fx_rates, dim_sales_people, dim_tax_codes, dim_stock_movement_types), facts with fact_ (fact_invoice_lines, fact_sales_order_lines, fact_stock_ledger); load_log has no prefix. Column names have no prefix.
- Join dimensions on the foreign-key columns; join `dim_calendar` on the *_date_id column for months, NOP sales months and financial years.
- Text values are exact: status 'Open' / 'Closed' / 'Canceled'; document_type 'INVOICE' / 'CREDIT_NOTE' / 'DEBIT_NOTE'; movement_type 'Closing balance' (small b) / 'Opening Balance'; sale_type 'Domestic' / 'Export' / 'Service'; financial_year '2627'; nop_sales_month 'Oct 2026'.
- Dates as 'YYYY-MM-DD'; date keys as yyyymmdd numbers (20260920). Today = CURDATE().
- Money: `ROUND(SUM(...), 2)`. Top N: `ORDER BY ... DESC LIMIT N`.
- When an answer must name both the top and the bottom of a long list (highest and lowest, best and worst), label those rows in SQL in a `highlight` column (ROW_NUMBER() OVER (ORDER BY ...) = 1 from each end) and order the labelled rows first, so the answer never has to search the list.
- Do not use reserved words as aliases (lines, rows, order, group, year, range...): write order_lines, net_sales_inr.
