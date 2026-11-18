# ss_gold data dictionary

Plain-English meaning of every table and column in the MySQL database `ss_gold` (read-only for the AI).
Column meanings are the MySQL column COMMENTs (the source of truth). Amounts are INR unless a column says otherwise.

## ss_gold overview - star schema (fact and dimension tables)

`ss_gold` is a star schema built from the SS Manufacturing files by loader/load_gold.py.
- Fact tables (the numbers): `fact_invoice_lines` (invoice and credit note lines - sales), `fact_sales_order_lines` (sales order lines - orders booked), `fact_stock_ledger` (stock balances and movements, one snapshot per Inventory Audit Report date).
- Dimension tables (the descriptions): `dim_calendar` (one row per day, financial year and sales month), `dim_customers`, `dim_products`, `dim_fx_rates` (INR to JPY rate windows), `dim_sales_people`, `dim_tax_codes` (GST codes on sales orders), `dim_stock_movement_types` (kinds of stock ledger row).
- `load_log`: load history, one row per table per load run (a full load; incremental batches are possible): rows read / inserted / updated / skipped, Unknown keys, cleaning fixes.
- ML results (estimates made by models on the data, rebuilt by `run_ml` after each load; no foreign keys): `ml_sales_forecast` (sales forecast of the next sales months), `ml_customer_risk` (customers who might stop buying), `ml_customer_segments` (customer groups by buying behaviour), `ml_invoice_alerts` (unusual invoices), `ml_product_pairs` (products bought together), `ml_stock_runout` (items running out of stock), `ml_run_log` (the ML runs).
- Every fact key column is NOT NULL and has a real FOREIGN KEY to its dimension, so a plain JOIN never loses rows (Unknown keys point to the -1 row).
- Questions about sales / revenue / invoice value use `fact_invoice_lines`; about orders, order intake or open orders use `fact_sales_order_lines`; about stock or inventory value use `fact_stock_ledger`.
- The data changes with every load, so never assume a last date: check it with MIN / MAX on the date columns (business rule 'Data coverage'). Loaded on 17-Nov-2026: sales orders 01-Apr-2024 to 31-Oct-2026; invoices 02-Apr-2024 to 31-Oct-2026; calendar 01-Apr-2024 to 31-Mar-2027.

## How the ss_gold tables join (all foreign keys)

Every relationship is a real FOREIGN KEY (17 in total). Join on exactly these columns:
- fact_invoice_lines.customer_id = dim_customers.customer_id
- fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id
- fact_invoice_lines.invoice_date_id = dim_calendar.date_id
- fact_invoice_lines.note_date_id = dim_calendar.date_id
- fact_invoice_lines.product_id = dim_products.product_id
- fact_invoice_lines.sales_person_id = dim_sales_people.sales_person_id
- fact_sales_order_lines.customer_id = dim_customers.customer_id
- fact_sales_order_lines.delivery_date_id = dim_calendar.date_id
- fact_sales_order_lines.fx_rate_id = dim_fx_rates.fx_rate_id
- fact_sales_order_lines.order_date_id = dim_calendar.date_id
- fact_sales_order_lines.product_id = dim_products.product_id
- fact_sales_order_lines.sales_person_id = dim_sales_people.sales_person_id
- fact_sales_order_lines.tax_code_id = dim_tax_codes.tax_code_id
- fact_stock_ledger.movement_type_id = dim_stock_movement_types.movement_type_id
- fact_stock_ledger.posting_date_id = dim_calendar.date_id
- fact_stock_ledger.product_id = dim_products.product_id
- fact_stock_ledger.report_date_id = dim_calendar.date_id

## Unknown (-1) rows in every dimension

- Every dimension table, including `dim_calendar`, has an Unknown row with id -1: dim_calendar.date_id = -1, dim_customers.customer_id = -1 ('Unknown customer'), dim_products.product_id = -1 ('UNKNOWN'), dim_fx_rates.fx_rate_id = -1 (exchange_rate NULL), dim_sales_people.sales_person_id = -1, dim_tax_codes.tax_code_id = -1, dim_stock_movement_types.movement_type_id = -1.
- A fact row whose code or date was not found gets -1 and is NEVER dropped, so totals stay complete. Keep -1 rows in totals and show them as 'Unknown'.
- -1 is also used where a date does not apply: fact_invoice_lines.note_date_id = -1 on invoice rows (not a note); fact_stock_ledger.posting_date_id = -1 on balance rows.
- Facts keep the source codes in src_* columns (e.g. fact_sales_order_lines.src_customer_code) so a -1 row can be traced.
- Service lines (no item code) always have product_id -1; sales orders dated before 21-Dec-2024 have fx_rate_id -1 (no exchange rate). How many -1 keys there are changes with each load: count them with SUM(customer_id = -1) etc.

## Date columns that join to dim_calendar.date_id

All *_date_id columns hold yyyymmdd as a number (20260920 = 20-Sep-2026) and join to `dim_calendar.date_id`:
- fact_invoice_lines.invoice_date_id = dim_calendar.date_id (invoice date; for credit notes the note date)
- fact_invoice_lines.note_date_id = dim_calendar.date_id (credit / debit note date; -1 on invoice rows)
- fact_sales_order_lines.order_date_id = dim_calendar.date_id (order posting date)
- fact_sales_order_lines.delivery_date_id = dim_calendar.date_id (promised delivery date)
- fact_stock_ledger.report_date_id = dim_calendar.date_id (stock report snapshot date)
- fact_stock_ledger.posting_date_id = dim_calendar.date_id (movement posting date; -1 on balance rows)
Each fact also keeps the plain DATE column (invoice_date, order_date, delivery_date, report_date, posting_date) for simple date filters like `invoice_date BETWEEN '2026-08-01' AND '2026-08-31'`.
Join the calendar to filter or group by calendar month (month_year), financial year (financial_year) or sales month (sales_month).

## dim_calendar - date key, calendar month and financial year columns

Table `dim_calendar` (dimension, incl. the -1 Unknown row). Primary key: `date_id`.
What one row is: One row per day from 01-Apr-2024 to 31-Mar-2027, plus the Unknown row -1. Gives every date its calendar month, Indian financial year (Apr-Mar) and sales month (21st to 20th). Every *_date_id in the facts points here.
Every *_date_id column of the fact tables joins here: join <fact>.<x>_date_id = dim_calendar.date_id, then filter or group on the calendar columns (month_year, financial_year, sales_month ...).
Calendar month ('Sep 2026' = 1st to last day) is month_year; the sales month is a different column (see 'dim_calendar - sales month columns').
Joined from: fact_invoice_lines.invoice_date_id = dim_calendar.date_id; fact_invoice_lines.note_date_id = dim_calendar.date_id; fact_sales_order_lines.delivery_date_id = dim_calendar.date_id; fact_sales_order_lines.order_date_id = dim_calendar.date_id; fact_stock_ledger.posting_date_id = dim_calendar.date_id; fact_stock_ledger.report_date_id = dim_calendar.date_id.

