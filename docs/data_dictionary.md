# ai_gold data dictionary

Plain-English meaning of every table and column in the MySQL database `ai_gold` (read-only for the AI).
Column meanings are the MySQL column COMMENTs (the source of truth). Amounts are INR unless a column says otherwise.

## ai_gold overview - star schema (fact and dimension tables)

`ai_gold` is a star schema built from the synthetic NOP files by loader/load_gold.py.
- Fact tables (the numbers): `fact_invoice_lines` (invoice and credit note lines - sales), `fact_sales_order_lines` (sales order lines - orders booked), `fact_stock_ledger` (stock balances and movements, one snapshot per Inventory Audit Report date).
- Dimension tables (the descriptions): `dim_calendar` (one row per day, financial year and NOP sales month), `dim_customers`, `dim_products`, `dim_fx_rates` (INR to JPY rate windows), `dim_sales_people`, `dim_tax_codes` (GST codes on sales orders), `dim_stock_movement_types` (kinds of stock ledger row).
- `load_log`: load history, one row per table per load run (full load, then incremental batches): rows read / inserted / updated / skipped, Unknown keys, cleaning fixes.
- Every fact key column is NOT NULL and has a real FOREIGN KEY to its dimension, so a plain JOIN never loses rows (Unknown keys point to the -1 row).
- Questions about sales / revenue / invoice value use `fact_invoice_lines`; about orders, order intake or open orders use `fact_sales_order_lines`; about stock or inventory value use `fact_stock_ledger`.
- The data grows with every load (full load, then incremental batches), so never assume a last date: check it with MIN / MAX on the date columns (business rule 'Data coverage'). Fixed starts: invoices 21-Dec-2025; sales orders 02-Apr-2024; calendar 01-Apr-2024 to 31-Mar-2027.

## How the ai_gold tables join (all foreign keys)

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
Join the calendar to filter or group by calendar month (month_year), financial year (financial_year) or NOP sales month (nop_sales_month).

## dim_calendar - date key, calendar month and financial year columns

Table `dim_calendar` (dimension, incl. the -1 Unknown row). Primary key: `date_id`.
What one row is: One row per day from 01-Apr-2024 to 31-Mar-2027, plus the Unknown row -1. Gives every date its calendar month, Indian financial year (Apr-Mar) and NOP sales month (21st to 20th). Every *_date_id in the facts points here.
Every *_date_id column of the fact tables joins here: join <fact>.<x>_date_id = dim_calendar.date_id, then filter or group on the calendar columns (month_year, financial_year, nop_sales_month ...).
Calendar month ('Sep 2026' = 1st to last day) is month_year; the NOP sales month is a different column (see 'dim_calendar - NOP sales month columns').
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
- `financial_year` VARCHAR(4): Indian financial year (1-Apr to 31-Mar) as NOP writes it: '2627' = FY 2026-27 = 01-Apr-2026 to 31-Mar-2027.
- `financial_year_label` VARCHAR(10): Financial year label, e.g. 'FY 2026-27'.
- `fiscal_period` TINYINT: Month number inside the financial year: 1 = April ... 12 = March.
- `fiscal_quarter` TINYINT: Quarter inside the financial year: 1 = Apr-Jun, 2 = Jul-Sep, 3 = Oct-Dec, 4 = Jan-Mar.
- `is_month_end` CHAR(1): 'Y' on the last day of a calendar month, else 'N'.
- `is_weekend` CHAR(1): 'Y' on Saturday and Sunday, else 'N'.

## dim_calendar - NOP sales month columns (21st to 20th)

Table `dim_calendar` (dimension): one row per day (01-Apr-2024 to 31-Mar-2027) plus the Unknown row -1. Primary key: `date_id`.
NOP sales month = 21st of the previous month to the 20th, named after the month it ENDS in: 'Oct 2026' = 21-Sep-2026 to 20-Oct-2026. Filter with dim_calendar.nop_sales_month = 'Oct 2026' after join <fact>.<x>_date_id = dim_calendar.date_id.