Columns:
- `date_id` INT (primary key): Date key = yyyymmdd as a number (20260920 = 20-Sep-2026). -1 = unknown or not applicable date.
- `full_date` DATE: The calendar date. NULL only on the -1 row.
- `day_of_month` TINYINT: Day of the month, 1-31.
- `day_name` VARCHAR(10): Day name, e.g. Monday.
- `day_of_week` TINYINT: Day of the week, 1 = Monday ... 7 = Sunday.
- `week_of_year` TINYINT: ISO week number, 1-53.
- `month_no` TINYINT: Calendar month number, 1 = January ... 12 = December.
- `month_name` VARCHAR(10): Calendar month name, e.g. September.
- `month_short` VARCHAR(3): Short calendar month name, e.g. Sep.
- `month_year` VARCHAR(8): Calendar month label, e.g. 'Sep 2026' (1st to last day of the month).
- `calendar_quarter` TINYINT: Calendar quarter 1-4 (1 = Jan-Mar).
- `calendar_year` SMALLINT: Calendar year, e.g. 2026.
- `financial_year` VARCHAR(4): Indian financial year (1-Apr to 31-Mar) as SS Manufacturing writes it: '2627' = FY 2026-27 = 01-Apr-2026 to 31-Mar-2027.
- `financial_year_label` VARCHAR(10): Financial year label, e.g. 'FY 2026-27'.
- `fiscal_period` TINYINT: Month number inside the financial year: 1 = April ... 12 = March.
- `fiscal_quarter` TINYINT: Quarter inside the financial year: 1 = Apr-Jun, 2 = Jul-Sep, 3 = Oct-Dec, 4 = Jan-Mar.
- `is_month_end` CHAR(1): 'Y' on the last day of a calendar month, else 'N'.
- `is_weekend` CHAR(1): 'Y' on Saturday and Sunday, else 'N'.

## dim_calendar - sales month columns (21st to 20th)

Table `dim_calendar` (dimension): one row per day (01-Apr-2024 to 31-Mar-2027) plus the Unknown row -1. Primary key: `date_id`.
sales month = 21st of the previous month to the 20th, named after the month it ENDS in: 'Oct 2026' = 21-Sep-2026 to 20-Oct-2026. Filter with dim_calendar.sales_month = 'Oct 2026' after join <fact>.<x>_date_id = dim_calendar.date_id.

Columns:
- `sales_month` VARCHAR(8): sales month of this date, e.g. 'Oct 2026'. A sales month runs from the 21st of the previous month to the 20th and is named after the month it ENDS in (21-Sep-2026 .. 20-Oct-2026 = 'Oct 2026').
- `sales_month_name` VARCHAR(10): Month name of the sales month, e.g. 'October'.
- `sales_month_no` TINYINT: Calendar month number of the sales month (10 for 'Oct 2026').
- `sales_year` VARCHAR(4): Financial year of the sales month, same style as financial_year: '2627' = sales months Apr 2026 .. Mar 2027 (21-Mar-2026 .. 20-Mar-2027).
- `sales_period_no` TINYINT: Position of the sales month in its sales year: 1 = April ... 12 = March.
- `sales_period_start` DATE: First day of the sales month (the 21st of the previous month).
- `sales_period_end` DATE: Last day of the sales month (the 20th).

## dim_customers - keys, names, customer group and country

Table `dim_customers` (dimension, incl. the -1 Unknown row). Primary key: `customer_id`.
What one row is: Customers (dimension). One row per SAP customer from the Customer Master Report, plus customers that exist only in the client's Customer list sheet (no BP code yet), plus the Unknown row -1.
Use dim_customers.customer_name in reports (not the src_/billing names on the facts).
Joined from: fact_invoice_lines.customer_id = dim_customers.customer_id; fact_sales_order_lines.customer_id = dim_customers.customer_id.

Columns:
- `customer_id` INT (primary key): Customer key. -1 = Unknown customer (code or name not found in the master).
- `customer_code` VARCHAR(20): SAP business-partner code (BP code), e.g. 'C0001'. NULL for sheet-only customers (source_system 'CLIENT_SHEET'). 'UNKNOWN' on the -1 row.
- `customer_name` VARCHAR(255): Customer company name.
- `client_customer_code` VARCHAR(20): The client's own customer code from the 'Customer list' sheet (e.g. '50001'), matched on BP code. NULL when the sheet gives none.
- `customer_group` VARCHAR(50): SAP customer group: 'Local Customer', 'Foreign Customer' or 'Customers'.
- `type_of_business` VARCHAR(50): SAP type of business, e.g. 'Company'.
- `city` VARCHAR(100): Bill-to city.
- `zip_code` VARCHAR(20): Bill-to ZIP / PIN code.
- `state` VARCHAR(100): Bill-to state (Indian customers; NULL for foreign customers).
- `country` VARCHAR(100): Bill-to country in plain English, spelling corrected (e.g. 'United Arab Emirates').
- `country_iso_code` VARCHAR(3): ISO 3166 3-letter country code from the client's Country master, e.g. IND, JPN. NULL if the country is not in that master.
- `country_segment` VARCHAR(30): Client's country segment for sales reporting, e.g. '1.JAPAN', '2.ASIA', '3.AMERICA', '4.EUROPE', '5.MIDDLE EAST'.
- `accounts_receivable` VARCHAR(100): Receivables (debtors) ledger: 'Sundry Debtors - India' or 'Sundry Debtors - Foreign'.

## dim_customers - address, tax ids, contacts and source columns

Table `dim_customers` (dimension): one row per customer plus the Unknown row -1. Primary key: `customer_id`.
3 customers come only from the client's Customer list sheet (source_system 'CLIENT_SHEET', no customer_code); they have no orders or invoices yet.

Columns:
- `billing_address` VARCHAR(500): Bill-to street address (master column 'BUILDING/FLOOR/ROOM').
- `gstin` VARCHAR(20): Customer's GST registration number (Indian customers).
- `gst_type` VARCHAR(50): GST registration type, e.g. 'Regular/TDS/ISD'.
- `pan_no` VARCHAR(20): Customer's PAN (Indian income-tax id).
- `mobile_phone` VARCHAR(30): Contact mobile number.
- `email` VARCHAR(150): Contact e-mail address.
- `is_active` CHAR(1): 'Y' = active in SAP, 'N' = inactive. NULL for sheet-only customers.
- `source_system` VARCHAR(20): Where the row comes from: 'CUSTOMER_MASTER' (SAP Customer Master Report) or 'CLIENT_SHEET' (only in the client's Customer list sheet, no BP code yet). 'UNKNOWN' on the -1 row.
- `is_current` CHAR(1): 'Y' = current version (always 'Y'; no history is kept).

## dim_products - keys, codes and product classification

Table `dim_products` (dimension, incl. the -1 Unknown row). Primary key: `product_id`.
What one row is: Products / items (dimension). One row per SAP item from the Item Master, with the client's product classification (PTC_SSMI / PCT_SSMJ sheets) joined on the foreign code, plus the Unknown row -1.
product_category / product_segment_* / middle_class_* are the CLIENT (SS Manufacturing Japan) classification; sap_segment is SAP's own product family. NULL product_category = not classified (show it as 'Not classified', never drop it).
Joined from: fact_invoice_lines.product_id = dim_products.product_id; fact_sales_order_lines.product_id = dim_products.product_id; fact_stock_ledger.product_id = dim_products.product_id.

Columns:
- `product_id` INT (primary key): Product key. -1 = Unknown product (item code not found, or a line without item code such as a service charge).
- `product_code` VARCHAR(30): SAP item number, e.g. 'FG00001'. Prefix: FG = finished goods, RM = raw material, CO = consumables, CA = capital item. 'UNKNOWN' on the -1 row.
- `product_description` VARCHAR(255): Item description from the SAP item master.
- `item_group` VARCHAR(50): SAP item group: 'Finished goods', 'Raw material', 'Consumables' or 'Capital Item'.
- `foreign_code` VARCHAR(50): Client's (SS Manufacturing Japan) product code for the item. 'India - No Foreign Code' when SAP has none.
- `product_category` VARCHAR(50): Client classification - category, e.g. 'Trochoid pumps'. From the PTC_SSMI / PCT_SSMJ row whose product code = foreign_code. NULL = not classified.
- `product_segment_code` VARCHAR(20): Client classification - product segment code, e.g. 'L-01'.
- `product_segment_name` VARCHAR(100): Client classification - product segment name, e.g. 'L-01 Trochoid'.
- `middle_class_code` VARCHAR(20): Client classification - middle segment code, e.g. '194'.
- `middle_class_name` VARCHAR(100): Client classification - middle segment name, e.g. 'Trochoid group'.
- `sales_agency` VARCHAR(10): Which client sheet classified the item: 'SSM-I' (sheet PTC_SSMI) or 'SSMJ' (sheet PCT_SSMJ). NULL = not classified.
- `sap_segment` VARCHAR(50): SAP item master 'Segment' (product family), e.g. 'Trochoid pumps'.
- `sap_product_segment` VARCHAR(20): SAP item master 'Product Segment' code, e.g. 'L-06' (can differ from the client's product_segment_code).
- `hsn_code` VARCHAR(20): HSN code (Indian GST goods classification).

## dim_products - SAP master price, stock quantities and status

Table `dim_products` (dimension): one row per SAP item plus the Unknown row -1. Primary key: `product_id`.
These are values from the SAP item master export, not movements. For stock on a date use fact_stock_ledger (Closing balance rows).

Columns:
- `amount` DECIMAL(15,2): 'Amount' from the SAP item master: the item's price per unit in INR as kept in SAP.
- `in_stock_qty` DECIMAL(15,3): 'In Stock' quantity when the item master was exported (for stock on a date use fact_stock_ledger).
- `ordered_from_supplier_qty` DECIMAL(15,3): 'Order to Supplier' - quantity on open purchase orders.
- `ordered_by_customers_qty` DECIMAL(15,3): 'Order by Customer' - quantity on open customer orders.
- `minimum_inventory_qty` DECIMAL(15,3): Minimum inventory level set in SAP (0 = none).
- `lead_time_days` SMALLINT: Lead time in days. NULL when not set.
- `pricing_unit` VARCHAR(20): SAP pricing unit, e.g. 'Manual'.
- `is_active` CHAR(1): 'Y' = active item, 'N' = inactive.
- `last_updated_on` DATE: Date the item record was last updated in SAP (master column 'Date of Udate').

## dim_fx_rates - INR to JPY exchange rate windows

Table `dim_fx_rates` (dimension, incl. the -1 Unknown row). Primary key: `fx_rate_id`.
What one row is: INR -> JPY exchange rates (dimension). One row per monthly rate window (21st of the previous month to the 20th = one sales month), plus the Unknown row -1. JPY value = INR value x exchange_rate.
JPY value = INR value x dim_fx_rates.exchange_rate of the window holding the date: join fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id (or fact_sales_order_lines.fx_rate_id). The first window starts on 21-Dec-2024 ('Jan 2025') and new months arrive with each load; the -1 row has exchange_rate NULL (no rate for that date).
Joined from: fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id; fact_sales_order_lines.fx_rate_id = dim_fx_rates.fx_rate_id.

Columns:
- `fx_rate_id` INT (primary key): Exchange-rate window key. -1 = Unknown (date outside every window).
- `rate_month` VARCHAR(8): Month the rate is for, written like dim_calendar.sales_month, e.g. 'Oct 2026'.
- `start_date` DATE: First day the rate applies (the 21st of the previous month).
- `end_date` DATE: Last day the rate applies (the 20th).
- `from_currency` VARCHAR(3): Currency converted from: 'INR'.
- `to_currency` VARCHAR(3): Currency converted to: 'JPY'.
- `exchange_rate` DECIMAL(12,6): Japanese yen for 1 Indian rupee in this window.
- `remarks` VARCHAR(255): Remark from the rate file, e.g. 'Old Exchange Rate'.

## dim_sales_people - sales persons

Table `dim_sales_people` (dimension, incl. the -1 Unknown row). Primary key: `sales_person_id`.
What one row is: Sales people (dimension). Distinct 'Sales Employee' names from the sales order and invoice files, plus the Unknown row -1.
Report the person with dim_sales_people.sales_person_name. The -1 row is 'Unknown'.
Joined from: fact_invoice_lines.sales_person_id = dim_sales_people.sales_person_id; fact_sales_order_lines.sales_person_id = dim_sales_people.sales_person_id.

Columns:
- `sales_person_id` INT (primary key): Sales person key. -1 = Unknown / not given.
- `sales_person_name` VARCHAR(100): Name without title, e.g. 'Rahul Verma'.
- `name_with_title` VARCHAR(110): Name as written in the files, e.g. 'Mr. Rahul Verma'.
- `designation` VARCHAR(30): Job title: 'Sales Person'.
- `is_current` CHAR(1): 'Y' = current (always 'Y').

## dim_tax_codes - GST tax codes on sales orders

Table `dim_tax_codes` (dimension, incl. the -1 Unknown row). Primary key: `tax_code_id`.
What one row is: GST tax codes used on sales orders (dimension), plus the Unknown row -1. Invoices carry their GST rates and amounts as columns instead.
Only fact_sales_order_lines uses this table. Invoice lines carry their GST as columns (igst_amount, cgst_amount, sgst_amount).
Joined from: fact_sales_order_lines.tax_code_id = dim_tax_codes.tax_code_id.

Columns:
- `tax_code_id` INT (primary key): Tax code key. -1 = Unknown.
- `tax_code` VARCHAR(20): Tax code from the sales order 'TAX Information', spaces removed, upper case, e.g. 'IGST18', 'CSGST18', 'IGST0'.
- `tax_type` VARCHAR(20): 'IGST' = inter-state GST; 'CSGST' = intra-state GST split half CGST + half SGST.
- `tax_rate` DECIMAL(5,2): Total GST rate in percent, e.g. 18.00.
- `tax_description` VARCHAR(100): Meaning in plain English.

## dim_stock_movement_types - kinds of stock ledger row

Table `dim_stock_movement_types` (dimension, incl. the -1 Unknown row). Primary key: `movement_type_id`.
What one row is: Kinds of row in the stock ledger (fixed list, dimension). BALANCE rows are stock balances (Opening / Closing); MOVEMENT rows are stock movements whose type comes from the letters before the document number.
Rows: -1 Unknown; 1 Opening Balance (BALANCE); 2 Closing balance (BALANCE); 3 Purchase (PD, PU, PC); 4 Landed cost (IF); 5 COGS (IN, CN, DN, RE); 6 Inventory transfer (IM); 7 Production (SO, SI, MR). Filter fact_stock_ledger rows by joining fact_stock_ledger.movement_type_id = dim_stock_movement_types.movement_type_id and using movement_type or row_kind.
Joined from: fact_stock_ledger.movement_type_id = dim_stock_movement_types.movement_type_id.

Columns:
- `movement_type_id` INT (primary key): Movement type key. -1 = Unknown document prefix.
- `movement_type` VARCHAR(30): 'Opening Balance', 'Closing balance', 'Purchase', 'Landed cost', 'COGS', 'Inventory transfer' or 'Production'.
- `row_kind` VARCHAR(10): 'BALANCE' = a stock balance row (never add it to movements); 'MOVEMENT' = a stock movement.
- `doc_prefixes` VARCHAR(50): Document prefixes (letters before the number in fact_stock_ledger.document_no) that mean this type, e.g. 'PD, PU, PC'.
- `direction` VARCHAR(10): Usual stock direction: 'IN', 'OUT', 'IN / OUT', or '-' for balances.

## fact_sales_order_lines - what one row is, keys and joins

Table `fact_sales_order_lines` (fact). Primary key: `sales_order_line_id`.
What one row is: Sales order lines (fact). One row per line of the Sales Order Report, nothing dropped. Amounts in INR. SO numbers restart every financial year.
Identify one sales order by so_number + dim_calendar.financial_year of order_date_id (SO numbers restart every financial year). Count orders with COUNT(DISTINCT s.so_number, c.financial_year).
Joins: join fact_sales_order_lines.customer_id = dim_customers.customer_id; join fact_sales_order_lines.delivery_date_id = dim_calendar.date_id; join fact_sales_order_lines.fx_rate_id = dim_fx_rates.fx_rate_id; join fact_sales_order_lines.order_date_id = dim_calendar.date_id; join fact_sales_order_lines.product_id = dim_products.product_id; join fact_sales_order_lines.sales_person_id = dim_sales_people.sales_person_id; join fact_sales_order_lines.tax_code_id = dim_tax_codes.tax_code_id.

Columns:
- `sales_order_line_id` INT (primary key): Sales order line key, in file order.
- `source_row_no` INT: Row number ('#') in Sales Order Report.xlsx, for tracing.
- `order_date_id` INT: Order (posting) date -> dim_calendar.date_id. -1 = date missing or outside the calendar.
- `order_date` DATE: Order posting date (file column 'Posting Date').
- `delivery_date_id` INT: Promised delivery date -> dim_calendar.date_id. -1 = missing / outside the calendar.
- `delivery_date` DATE: Promised delivery date.
- `customer_id` INT: -> dim_customers.customer_id (matched on the customer code). -1 = Unknown.
- `product_id` INT: -> dim_products.product_id (matched on the item number). -1 = no item number (service line) or item not in the master.
- `sales_person_id` INT: -> dim_sales_people.sales_person_id. -1 = Unknown.
- `tax_code_id` INT: -> dim_tax_codes.tax_code_id. -1 = Unknown.
- `fx_rate_id` INT: -> dim_fx_rates.fx_rate_id: the INR->JPY window holding the order date. -1 = order date before the first rate window (21-Dec-2024).

## fact_sales_order_lines - order number, status, quantity and amount columns

Table `fact_sales_order_lines` (fact): one row per sales order line (amounts in INR). Primary key: `sales_order_line_id`.
Order value before GST = SUM(total_amount); GST = SUM(tax_total). Status is the same on every line of an order.

Columns:
- `so_number` INT: Sales order number. Numbers RESTART every financial year: identify an order by so_number + financial year of the order date, never by so_number alone.
- `customer_ref_no` VARCHAR(50): Customer's purchase-order reference, e.g. 'PO/4256/24-25'.
- `status` VARCHAR(20): 'Open' = ordered, not yet (fully) invoiced; 'Closed' = completed; 'Canceled' = cancelled.
- `item_description` VARCHAR(255): Item description on the line (NULL on service lines).
- `hsn_code` VARCHAR(20): HSN code on the line (NULL on service lines).
- `quantity` DECIMAL(15,3): Ordered quantity (0 on service lines).
- `unit_price` DECIMAL(15,2): Price per unit in INR, before discount.
- `discount_pct` DECIMAL(6,2): Line discount in percent.
- `total_amount` DECIMAL(15,2): Line value in INR after discount, before GST (file 'Total (LC)'). Service lines carry the charge here with quantity 0.
- `tax_total` DECIMAL(15,2): GST on the line in INR.
- `payment_terms` VARCHAR(50): Payment terms, e.g. 'Net-30', '100% ADVANCE'.

## fact_sales_order_lines - contact, address, remarks and source (src_) columns

Table `fact_sales_order_lines` (fact): one row per sales order line (amounts in INR). Primary key: `sales_order_line_id`.
src_* columns hold the values exactly as in the file, to trace -1 Unknown keys; use the dimension tables for names in reports.

Columns:
- `contact_person` VARCHAR(100): Customer contact person for the order.
- `contact_number` VARCHAR(30): Customer contact phone number.
- `bill_to_address` VARCHAR(500): Bill-to address on the order.
- `ship_to_address` VARCHAR(500): Ship-to address on the order.
- `remarks` VARCHAR(500): Remarks on the order line.
- `src_customer_code` VARCHAR(20): Customer code exactly as in the file (cleaned), to trace -1 rows.
- `src_customer_name` VARCHAR(255): Customer name as in the file, for tracing (use dim_customers.customer_name in reports).
- `src_product_code` VARCHAR(30): Item number as in the file (NULL on service lines), to trace -1 rows.
- `src_sales_person` VARCHAR(110): Sales employee as written in the file, for tracing.
- `src_tax_code` VARCHAR(30): Tax information as written in the file, e.g. 'IGST 18', for tracing.

## fact_invoice_lines - what one row is, keys and joins

Table `fact_invoice_lines` (fact). Primary key: `invoice_line_id`.
What one row is: Invoice lines and credit / debit note lines (fact). One row per line of Sales Invoice Details (document_type 'INVOICE') plus one row per line of GSTR1_Credit_Debit_Note.csv (document_type 'CREDIT_NOTE' or 'DEBIT_NOTE'). Amounts in INR. Net sales = SUM(net_taxable_value) (credit notes are negative there).
document_type tells invoice lines ('INVOICE') from credit notes ('CREDIT_NOTE') and debit notes ('DEBIT_NOTE'). Count invoices with COUNT(DISTINCT invoice_number) WHERE document_type = 'INVOICE'.
Joins: join fact_invoice_lines.customer_id = dim_customers.customer_id; join fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id; join fact_invoice_lines.invoice_date_id = dim_calendar.date_id; join fact_invoice_lines.note_date_id = dim_calendar.date_id; join fact_invoice_lines.product_id = dim_products.product_id; join fact_invoice_lines.sales_person_id = dim_sales_people.sales_person_id.

Columns:
- `invoice_line_id` INT (primary key): Invoice line key: invoice lines first (file order), then note lines.
- `source_format` VARCHAR(20): Source file: 'INVOICE_DETAILS' = Sales Invoice Details.xlsx; 'CREDIT_NOTE' / 'DEBIT_NOTE' = GSTR1_Credit_Debit_Note.csv.
- `document_type` VARCHAR(15): 'INVOICE', 'CREDIT_NOTE' (reduces sales, negative net_* values) or 'DEBIT_NOTE' (positive).
- `source_row_no` INT: Row number in the source file ('#' for invoices, data line number for notes), for tracing.
- `invoice_date_id` INT: -> dim_calendar.date_id of invoice_date (for notes: the NOTE date). -1 = missing / outside the calendar.
- `invoice_date` DATE: Invoice date; for credit / debit notes the note date (so a note reduces sales in the month it is issued).
- `customer_id` INT: -> dim_customers.customer_id. Found via the sales order (SO number + financial year), else the billing name; notes use the original invoice's customer. -1 = Unknown.
- `product_id` INT: -> dim_products.product_id (item code; for notes the original invoice line with the same description). -1 = no item (service line) or not found.
- `sales_person_id` INT: -> dim_sales_people.sales_person_id (notes: the original invoice's sales person). -1 = Unknown.
- `fx_rate_id` INT: -> dim_fx_rates.fx_rate_id: the INR->JPY window holding invoice_date. -1 = outside every window.

## fact_invoice_lines - invoice number, sales order, sale type and customer columns

Table `fact_invoice_lines` (fact): one row per invoice line or credit / debit note line (amounts in INR). Primary key: `invoice_line_id`.
Export vs domestic: fact_invoice_lines.sale_type ('Domestic', 'Export', 'Service'). OEM / after-market: fact_invoice_lines.customer_type (often NULL). Link to the sales order with so_number + so_date (= fact_sales_order_lines.order_date).

Columns:
- `invoice_number` VARCHAR(30): Invoice number, e.g. 'SSMI/D/2526/169'. For notes: the ORIGINAL invoice the note corrects.
- `invoice_series` VARCHAR(5): Document series: D = domestic, E = export, S = service, DU = duplicate (from the invoice number); CN = credit note, DN = debit note.
- `transaction_type` VARCHAR(30): Transaction type from the invoice file, e.g. 'GST Tax Invoice'. NULL on note rows.
- `so_number` INT: Sales order number the line was invoiced from (notes: from the original invoice). Restarts every financial year - pair it with so_date.
- `so_date` DATE: Date of that sales order.
- `customer_ref_no` VARCHAR(50): Customer's purchase-order reference.
- `customer_type` VARCHAR(10): 'OEM' or 'AFT' (after-market); often blank.
- `territory` VARCHAR(50): Sales territory, e.g. 'South Region - 1', 'Export'.
- `sale_type` VARCHAR(10): 'Domestic', 'Export' or 'Service' (file 'Type Export/Domestic'; notes: from the original invoice).
- `customer_billing_name` VARCHAR(255): Bill-to customer name as on the document.
- `customer_billing_city` VARCHAR(100): Bill-to city as on the document.
- `place_of_supply_state` VARCHAR(10): GST place of supply, 2-letter state code, e.g. 'KA'. NULL for exports.
- `country` VARCHAR(100): Bill-to country (spelling corrected; notes: from the original invoice).
- `customer_billing_gstin` VARCHAR(20): Customer's billing GSTIN.
- `customer_shipping_gstin` VARCHAR(20): Customer's shipping GSTIN.
- `customer_billing_address` VARCHAR(500): Bill-to address as on the document.
- `customer_shipping_address` VARCHAR(500): Ship-to address as on the document.
- `src_sales_person` VARCHAR(110): Sales employee as written in the invoice file, for tracing (NULL on note rows).
- `remarks` VARCHAR(500): Remarks on the invoice, e.g. 'Based On Sales Orders 182.'.

## fact_invoice_lines - item and quantity columns

Table `fact_invoice_lines` (fact): one row per invoice line or credit / debit note line (amounts in INR). Primary key: `invoice_line_id`.
Use net_quantity for quantity sold (credit notes negative); quantity is as printed (always positive). Service lines have item_type 'S', quantity 0 and product_id -1.

Columns:
- `item_type` VARCHAR(1): 'G' = goods, 'S' = service.
- `src_product_code` VARCHAR(30): SAP item code as in the invoice file ('Part Code SAP Code'), to trace -1 rows. NULL on service lines and on note rows (the note file has no item code).
- `foreign_code` VARCHAR(50): Client's product code as on the invoice line ('Item Foreign Code'); NULL when the item has none.
- `item_description` VARCHAR(255): Item description as on the document.
- `hsn_code` VARCHAR(20): HSN code (goods) as on the document.
- `sac_code` VARCHAR(20): SAC code (services) as on the document.
- `uom` VARCHAR(20): Unit of measure as in SAP, e.g. 'Manual'.
- `quantity` DECIMAL(15,3): Quantity as printed on the document (always positive; see net_quantity).
- `unit_price` DECIMAL(15,2): Price per unit in INR.
- `net_quantity` DECIMAL(15,3): Signed quantity: + for invoices and debit notes, - for credit notes.

## fact_invoice_lines - invoice value: taxable value, net taxable value, freight and totals

Table `fact_invoice_lines` (fact): one row per invoice line or credit / debit note line (amounts in INR). Primary key: `invoice_line_id`.
Use these columns for any question about invoice value, sales value or the amount of an invoice.
Invoice value / net sales (INR, before GST and freight) = SUM(fact_invoice_lines.net_taxable_value) - credit notes are already negative there. taxable_value is as printed (always positive), so never SUM taxable_value over credit notes.
Sales value incl. freight = SUM(net_taxable_value) + SUM(COALESCE(freight_amount, 0)). Incl. GST = SUM(net_line_total_incl_gst). Never SUM invoice_total_incl_gst (repeated on every line).

Columns:
- `taxable_value` DECIMAL(15,2): Taxable value in INR, before GST and freight, as printed (always positive; see net_taxable_value).
- `net_taxable_value` DECIMAL(15,2): Signed taxable value in INR: + for invoices and debit notes, - for credit notes. SUM(net_taxable_value) = net sales before GST and freight.
- `freight_amount` DECIMAL(15,2): Freight / packing charged on the line, INR (NULL on note rows). Sales value = net_taxable_value + freight_amount.
- `freight_detail` VARCHAR(50): What the freight amount is: 'Freight' or 'Packing Charges'.
- `freight_sac_code` VARCHAR(20): SAC code of the freight charge.
- `line_total_incl_gst` DECIMAL(15,2): Line total in INR including GST and freight, as printed (always positive).
- `net_line_total_incl_gst` DECIMAL(15,2): Signed line total incl. GST in INR (- for credit notes).
- `doc_round_off` DECIMAL(15,2): Document-level rounding in INR.
- `invoice_total_incl_gst` DECIMAL(15,2): Total of the WHOLE invoice incl. GST, repeated on every line of the invoice - do not SUM it over lines. NULL on note rows.
- `invoice_discount_pct` DECIMAL(6,2): Invoice-level discount in percent.

## fact_invoice_lines - GST tax columns (IGST, CGST, SGST, cess)

Table `fact_invoice_lines` (fact): one row per invoice line or credit / debit note line (amounts in INR). Primary key: `invoice_line_id`.
GST on invoices = SUM(igst_amount + cgst_amount + sgst_amount). These amounts are positive as printed, also on credit notes - subtract credit note rows (document_type = 'CREDIT_NOTE') yourself if a net figure is needed.

Columns:
- `igst_rate` DECIMAL(5,2): IGST rate in percent (inter-state GST).
- `igst_amount` DECIMAL(15,2): IGST amount in INR.
- `cgst_rate` DECIMAL(5,2): CGST rate in percent (intra-state, central half).
- `cgst_amount` DECIMAL(15,2): CGST amount in INR.
- `sgst_rate` DECIMAL(5,2): SGST rate in percent (intra-state, state half).
- `sgst_amount` DECIMAL(15,2): SGST amount in INR.
- `cess_rate` DECIMAL(5,2): GST cess rate in percent (note rows only; NULL on invoice rows).
- `cess_amount` DECIMAL(15,2): GST cess amount in INR (note rows only).

## fact_invoice_lines - credit / debit note columns

Table `fact_invoice_lines` (fact): one row per invoice line or credit / debit note line (amounts in INR). Primary key: `invoice_line_id`.
Credit note rows: document_type = 'CREDIT_NOTE', invoice_series 'CN', invoice_date = the NOTE date, invoice_number = the ORIGINAL invoice, net_quantity / net_taxable_value / net_line_total_incl_gst negative, quantity / taxable_value positive as printed.

Columns:
- `note_number` VARCHAR(30): Credit / debit note number, e.g. 'SSMI/CN/2526/1' (series prefix + suffix + note no.). NULL on invoice rows.
- `note_series` VARCHAR(20): Note series, e.g. 'CN/2526' (CN + financial year). NULL on invoice rows.
- `note_date_id` INT: -> dim_calendar.date_id of note_date. -1 on invoice rows (not a note) or unknown.
- `note_date` DATE: Date the credit / debit note was issued. NULL on invoice rows.
- `note_value` DECIMAL(15,2): Total value of the note in INR incl. GST, as printed (positive). NULL on invoice rows.
- `original_invoice_number` VARCHAR(30): Invoice the note corrects. NULL on invoice rows.
- `original_invoice_date` DATE: Date of the invoice the note corrects. NULL on invoice rows.
- `issue_reason` VARCHAR(255): Reason given for the note, e.g. 'Rate difference / return - ...'.

## fact_stock_ledger - what one row is, keys and joins

Table `fact_stock_ledger` (fact). Primary key: `stock_ledger_id`.
What one row is: Stock ledger (fact) from the Inventory Audit Report 'as on DDMMYY'. Per item: a Closing balance row, an Opening Balance row, then the movements. Never SUM every row: stock value on a date = SUM(cumulative_value) of the 'Closing balance' rows of that report_date.
One report per Inventory Audit Report file (report_date from the file name 'as on DDMMYY'); new reports arrive with each load - list them with SELECT DISTINCT report_date. Current / latest stock = the newest report: report_date = (SELECT MAX(report_date) FROM fact_stock_ledger). Stock value on a date = SUM(cumulative_value) of the 'Closing balance' rows of that report_date (join dim_stock_movement_types, movement_type = 'Closing balance').
Joins: join fact_stock_ledger.movement_type_id = dim_stock_movement_types.movement_type_id; join fact_stock_ledger.posting_date_id = dim_calendar.date_id; join fact_stock_ledger.product_id = dim_products.product_id; join fact_stock_ledger.report_date_id = dim_calendar.date_id.

Columns:
- `stock_ledger_id` INT (primary key): Stock ledger row key, in file order.
- `source_row_no` INT: Row number ('#') in the inventory file, for tracing.
- `report_date_id` INT: -> dim_calendar.date_id of report_date. -1 = unknown.
- `report_date` DATE: Snapshot date, from the file name 'as on DDMMYY' (200926 = 20-Sep-2026).
- `product_id` INT: -> dim_products.product_id (matched on the item number). -1 = item not in the master.
- `movement_type_id` INT: -> dim_stock_movement_types.movement_type_id. Blank document = Closing balance, 'Opening Balance' = Opening Balance, else the letters before the document number decide.
- `posting_date_id` INT: -> dim_calendar.date_id of posting_date. -1 on balance rows (no posting date) or unknown.
- `posting_date` DATE: Posting date of the movement. NULL on balance rows.
- `system_date` DATE: Date the movement was entered in SAP. NULL on balance rows.

## fact_stock_ledger - document, quantity, cost and value columns

Table `fact_stock_ledger` (fact): one row per stock ledger row of the inventory report (balance or movement). Primary key: `stock_ledger_id`.
Balance rows (Opening Balance / Closing balance) carry the balance in cumulative_qty / cumulative_value; movement rows carry quantity and transaction_value. Never SUM cumulative_value over movement rows or over all rows.

Columns:
- `src_product_code` VARCHAR(30): Item number as in the file, filled down from the item's first row, to trace -1 rows.
- `item_description` VARCHAR(255): Item description (filled down like the item number).
- `document_no` VARCHAR(50): SAP document, e.g. 'PD 578' (prefix + number); 'Opening Balance' on opening rows; NULL on closing-balance rows.
- `doc_row` INT: Line number inside the SAP document.
- `warehouse_code` VARCHAR(10): SAP warehouse code, e.g. '03'. NULL on balance rows.
- `quantity` DECIMAL(15,3): Movement quantity: + = into stock, - = out of stock. NULL on balance rows.
- `unit_cost` DECIMAL(15,4): Cost per unit in INR.
- `transaction_value` DECIMAL(15,2): Value of the movement in INR (+ in, - out); 0 on balance rows.
- `cumulative_qty` DECIMAL(15,3): Running stock quantity after this row (on balance rows: the balance).
- `cumulative_value` DECIMAL(15,2): Running stock value in INR after this row (on balance rows: the balance value).

## load_log - load history per run and table (data quality)

Table `load_log` (run log: one row per table per load run). Primary key: `load_log_id`.
What one row is: Load history: one row per gold table per run of load_gold.py (run 1 = the FULL load from inputdata/, then one run per INCREMENTAL batch). Rows read, inserted / updated / skipped, rows with an Unknown (-1) key, every cleaning fix. A full load starts the history again.
Use it to answer 'when was the data last loaded / how many rows did the last load add, update or skip / how many Unknown keys / what was cleaned'. The latest run = `WHERE run_id = (SELECT MAX(run_id) FROM load_log)`. Not joined to any other table.

Columns:
- `load_log_id` INT (primary key): Log row key.
- `run_id` INT: Load run number: 1 = the full load; each incremental batch run adds 1. The latest run = MAX(run_id).
- `run_type` VARCHAR(12): 'FULL' = every table dropped and rebuilt from inputdata/; 'INCREMENTAL' = one batch folder merged into the existing tables (nothing dropped).
- `batch_name` VARCHAR(100): Folder the run read: 'inputdata' for the full load, e.g. 'batch_001' for a batch.
- `table_name` VARCHAR(64): Gold table this row is about.
- `source_file` VARCHAR(255): Input file(s) the table was built from.
- `source_rows` INT: Data rows read from the source file(s), empty lines not counted (for dim_calendar: days generated; dim_sales_people / dim_tax_codes: distinct names / codes found).
- `loaded_rows` INT: FULL run: rows loaded, not counting the -1 Unknown row. INCREMENTAL run: rows written by the run = inserted_rows + updated_rows.
- `inserted_rows` INT: Rows added by this run (business key not in the table before).
- `updated_rows` INT: Rows already in the table (same business key) whose values changed: updated in place, same id. 0 on a FULL run.
- `skipped_rows` INT: Rows read but not written: already in the table with the same values, or exact duplicate lines inside the batch (see fixes). 0 on a FULL run. For facts: source_rows = inserted_rows + updated_rows + skipped_rows.
- `table_rows_after` INT: Rows in the table after this run, not counting the -1 Unknown row.
- `unknown_key_rows` INT: Fact rows of this run where a key that should have matched fell back to -1 (details in fixes).
- `fixes` TEXT: Every cleaning fix with its count, '; ' separated. Rows are never dropped.
- `loaded_at` DATETIME: When this run loaded the table.

## ml_run_log - the ML runs (when the forecasts and estimates were made)

Table `ml_run_log` (ML results: one row per scenario per run of `python manage.py run_ml`). Primary key: `run_id` + `scenario`.
What one row is: one model run of one scenario: the ml_ table it wrote, the rows written, its key quality number and the newest invoice date the models used (data_to). The models work 'as of' data_to, not as of today; the ml_ result tables hold the LATEST run only and are rebuilt by run_ml after each data load. Their rows are ESTIMATES, not recorded facts (business rule 'ML results').
Use it for 'when were the forecasts made / up to which date / how accurate is the forecast / what data was each model built from' (trained_on). The latest run = `WHERE run_id = (SELECT MAX(run_id) FROM ml_run_log)`. Not joined to any other table.

Columns:
- `run_id` INT: Run number: 1 = the first run of ml/run_ml.py, +1 on every run. The latest run = MAX(run_id).
- `scenario` VARCHAR(30): Scenario: 'sales_forecast', 'customer_risk', 'customer_segments', 'invoice_alerts', 'product_pairs' or 'stock_runout'.
- `result_table` VARCHAR(64): The ml_* table this scenario wrote, e.g. 'ml_sales_forecast'.
- `rows_written` INT: Rows the scenario wrote into its result table in this run.
- `metric_name` VARCHAR(60): Name of the scenario's key number, e.g. 'backtest MAPE % (last 6 months)' for the forecast.
- `metric_value` DECIMAL(18,2): Value of that key number (e.g. 3.85 = a 3.85 % average error).
- `seconds` DECIMAL(9,2): Seconds the scenario took (reading, training and preparing; not the writing).
- `data_to` DATE: Newest invoice date in ss_gold the models used (e.g. 2026-10-31). Results are 'as of' this date.
- `run_at` DATETIME: When this run wrote its results.
- `trained_on` VARCHAR(255): The data this scenario was trained on / built from, in plain English, e.g. '30 complete sales months May 2024 - Oct 2026 (net sales per sales month)' for the forecast, 'invoices 02-Apr-2024 - 31-Oct-2026' for the customer groups, 'stock report 31-Oct-2026 + invoices 03-Aug-2026 - 31-Oct-2026 (the last 90 days)' for the stock run-out. NULL for runs before 18-Nov-2026.

## ml_sales_forecast - sales forecast for the next sales months (total and top products)

Table `ml_sales_forecast` (ML results: a FORECAST, not actual sales). Primary key: `forecast_id`.
What one row is: the forecast net sales (before GST, like SUM(net_taxable_value)) of one future sales month: for the whole company (level 'TOTAL': the next 12 sales months after the newest complete sales month - Nov 2026 to Oct 2027 for the data to 31-Oct-2026) or for one product (level 'PRODUCT': the next 3 sales months - Nov 2026, Dec 2026, Jan 2027 - only for the top 10 products, one row per product and month). low_inr to high_inr = an 80 % range, wider for months further ahead. Never add forecast_inr to actual sales.
Use it for 'what will our sales be next month / in the next 3 months / in the next 12 months', 'sales forecast', 'expected / projected sales', 'forecast for product X'. A product outside the top 10 has no forecast row. The model is TRAINED on the complete sales months of the past (train_from_month to train_to_month: May 2024 to Oct 2026 = 30 months) and FORECASTS the 12 months after them - the training period and the forecast months are different things.

Columns:
- `forecast_id` INT (primary key): Row key: TOTAL rows first (in month order), then the PRODUCT rows (month by month).
- `level` VARCHAR(10): 'TOTAL' = the whole company's net sales; 'PRODUCT' = one product (one of the top 10 by net sales of the last 12 complete sales months).
- `product_id` INT: -> dim_products.product_id on PRODUCT rows; NULL on TOTAL rows.
- `product_code` VARCHAR(30): SAP item code on PRODUCT rows, e.g. 'FG00123'; NULL on TOTAL rows.
- `product_description` VARCHAR(255): Product description on PRODUCT rows; NULL on TOTAL rows.
- `sales_month` VARCHAR(8): The forecast sales month, named like dim_calendar.sales_month, e.g. 'Nov 2026' (21-Oct-2026 .. 20-Nov-2026).
- `period_start` DATE: First day of that sales month (the 21st of the previous month).
- `period_end` DATE: Last day of that sales month (the 20th).
- `horizon_months` TINYINT: How far ahead: 1 = the first sales month after the newest complete one, 2 = the next, ... 12 = the twelfth (TOTAL rows 1-12, PRODUCT rows 1-3).
- `forecast_inr` DECIMAL(18,2): Forecast net sales in INR, before GST and freight (the model's best guess).
- `low_inr` DECIMAL(18,2): Low end of the 80 % range in INR: the actual is expected to be above this 9 times in 10.
- `high_inr` DECIMAL(18,2): High end of the 80 % range in INR: the actual is expected to be below this 9 times in 10.
- `model_name` VARCHAR(80): Model that made the forecast, e.g. 'Holt-Winters (trend + multiplicative 12-month season)'; for products 'Share of the total forecast'.
- `mape_pct` DECIMAL(9,2): Backtest accuracy: average error in % (MAPE) when the model forecast the last 6 complete sales months from the months before. Lower is better; 5 = 5 % average error.
- `train_from_month` VARCHAR(8): First sales month the model was trained on (the oldest COMPLETE sales month of the data), e.g. 'May 2024'. The same on every row.
- `train_to_month` VARCHAR(8): Last sales month the model was trained on (the newest COMPLETE sales month), e.g. 'Oct 2026'. The forecast starts with the month after it. The same on every row.
- `train_months` SMALLINT: How many complete sales months the model was trained on (train_from_month .. train_to_month), e.g. 30. The same on every row.
- `data_to` DATE: Newest invoice date the model saw. The forecast is 'as of' this date (the last complete sales month ends on or before it).
- `run_at` DATETIME: When ml/run_ml.py made this forecast.

## ml_customer_risk - customers who might stop buying (churn risk score)

Table `ml_customer_risk` (ML results: an ESTIMATE). Primary key: `customer_id`.
What one row is: one customer with a real buying history (at least 6 invoices over 6 months, some sales in the last 15 months) and a 0-100 risk score of buying less or stopping, as of the newest invoice date (data_to). Not the same as 'customers who stopped buying' (no invoice in the last 3 months - fact_invoice_lines).
Use it for 'which customers might stop buying / are at risk / may churn / are we losing'. Highest risk first: ORDER BY risk_score DESC; give the reason.

Columns:
- `customer_id` INT (primary key): -> dim_customers.customer_id.
- `customer_code` VARCHAR(20): SAP customer code, e.g. 'C0001'.
- `customer_name` VARCHAR(255): Customer name (dim_customers.customer_name).
- `risk_score` DECIMAL(9,2): Risk score 0-100: 40 % sales drop and 40 % fewer sales orders against the customer's normal level, 20 % days since the last invoice against its usual gap; lowered for customers who normally order less than about once a month. Higher = more likely to be lost.
- `risk_level` VARCHAR(10): 'High' (score >= 50), 'Medium' (30-49) or 'Low' (< 30).
- `reason` VARCHAR(500): Why, in plain English, e.g. 'Sales fell 82% (last 3 months vs its normal 3 months); no invoice for 140 days (usually every 20 days)'.
- `last_invoice_date` DATE: Date of the customer's last invoice (on or before data_to).
- `days_since_last_invoice` INT: Days from the last invoice to data_to (the newest invoice date in ss_gold).
- `typical_gap_days` INT: The customer's usual number of days between two invoice dates (median).
- `sales_last_3m_inr` DECIMAL(18,2): Net sales of the last 3 months (the 91 days up to data_to), INR before GST.
- `sales_prev_3m_inr` DECIMAL(18,2): Net sales of the 3 months before those (days 92-182 before data_to), INR.
- `change_pct` DECIMAL(9,2): Change of the last 3 months against the previous 3 months in % (-50 = half). NULL when the previous 3 months had no sales.
- `normal_3m_inr` DECIMAL(18,2): The customer's normal 3-month sales the drop is measured against: the higher of the average 3 months of the 12 months before the last 3 months and the same 3 months a year ago, INR.
- `drop_pct` DECIMAL(9,2): How far the last 3 months are below that normal level, in % (100 = no sales at all, 0 = at or above normal).
- `orders_last_3m` INT: Sales orders (not cancelled; SO number + order date) of the last 3 months (91 days up to data_to).
- `orders_normal_3m` DECIMAL(9,2): The customer's normal number of sales orders per 3 months (the higher of the average of the 12 months before the last 3 months and the same 3 months a year ago).
- `invoices_last_12m` INT: Invoices (distinct invoice numbers) of the last 12 months.
- `invoices_total` INT: Invoices of the customer in all the data.
- `lifetime_sales_inr` DECIMAL(18,2): Net sales of the customer in all the data, INR before GST.
- `run_at` DATETIME: When ml/run_ml.py made this score.

## ml_customer_segments - customer groups by buying behaviour (segments)

Table `ml_customer_segments` (ML results: groups found by a clustering model). Primary key: `customer_id`.
What one row is: one customer with at least one invoice and the group (segment) it was put in by how recently, how often and how much it buys and how long it has bought: 'Big regular buyers', 'Regular buyers', 'Occasional buyers', 'New customers' or 'Lapsed'.
Use it for 'what customer groups / segments / kinds of customers do we have', 'which customers are in group X'. SAP's own customer_group ('Local Customer', 'Foreign Customer') is in dim_customers - use that only when the user says local / foreign / SAP customer group.

Columns:
- `customer_id` INT (primary key): -> dim_customers.customer_id.
- `customer_code` VARCHAR(20): SAP customer code, e.g. 'C0001'.
- `customer_name` VARCHAR(255): Customer name (dim_customers.customer_name).
- `segment_no` TINYINT: Group number 1-5 (1 = Big regular buyers, 2 = Regular buyers, 3 = Occasional buyers, 4 = New customers, 5 = Lapsed).
- `segment_name` VARCHAR(30): Group name: 'Big regular buyers', 'Regular buyers', 'Occasional buyers', 'New customers' or 'Lapsed'.
- `recency_days` INT: Days from the customer's last invoice to data_to (the newest invoice date).
- `invoices` INT: Invoices of the customer in all the data (distinct invoice numbers).
- `sales_inr` DECIMAL(18,2): Net sales of the customer in all the data, INR before GST.
- `tenure_days` INT: Days from the customer's first invoice to data_to.
- `first_invoice_date` DATE: Date of the customer's first invoice.
- `last_invoice_date` DATE: Date of the customer's last invoice.
- `run_at` DATETIME: When ml/run_ml.py made the groups.

## ml_invoice_alerts - unusual invoices (price, quantity, large credit notes)

Table `ml_invoice_alerts` (ML results: anomalies found by a model - lines to check, not proven errors). Primary key: `alert_id`.
What one row is: one invoice line with a unit price or quantity far from that product's normal, or a credit note much larger than usual (at most 100 price, 60 quantity and 40 credit-note alerts).
Use it for 'any unusual / strange / suspicious invoices', 'odd prices', 'anomalies', 'invoices to check'. Most unusual first: ORDER BY score DESC (alert_id 1 = the highest score).

Columns:
- `alert_id` INT (primary key): Alert key (1 = the highest score).
- `alert_type` VARCHAR(20): 'Unusual price' (unit price far from the product's median price), 'Unusual quantity' (quantity far above the product's usual quantity) or 'Large credit note' (a credit note much bigger than usual).
- `invoice_number` VARCHAR(30): Invoice number, e.g. 'SSMI/D/2526/169'. For a credit note: the ORIGINAL invoice it corrects (like fact_invoice_lines.invoice_number).
- `note_number` VARCHAR(30): Credit note number on 'Large credit note' rows, e.g. 'SSMI/CN/2627/1'; NULL on the other rows.
- `invoice_date` DATE: Invoice date; for a credit note the note date.
- `customer_id` INT: -> dim_customers.customer_id (-1 = Unknown customer).
- `customer_name` VARCHAR(255): Customer name (dim_customers.customer_name).
- `product_code` VARCHAR(30): SAP item code of the line (for a credit note: of its biggest line).
- `product_description` VARCHAR(255): Product description.
- `value_inr` DECIMAL(18,2): The unusual value in INR: 'Unusual price' = the unit price; 'Unusual quantity' = the line's taxable value; 'Large credit note' = the note's taxable value (positive).
- `typical_inr` DECIMAL(18,2): The normal value to compare with, INR: the product's median unit price; the product's median quantity x median price; the median credit note.
- `quantity` DECIMAL(15,3): Quantity of the line on 'Unusual quantity' / 'Unusual price' rows; NULL on credit notes.
- `typical_quantity` DECIMAL(15,3): The product's median quantity per invoice line on 'Unusual quantity' rows; NULL on the others.
- `score` DECIMAL(9,2): How unusual: the robust z-score (distance from normal in 'normal spreads'). 3.5 or more is very unusual; higher = stronger.
- `reason` VARCHAR(500): Why, in plain English, e.g. 'Unit price 41,000 is 31% below this product's usual 59,500 (seen on 48 lines)'.
- `run_at` DATETIME: When ml/run_ml.py found the alert.

## ml_product_pairs - products bought together (market basket)

Table `ml_product_pairs` (ML results: association rules from the sales orders). Primary key: `product_a_id` + `product_b_id`.
What one row is: two products that are often on the same sales order (cancelled orders left out), bought together more often than by chance (lift > 1). product_a = the product of the pair with fewer orders; each pair is stored once.
Use it for 'which products are bought together', 'what else do customers buy with X', 'cross-sell'. For one product X search BOTH sides: product_a_description LIKE '%X%' OR product_b_description LIKE '%X%' (also the codes).

Columns:
- `product_a_id` INT: -> dim_products.product_id of product A (the one with fewer orders).
- `product_a_code` VARCHAR(30): SAP item code of product A.
- `product_a_description` VARCHAR(255): Description of product A.
- `product_b_id` INT: -> dim_products.product_id of product B.
- `product_b_code` VARCHAR(30): SAP item code of product B.
- `product_b_description` VARCHAR(255): Description of product B.
- `orders_together` INT: Sales orders that had both products.
- `orders_a` INT: Sales orders that had product A.
- `orders_b` INT: Sales orders that had product B.
- `support_pct` DECIMAL(9,4): orders_together / all sales orders x 100 (how common the pair is overall).
- `confidence_pct` DECIMAL(9,2): orders_together / orders_a x 100: of the orders with product A, this % also had product B.
- `lift` DECIMAL(9,2): How many times more often A and B are on one order than by chance (1 = chance; 2 = twice as often).
- `min_orders` INT: The threshold of this run: pairs need at least this many orders together.
- `run_at` DATETIME: When ml/run_ml.py found the pairs.

## ml_stock_runout - items that will run out of stock (days of stock left)

Table `ml_stock_runout` (ML results: an ESTIMATE from the latest stock report and the last 90 days of sales). Primary key: `product_code`.
What one row is: one item of the newest stock report: its stock, its average daily sales quantity over the last 90 days of invoices, the days the stock lasts at that speed and the date it runs out.
Use it for 'which items will run out of stock soon', 'days of stock left', 'when will we run out of X'. Soonest first: ORDER BY days_left. Always say the report_date.

Columns:
- `product_id` INT: -> dim_products.product_id (-1 = an item of the report not in the item master).
- `product_code` VARCHAR(30) (primary key): SAP item code, e.g. 'FG00123'.
- `product_description` VARCHAR(255): Product description.
- `item_group` VARCHAR(50): Item group from dim_products: 'Finished goods' are sold; raw materials, consumables and capital items never are (always 'No recent sales').
- `report_date` DATE: Date of the stock report used (the newest fact_stock_ledger.report_date).
- `stock_qty` DECIMAL(15,3): Stock quantity on report_date (the 'Closing balance' cumulative_qty).
- `sold_qty_90d` DECIMAL(15,3): Quantity sold in the last 90 days of invoices up to data_to (SUM(net_quantity), credit notes subtract).
- `avg_daily_sales_qty` DECIMAL(15,3): Average quantity sold per day = sold_qty_90d / 90.
- `days_left` DECIMAL(9,1): Days the stock lasts at that speed = stock_qty / avg_daily_sales_qty. NULL when nothing was sold in the 90 days.
- `runout_date` DATE: report_date + days_left: the day the stock runs out at the current speed. NULL when nothing was sold.
- `status` VARCHAR(20): 'Out of stock' (stock 0 or less), 'Under 30 days', 'Under 90 days', 'OK' (90 days or more) or 'No recent sales'.
- `run_at` DATETIME: When ml/run_ml.py made this row.