Columns:
- `nop_sales_month` VARCHAR(8): NOP sales month of this date, e.g. 'Oct 2026'. A NOP sales month runs from the 21st of the previous month to the 20th and is named after the month it ENDS in (21-Sep-2026 .. 20-Oct-2026 = 'Oct 2026').
- `nop_sales_month_name` VARCHAR(10): Month name of the NOP sales month, e.g. 'October'.
- `nop_sales_month_no` TINYINT: Calendar month number of the NOP sales month (10 for 'Oct 2026').
- `nop_sales_year` VARCHAR(4): Financial year of the NOP sales month, same style as financial_year: '2627' = NOP sales months Apr 2026 .. Mar 2027 (21-Mar-2026 .. 20-Mar-2027).
- `nop_sales_period_no` TINYINT: Position of the NOP sales month in its NOP sales year: 1 = April ... 12 = March.
- `nop_sales_period_start` DATE: First day of the NOP sales month (the 21st of the previous month).
- `nop_sales_period_end` DATE: Last day of the NOP sales month (the 20th).

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
What one row is: Products / items (dimension). One row per SAP item from the Item Master, with the client's product classification (PTC_NOPI / PCT_NOPJ sheets) joined on the foreign code, plus the Unknown row -1.
product_category / product_segment_* / middle_class_* are the CLIENT (NOP Japan) classification; sap_segment is SAP's own product family. NULL product_category = not classified (show it as 'Not classified', never drop it).
Joined from: fact_invoice_lines.product_id = dim_products.product_id; fact_sales_order_lines.product_id = dim_products.product_id; fact_stock_ledger.product_id = dim_products.product_id.

Columns:
- `product_id` INT (primary key): Product key. -1 = Unknown product (item code not found, or a line without item code such as a service charge).
- `product_code` VARCHAR(30): SAP item number, e.g. 'FG00001'. Prefix: FG = finished goods, RM = raw material, CO = consumables, CA = capital item. 'UNKNOWN' on the -1 row.
- `product_description` VARCHAR(255): Item description from the SAP item master.
- `item_group` VARCHAR(50): SAP item group: 'Finished goods', 'Raw material', 'Consumables' or 'Capital Item'.
- `foreign_code` VARCHAR(50): Client's (NOP Japan) product code for the item. 'India - No Foreign Code' when SAP has none.
- `product_category` VARCHAR(50): Client classification - category, e.g. 'Trochoid pumps'. From the PTC_NOPI / PCT_NOPJ row whose product code = foreign_code. NULL = not classified.
- `product_segment_code` VARCHAR(20): Client classification - product segment code, e.g. 'L-01'.
- `product_segment_name` VARCHAR(100): Client classification - product segment name, e.g. 'L-01 Trochoid'.
- `middle_class_code` VARCHAR(20): Client classification - middle segment code, e.g. '194'.
- `middle_class_name` VARCHAR(100): Client classification - middle segment name, e.g. 'Trochoid group'.
- `sales_agency` VARCHAR(10): Which client sheet classified the item: 'NOP-I' (sheet PTC_NOPI) or 'NOPJ' (sheet PCT_NOPJ). NULL = not classified.
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
What one row is: INR -> JPY exchange rates (dimension). One row per monthly rate window (21st of the previous month to the 20th = one NOP sales month), plus the Unknown row -1. JPY value = INR value x exchange_rate.
JPY value = INR value x dim_fx_rates.exchange_rate of the window holding the date: join fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id (or fact_sales_order_lines.fx_rate_id). The first window starts on 21-Dec-2024 ('Jan 2025') and new months arrive with each load; the -1 row has exchange_rate NULL (no rate for that date).
Joined from: fact_invoice_lines.fx_rate_id = dim_fx_rates.fx_rate_id; fact_sales_order_lines.fx_rate_id = dim_fx_rates.fx_rate_id.

Columns:
- `fx_rate_id` INT (primary key): Exchange-rate window key. -1 = Unknown (date outside every window).
- `rate_month` VARCHAR(8): Month the rate is for, written like dim_calendar.nop_sales_month, e.g. 'Oct 2026'.
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
- `invoice_number` VARCHAR(30): Invoice number, e.g. 'NOPI/D/2526/169'. For notes: the ORIGINAL invoice the note corrects.
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
- `note_number` VARCHAR(30): Credit / debit note number, e.g. 'NOPI/CN/2526/1' (series prefix + suffix + note no.). NULL on invoice rows.
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
