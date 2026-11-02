"""
load_gold.py - Step 2 of "Ask NOP".

Reads the 9 synthetic (fake) input files in <repo>/inputdata, CLEANS them and
writes a small gold star schema into the MySQL database `ai_gold`:

  dimensions : dim_calendar, dim_customers, dim_products, dim_fx_rates,
               dim_sales_people, dim_tax_codes, dim_stock_movement_types
  facts      : fact_sales_order_lines, fact_invoice_lines, fact_stock_ledger
  run log    : load_log (one row per table: rows read, rows loaded, fixes)

Every run DROPS and RECREATES these tables (only inside ai_gold), so running
it twice gives the same result. Each dimension has an Unknown row with id -1:
a fact row whose code or date is not found gets -1 and is never dropped.
At the end it creates / updates the read-only MySQL user the AI uses
(SELECT on ai_gold only) and prints a summary.

Run from the repo folder:
    venv\\Scripts\\python.exe loader\\load_gold.py

INCREMENTAL load of one batch folder (same file names / columns as inputdata,
any subset of the files; a missing file = no change for its tables):
    venv\\Scripts\\python.exe loader\\load_gold.py --batch inputdata_batches\\batch_001
Nothing is dropped: every row gets a business key (customer code, item no.,
rate month, ... ; fact lines: document + line number inside the document).
A key already in ai_gold with the same values is skipped, with other values it
is updated in place (same id), a new key is inserted. Exact duplicate lines
inside the batch are skipped (counted). All counts are checked before anything
is written; load_log keeps one row per table per run. Running the same batch
twice changes nothing the second time. Running WITHOUT --batch rebuilds
ai_gold from inputdata/ only (the base data).

Settings come from .env (MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD,
AI_GOLD_DATABASE, AI_DB_USER, AI_DB_PASSWORD). Passwords are never printed.
GSTR1_Invoice.csv is NOT loaded (GST-return copy of the same invoices).
"""
import argparse
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# ============================================================== settings
REPO_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_DIR / "inputdata"
load_dotenv(REPO_DIR / ".env")

GOLD_DB = "ai_gold"                 # the ONLY database this script writes to
READER_USER = "nop_ai_reader"       # the AI's read-only MySQL user
UNKNOWN = -1                        # id of the Unknown row in every dimension
CALENDAR_START = date(2024, 4, 1)
CALENDAR_END = date(2027, 3, 31)

CUSTOMER_FILE = "Customer Master Report.xlsx"
CLIENT_FILE = "Sales_Order_Data_202609.xlsx"      # client sheets
ITEM_FILE = "Item Master Lists.xlsx"
FX_FILE = "Exchange Rate.xlsx"
SALES_ORDER_FILE = "Sales Order Report.xlsx"
INVOICE_FILE = "Sales Invoice Details.xlsx"
NOTE_FILE = "GSTR1_Credit_Debit_Note.csv"         # cp1252 encoded
STOCK_FILES = "Inventory Audit Report as on *.xlsx"

NO_FOREIGN_CODE = "India - No Foreign Code"

# country names written wrongly in the source files -> correct spelling
COUNTRY_SPELLING = {
    "UNITES ARAB EMIRATES": "United Arab Emirates",
    "UNITED STATE OF AMERICA": "United States of America",
    "U.A.E.": "United Arab Emirates", "U.A.E": "United Arab Emirates", "UAE": "United Arab Emirates",
    "U.S.A.": "United States of America", "U.S.A": "United States of America",
    "USA": "United States of America", "U.K.": "United Kingdom", "UK": "United Kingdom",
    "INIDA": "India", "SAUDI ARABIYA": "Saudi Arabia",
}
# country names in their usual spelling: 'INDIA' / 'india' -> 'India'
KNOWN_COUNTRIES = {name.upper(): name for name in [
    "India", "Japan", "Saudi Arabia", "United Arab Emirates", "United Kingdom",
    "United States of America", "Thailand", "Sri Lanka", "Mexico", "China",
    "South Africa", "Germany", "Vietnam", "Singapore"]}
# sales order status as NOP writes it
STATUS_SPELLING = {"OPEN": "Open", "CLOSED": "Closed", "CANCELED": "Canceled", "CANCELLED": "Canceled"}
# exchange-rate month written in other ways -> 'Mon YYYY' ('%b-%y' = the file's own 'Jan-25')
RATE_MONTH_FORMATS = ["%b-%y", "%b %Y", "%B %Y", "%b-%Y", "%B-%y", "%B-%Y", "%Y-%m", "%b %y", "%B %y"]
# common English country names -> ISO code (the client's Country master uses
# formal names such as 'Republic of India')
COUNTRY_ISO_ALIASES = {
    "india": "IND", "saudi arabia": "SAU", "thailand": "THA",
    "sri lanka": "LKA", "mexico": "MEX", "china": "CHN",
    "south africa": "ZAF", "usa": "USA", "united states": "USA",
    "uae": "ARE", "uk": "GBR", "vietnam": "VNM",
}

# stock document prefix -> movement type id (NOP's REAL map)
MOVEMENT_TYPES = [
    # id, movement type,      row kind,   prefixes,         direction
    (UNKNOWN, "Unknown",              "MOVEMENT", "",               "?"),
    (1, "Opening Balance",            "BALANCE",  "",               "-"),
    (2, "Closing balance",            "BALANCE",  "",               "-"),
    (3, "Purchase",                   "MOVEMENT", "PD, PU, PC",     "IN"),
    (4, "Landed cost",                "MOVEMENT", "IF",             "IN"),
    (5, "COGS",                       "MOVEMENT", "IN, CN, DN, RE", "OUT"),
    (6, "Inventory transfer",         "MOVEMENT", "IM",             "IN / OUT"),
    (7, "Production",                 "MOVEMENT", "SO, SI, MR",     "IN / OUT"),
]
OPENING_BALANCE, CLOSING_BALANCE = 1, 2
PREFIX_TO_MOVEMENT = {p.strip(): mt[0] for mt in MOVEMENT_TYPES
                      for p in mt[3].split(",") if p.strip()}

PLACEHOLDERS = {"", "NA", "N/A", "#N/A", "-", "--", "NULL", "NONE", "NAN"}
TITLE_RE = re.compile(r"^(MR|MRS|MS|DR|SHRI|SMT)\.?\s+", re.IGNORECASE)


# ============================================================== fix counter
class Fixes:
    """Counts every cleaning fix for one table; text() goes to load_log.fixes."""

    def __init__(self):
        self.counts = {}

    def add(self, what, n=1):
        if n:
            self.counts[what] = self.counts.get(what, 0) + n

    def text(self):
        if not self.counts:
            return "none"
        return "; ".join(f"{what}: {n}" for what, n in self.counts.items())


# ============================================================== cleaning helpers
def is_blank(value):
    """True for None, NaN and NaT (empty Excel / CSV cells)."""
    return value is None or (not isinstance(value, str) and pd.isna(value))


def clean_text(value, fixes):
    """Trim, collapse double spaces; blank / 'NA' / '-' -> None."""
    if is_blank(value):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)                  # Excel number used as text: 50001.0 -> '50001'
    raw = str(value)
    tidy = " ".join(raw.split())
    if tidy.upper() in PLACEHOLDERS:
        if tidy:
            fixes.add("'NA' / '-' placeholder -> NULL")
        return None
    if tidy != raw:
        fixes.add("extra spaces trimmed")
    return tidy


def clean_code(value, fixes):
    """A code: cleaned text in upper case ('fg00001 ' -> 'FG00001')."""
    tidy = clean_text(value, fixes)
    if tidy is None:
        return None
    if tidy.upper() != tidy:
        fixes.add("code upper-cased")
    return tidy.upper()


def clean_number(value, fixes):
    """Number from a cell; text like '4,500.00' or 'Rs 4500' -> 4500.0."""
    if is_blank(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    raw = str(value).strip()
    tidy = re.sub(r"(?i)rs\.?|inr|₹|\$|,|\s", "", raw)
    if tidy.upper() in PLACEHOLDERS:
        if tidy:
            fixes.add("'NA' / '-' placeholder -> NULL")
        return None
    if tidy != raw:
        fixes.add("commas / currency signs removed from numbers")
    try:
        return float(tidy)
    except ValueError:
        fixes.add("bad number -> NULL")
        return None


def clean_int(value, fixes):
    number = clean_number(value, fixes)
    return None if number is None else int(round(number))


DATE_FORMAT_NAMES = {"%d/%m/%y": "dd/mm/yy", "%d/%m/%Y": "dd/mm/yyyy",
                     "%d-%m-%Y": "dd-mm-yyyy", "%d-%m-%y": "dd-mm-yy",
                     "%Y-%m-%d": "yyyy-mm-dd", "%d.%m.%Y": "dd.mm.yyyy",
                     "%d-%b-%Y": "dd-Mon-yyyy", "%d %b %Y": "dd Mon yyyy",
                     "%Y-%m-%d %H:%M:%S": "yyyy-mm-dd hh:mm:ss"}
# tried in this order when the text is not in the file's own format (none of
# them can be read two ways: the separators and the year length differ)
OTHER_DATE_FORMATS = list(DATE_FORMAT_NAMES)


def clean_date(value, text_format, fixes):
    """Date from a cell: a real Excel date, an Excel serial number, or text in
    the file's own format (text_format) or another known format. Bad value ->
    None (counted)."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):         # also pandas Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):     # Excel serial number (days since 1899-12-30)
        fixes.add("Excel serial number -> DATE")
        return date(1899, 12, 30) + timedelta(days=int(value))
    tidy = " ".join(str(value).split())
    if tidy.upper() in PLACEHOLDERS:
        if tidy:
            fixes.add("'NA' / '-' placeholder -> NULL")
        return None
    for fmt in [text_format] + [f for f in OTHER_DATE_FORMATS if f != text_format]:
        try:
            parsed = datetime.strptime(tidy, fmt).date()
        except ValueError:
            continue
        if fmt == text_format:
            fixes.add(f"text date {DATE_FORMAT_NAMES.get(text_format, text_format)} -> DATE")
        else:
            fixes.add(f"text date in another format ({DATE_FORMAT_NAMES[fmt]}) -> DATE")
        return parsed
    fixes.add("bad date -> NULL")
    return None


def clean_yes_no(value, fixes):
    """'YES' / 'Yes' / 'Y' / 'TRUE' / '1' -> 'Y';  'NO' / 'No' / 'N' / 'FALSE' / '0' -> 'N'."""
    tidy = clean_text(value, fixes)
    if tidy is None:
        return None
    flag = {"YES": "Y", "Y": "Y", "TRUE": "Y", "1": "Y",
            "NO": "N", "N": "N", "FALSE": "N", "0": "N"}.get(tidy.upper())
    if flag is None:
        fixes.add("unreadable yes/no flag -> NULL")
    elif flag != tidy:
        fixes.add("yes/no text -> Y/N")
    return flag


def clean_country(value, fixes):
    """Country name, with known spelling mistakes and odd casing corrected."""
    tidy = clean_text(value, fixes)
    if tidy and tidy.upper() in COUNTRY_SPELLING:
        fixes.add("country spelling corrected")
        return COUNTRY_SPELLING[tidy.upper()]
    if tidy and tidy.upper() in KNOWN_COUNTRIES and KNOWN_COUNTRIES[tidy.upper()] != tidy:
        fixes.add("country name casing corrected")
        return KNOWN_COUNTRIES[tidy.upper()]
    return tidy


def clean_status(value, fixes):
    """Sales order status: 'OPEN' / 'closed ' / 'cancelled' -> 'Open' / 'Closed' / 'Canceled'."""
    status = clean_text(value, fixes)
    if status:
        fixed = STATUS_SPELLING.get(status.upper(), status.title())
        if fixed != status:
            fixes.add("status text casing / spelling made consistent")
        status = fixed
    return status


def clean_payment_terms(value, fixes):
    """'Net-60 days' / 'NET 30' / 'net-45 days' -> 'Net-60' / 'Net-30' / 'Net-45'."""
    terms = clean_text(value, fixes)
    net = re.fullmatch(r"(?i)net\s*-?\s*(\d+)(\s*days?)?", terms or "")
    if net and terms != f"Net-{net.group(1)}":
        if net.group(2) and terms.startswith("Net-"):
            fixes.add("payment terms 'Net-60 days' -> 'Net-60'")
        else:
            fixes.add("payment terms 'NET 30' / 'net 45 days' -> 'Net-30' / 'Net-45'")
        terms = f"Net-{net.group(1)}"
    return terms


def rate_month_label(month, fixes):
    """'Jan-25' / 'January 2025' / '2025-01' -> 'Jan 2025' (same text as
    dim_calendar.nop_sales_month); unreadable -> kept as written."""
    for fmt in RATE_MONTH_FORMATS:
        try:
            label = datetime.strptime(month, fmt).strftime("%b %Y")
        except (TypeError, ValueError):
            continue
        if fmt == "%b-%y":
            fixes.add("rate month 'Jan-25' -> 'Jan 2025'")
        elif label != month:
            fixes.add("rate month in another format -> 'Mon YYYY'")
        return label
    return month


def name_key(name):
    """Upper case, single spaces - used only for MATCHING names."""
    return " ".join(str(name).split()).upper() if name else ""


def strip_title(name):
    """'Mr. Rahul Verma' -> 'Rahul Verma'."""
    return TITLE_RE.sub("", name).strip() if name else name


def person_key(name):
    """Matching key for a person: no title, no punctuation, upper case."""
    return re.sub(r"[^A-Z0-9 ]", "", name_key(strip_title(name))).strip()


def tax_key(code):
    """'IGST 18' / 'igst_18' / 'IGST-18' / 'Igst 18%' -> 'IGST18'."""
    return re.sub(r"[\s_\-%]+", "", str(code).upper()) if code else ""


def fy_start_year(day):
    """Indian financial year starts 1-Apr: 15-Mar-2026 -> 2025, 01-Apr-2026 -> 2026."""
    return day.year if day.month >= 4 else day.year - 1


def date_id(day):
    """date -> dim_calendar.date_id (yyyymmdd); missing or outside the calendar -> -1."""
    if day is None or not (CALENDAR_START <= day <= CALENDAR_END):
        return UNKNOWN
    return int(day.strftime("%Y%m%d"))


class Source:
    """Where the input files are read from. Full load: everything from
    inputdata/. Batch: the batch folder; a reference-only file (the client
    sheets) that the batch does not bring is read from inputdata/ (its last
    known version), every other missing file means 'no change'."""

    def __init__(self, folder, reference_folder=None):
        self.folder = Path(folder)
        self.reference_folder = Path(reference_folder or folder)

    def has(self, file_name):
        return (self.folder / file_name).is_file()

    def path(self, file_name):
        return self.folder / file_name

    def reference_path(self, file_name):
        return self.path(file_name) if self.has(file_name) else self.reference_folder / file_name

    def stock_files(self):
        return sorted(self.folder.glob(STOCK_FILES))


def read_excel(path, sheet=0, header_row=1):
    """One sheet as plain Python values. header_row is the Excel row number.
    Header cells are trimmed and double spaces collapsed."""
    df = pd.read_excel(path, sheet_name=sheet, header=header_row - 1, dtype=object)
    df.columns = [" ".join(str(c).split()) for c in df.columns]
    return df


def read_notes_csv(path, fixes):
    """GSTR1_Credit_Debit_Note.csv (cp1252) as records; '' -> empty cell."""
    notes_df = pd.read_csv(path, encoding="cp1252", dtype=str,
                           keep_default_na=False, skip_blank_lines=False)
    notes_df.columns = [" ".join(c.split()) for c in notes_df.columns]
    return records(notes_df.where(notes_df != ""), fixes)


def records(df, fixes):
    """DataFrame -> list of dicts, skipping completely empty lines (counted)."""
    empty = df.isna().all(axis=1)
    fixes.add("completely empty lines skipped", int(empty.sum()))
    return df[~empty].to_dict("records")


DUPLICATES_KEPT = "exact duplicate rows found (kept, owner to decide)"
DUPLICATES_SKIPPED = "exact duplicate line inside the batch (skipped)"


def count_exact_duplicates(rows, ignore, fixes):
    """Count rows that are exact copies of an earlier row. They are KEPT."""
    seen, copies = set(), 0
    for row in rows:
        key = tuple((k, str(v)) for k, v in row.items() if k not in ignore)
        if key in seen:
            copies += 1
        seen.add(key)
    fixes.add(DUPLICATES_KEPT, copies)


def load_info(table, source_file, source_rows, rows, fixes, unknown_rows=0,
              has_unknown_row=False):
    """What goes into load_log for one table."""
    return {"table_name": table, "source_file": source_file,
            "source_rows": source_rows,
            "loaded_rows": len(rows) - (1 if has_unknown_row else 0),
            "unknown_key_rows": unknown_rows, "fixes": fixes}


# ============================================================== table definitions
class Table:
    """One gold table. The FIRST column is the primary key.
    columns      : list of (column name, MySQL type, plain-English comment)
    foreign_keys : list of (column, parent table) - parent's first column."""

    def __init__(self, name, comment, columns, foreign_keys=(), indexes=()):
        self.name = name
        self.comment = comment
        self.columns = columns
        self.foreign_keys = list(foreign_keys)
        self.indexes = list(indexes)

    @property
    def column_names(self):
        return [c[0] for c in self.columns]

    @property
    def primary_key(self):
        return self.columns[0][0]


CALENDAR = Table("dim_calendar", (
    "One row per day from 01-Apr-2024 to 31-Mar-2027, plus the Unknown row -1. "
    "Gives every date its calendar month, Indian financial year (Apr-Mar) and "
    "NOP sales month (21st to 20th). Every *_date_id in the facts points here."), [
    ("date_id", "INT NOT NULL", "Date key = yyyymmdd as a number (20260920 = 20-Sep-2026). -1 = unknown or not applicable date."),
    ("full_date", "DATE", "The calendar date. NULL only on the -1 row."),
    ("day_of_month", "TINYINT", "Day of the month, 1-31."),
    ("day_name", "VARCHAR(10)", "Day name, e.g. Monday."),
    ("day_of_week", "TINYINT", "Day of the week, 1 = Monday ... 7 = Sunday."),
    ("week_of_year", "TINYINT", "ISO week number, 1-53."),
    ("month_no", "TINYINT", "Calendar month number, 1 = January ... 12 = December."),
    ("month_name", "VARCHAR(10)", "Calendar month name, e.g. September."),
    ("month_short", "VARCHAR(3)", "Short calendar month name, e.g. Sep."),
    ("month_year", "VARCHAR(8)", "Calendar month label, e.g. 'Sep 2026' (1st to last day of the month)."),
    ("calendar_quarter", "TINYINT", "Calendar quarter 1-4 (1 = Jan-Mar)."),
    ("calendar_year", "SMALLINT", "Calendar year, e.g. 2026."),
    ("financial_year", "VARCHAR(4)", "Indian financial year (1-Apr to 31-Mar) as NOP writes it: '2627' = FY 2026-27 = 01-Apr-2026 to 31-Mar-2027."),
    ("financial_year_label", "VARCHAR(10)", "Financial year label, e.g. 'FY 2026-27'."),
    ("fiscal_period", "TINYINT", "Month number inside the financial year: 1 = April ... 12 = March."),
    ("fiscal_quarter", "TINYINT", "Quarter inside the financial year: 1 = Apr-Jun, 2 = Jul-Sep, 3 = Oct-Dec, 4 = Jan-Mar."),
    ("is_month_end", "CHAR(1)", "'Y' on the last day of a calendar month, else 'N'."),
    ("is_weekend", "CHAR(1)", "'Y' on Saturday and Sunday, else 'N'."),
    ("nop_sales_month", "VARCHAR(8)", "NOP sales month of this date, e.g. 'Oct 2026'. A NOP sales month runs from the 21st of the previous month to the 20th and is named after the month it ENDS in (21-Sep-2026 .. 20-Oct-2026 = 'Oct 2026')."),
    ("nop_sales_month_name", "VARCHAR(10)", "Month name of the NOP sales month, e.g. 'October'."),
    ("nop_sales_month_no", "TINYINT", "Calendar month number of the NOP sales month (10 for 'Oct 2026')."),
    ("nop_sales_year", "VARCHAR(4)", "Financial year of the NOP sales month, same style as financial_year: '2627' = NOP sales months Apr 2026 .. Mar 2027 (21-Mar-2026 .. 20-Mar-2027)."),
    ("nop_sales_period_no", "TINYINT", "Position of the NOP sales month in its NOP sales year: 1 = April ... 12 = March."),
    ("nop_sales_period_start", "DATE", "First day of the NOP sales month (the 21st of the previous month)."),
    ("nop_sales_period_end", "DATE", "Last day of the NOP sales month (the 20th)."),
], indexes=["full_date", "nop_sales_month", "month_year", "financial_year"])

CUSTOMERS = Table("dim_customers", (
    "Customers (dimension). One row per SAP customer from the Customer Master "
    "Report, plus customers that exist only in the client's Customer list sheet "
    "(no BP code yet), plus the Unknown row -1."), [
    ("customer_id", "INT NOT NULL", "Customer key. -1 = Unknown customer (code or name not found in the master)."),
    ("customer_code", "VARCHAR(20)", "SAP business-partner code (BP code), e.g. 'C0001'. NULL for sheet-only customers (source_system 'CLIENT_SHEET'). 'UNKNOWN' on the -1 row."),
    ("customer_name", "VARCHAR(255) NOT NULL", "Customer company name."),
    ("client_customer_code", "VARCHAR(20)", "The client's own customer code from the 'Customer list' sheet (e.g. '50001'), matched on BP code. NULL when the sheet gives none."),
    ("customer_group", "VARCHAR(50)", "SAP customer group: 'Local Customer', 'Foreign Customer' or 'Customers'."),
    ("type_of_business", "VARCHAR(50)", "SAP type of business, e.g. 'Company'."),
    ("billing_address", "VARCHAR(500)", "Bill-to street address (master column 'BUILDING/FLOOR/ROOM')."),
    ("city", "VARCHAR(100)", "Bill-to city."),
    ("zip_code", "VARCHAR(20)", "Bill-to ZIP / PIN code."),
    ("state", "VARCHAR(100)", "Bill-to state (Indian customers; NULL for foreign customers)."),
    ("country", "VARCHAR(100)", "Bill-to country in plain English, spelling corrected (e.g. 'United Arab Emirates')."),
    ("country_iso_code", "VARCHAR(3)", "ISO 3166 3-letter country code from the client's Country master, e.g. IND, JPN. NULL if the country is not in that master."),
    ("country_segment", "VARCHAR(30)", "Client's country segment for sales reporting, e.g. '1.JAPAN', '2.ASIA', '3.AMERICA', '4.EUROPE', '5.MIDDLE EAST'."),
    ("gstin", "VARCHAR(20)", "Customer's GST registration number (Indian customers)."),
    ("gst_type", "VARCHAR(50)", "GST registration type, e.g. 'Regular/TDS/ISD'."),
    ("pan_no", "VARCHAR(20)", "Customer's PAN (Indian income-tax id)."),
    ("mobile_phone", "VARCHAR(30)", "Contact mobile number."),
    ("email", "VARCHAR(150)", "Contact e-mail address."),
    ("accounts_receivable", "VARCHAR(100)", "Receivables (debtors) ledger: 'Sundry Debtors - India' or 'Sundry Debtors - Foreign'."),
    ("is_active", "CHAR(1)", "'Y' = active in SAP, 'N' = inactive. NULL for sheet-only customers."),
    ("source_system", "VARCHAR(20) NOT NULL", "Where the row comes from: 'CUSTOMER_MASTER' (SAP Customer Master Report) or 'CLIENT_SHEET' (only in the client's Customer list sheet, no BP code yet). 'UNKNOWN' on the -1 row."),
    ("is_current", "CHAR(1) NOT NULL", "'Y' = current version (always 'Y'; no history is kept)."),
], indexes=["customer_code", "customer_name"])

PRODUCTS = Table("dim_products", (
    "Products / items (dimension). One row per SAP item from the Item Master, "
    "with the client's product classification (PTC_NOPI / PCT_NOPJ sheets) "
    "joined on the foreign code, plus the Unknown row -1."), [
    ("product_id", "INT NOT NULL", "Product key. -1 = Unknown product (item code not found, or a line without item code such as a service charge)."),
    ("product_code", "VARCHAR(30) NOT NULL", "SAP item number, e.g. 'FG00001'. Prefix: FG = finished goods, RM = raw material, CO = consumables, CA = capital item. 'UNKNOWN' on the -1 row."),
    ("product_description", "VARCHAR(255)", "Item description from the SAP item master."),
    ("item_group", "VARCHAR(50)", "SAP item group: 'Finished goods', 'Raw material', 'Consumables' or 'Capital Item'."),
    ("foreign_code", "VARCHAR(50)", "Client's (NOP Japan) product code for the item. 'India - No Foreign Code' when SAP has none."),
    ("product_category", "VARCHAR(50)", "Client classification - category, e.g. 'Trochoid pumps'. From the PTC_NOPI / PCT_NOPJ row whose product code = foreign_code. NULL = not classified."),
    ("product_segment_code", "VARCHAR(20)", "Client classification - product segment code, e.g. 'L-01'."),
    ("product_segment_name", "VARCHAR(100)", "Client classification - product segment name, e.g. 'L-01 Trochoid'."),
    ("middle_class_code", "VARCHAR(20)", "Client classification - middle segment code, e.g. '194'."),
    ("middle_class_name", "VARCHAR(100)", "Client classification - middle segment name, e.g. 'Trochoid group'."),
    ("sales_agency", "VARCHAR(10)", "Which client sheet classified the item: 'NOP-I' (sheet PTC_NOPI) or 'NOPJ' (sheet PCT_NOPJ). NULL = not classified."),
    ("sap_segment", "VARCHAR(50)", "SAP item master 'Segment' (product family), e.g. 'Trochoid pumps'."),
    ("sap_product_segment", "VARCHAR(20)", "SAP item master 'Product Segment' code, e.g. 'L-06' (can differ from the client's product_segment_code)."),
    ("hsn_code", "VARCHAR(20)", "HSN code (Indian GST goods classification)."),
    ("amount", "DECIMAL(15,2)", "'Amount' from the SAP item master: the item's price per unit in INR as kept in SAP."),
    ("in_stock_qty", "DECIMAL(15,3)", "'In Stock' quantity when the item master was exported (for stock on a date use fact_stock_ledger)."),
    ("ordered_from_supplier_qty", "DECIMAL(15,3)", "'Order to Supplier' - quantity on open purchase orders."),
    ("ordered_by_customers_qty", "DECIMAL(15,3)", "'Order by Customer' - quantity on open customer orders."),
    ("minimum_inventory_qty", "DECIMAL(15,3)", "Minimum inventory level set in SAP (0 = none)."),
    ("lead_time_days", "SMALLINT", "Lead time in days. NULL when not set."),
    ("pricing_unit", "VARCHAR(20)", "SAP pricing unit, e.g. 'Manual'."),
    ("is_active", "CHAR(1)", "'Y' = active item, 'N' = inactive."),
    ("last_updated_on", "DATE", "Date the item record was last updated in SAP (master column 'Date of Udate')."),
], indexes=["product_code", "foreign_code"])

FX_RATES = Table("dim_fx_rates", (
    "INR -> JPY exchange rates (dimension). One row per monthly rate window "
    "(21st of the previous month to the 20th = one NOP sales month), plus the "
    "Unknown row -1. JPY value = INR value x exchange_rate."), [
    ("fx_rate_id", "INT NOT NULL", "Exchange-rate window key. -1 = Unknown (date outside every window)."),
    ("rate_month", "VARCHAR(8)", "Month the rate is for, written like dim_calendar.nop_sales_month, e.g. 'Oct 2026'."),
    ("start_date", "DATE", "First day the rate applies (the 21st of the previous month)."),
    ("end_date", "DATE", "Last day the rate applies (the 20th)."),
    ("from_currency", "VARCHAR(3)", "Currency converted from: 'INR'."),
    ("to_currency", "VARCHAR(3)", "Currency converted to: 'JPY'."),
    ("exchange_rate", "DECIMAL(12,6)", "Japanese yen for 1 Indian rupee in this window."),
    ("remarks", "VARCHAR(255)", "Remark from the rate file, e.g. 'Old Exchange Rate'."),
], indexes=["rate_month"])

SALES_PEOPLE = Table("dim_sales_people", (
    "Sales people (dimension). Distinct 'Sales Employee' names from the sales "
    "order and invoice files, plus the Unknown row -1."), [
    ("sales_person_id", "INT NOT NULL", "Sales person key. -1 = Unknown / not given."),
    ("sales_person_name", "VARCHAR(100) NOT NULL", "Name without title, e.g. 'Rahul Verma'."),
    ("name_with_title", "VARCHAR(110)", "Name as written in the files, e.g. 'Mr. Rahul Verma'."),
    ("designation", "VARCHAR(30)", "Job title: 'Sales Person'."),
    ("is_current", "CHAR(1) NOT NULL", "'Y' = current (always 'Y')."),
], indexes=["sales_person_name"])

TAX_CODES = Table("dim_tax_codes", (
    "GST tax codes used on sales orders (dimension), plus the Unknown row -1. "
    "Invoices carry their GST rates and amounts as columns instead."), [
    ("tax_code_id", "INT NOT NULL", "Tax code key. -1 = Unknown."),
    ("tax_code", "VARCHAR(20) NOT NULL", "Tax code from the sales order 'TAX Information', spaces removed, upper case: 'IGST18', 'CSGST18', 'IGST0'."),
    ("tax_type", "VARCHAR(20)", "'IGST' = inter-state GST; 'CSGST' = intra-state GST split half CGST + half SGST."),
    ("tax_rate", "DECIMAL(5,2)", "Total GST rate in percent, e.g. 18.00."),
    ("tax_description", "VARCHAR(100)", "Meaning in plain English."),
], indexes=["tax_code"])

STOCK_MOVEMENT_TYPES = Table("dim_stock_movement_types", (
    "Kinds of row in the stock ledger (fixed list, dimension). BALANCE rows are "
    "stock balances (Opening / Closing); MOVEMENT rows are stock movements whose "
    "type comes from the letters before the document number."), [
    ("movement_type_id", "INT NOT NULL", "Movement type key. -1 = Unknown document prefix."),
    ("movement_type", "VARCHAR(30) NOT NULL", "'Opening Balance', 'Closing balance', 'Purchase', 'Landed cost', 'COGS', 'Inventory transfer' or 'Production'."),
    ("row_kind", "VARCHAR(10) NOT NULL", "'BALANCE' = a stock balance row (never add it to movements); 'MOVEMENT' = a stock movement."),
    ("doc_prefixes", "VARCHAR(50)", "Document prefixes (letters before the number in fact_stock_ledger.document_no) that mean this type, e.g. 'PD, PU, PC'."),
    ("direction", "VARCHAR(10)", "Usual stock direction: 'IN', 'OUT', 'IN / OUT', or '-' for balances."),
])

SALES_ORDER_LINES = Table("fact_sales_order_lines", (
    "Sales order lines (fact). One row per line of the Sales Order Report, "
    "nothing dropped. Amounts in INR. SO numbers restart every financial year."), [
    ("sales_order_line_id", "INT NOT NULL", "Sales order line key, in file order."),
    ("source_row_no", "INT", "Row number ('#') in Sales Order Report.xlsx, for tracing."),
    ("order_date_id", "INT NOT NULL", "Order (posting) date -> dim_calendar.date_id. -1 = date missing or outside the calendar."),
    ("order_date", "DATE", "Order posting date (file column 'Posting Date')."),
    ("delivery_date_id", "INT NOT NULL", "Promised delivery date -> dim_calendar.date_id. -1 = missing / outside the calendar."),
    ("delivery_date", "DATE", "Promised delivery date."),
    ("customer_id", "INT NOT NULL", "-> dim_customers.customer_id (matched on the customer code). -1 = Unknown."),
    ("product_id", "INT NOT NULL", "-> dim_products.product_id (matched on the item number). -1 = no item number (service line) or item not in the master."),
    ("sales_person_id", "INT NOT NULL", "-> dim_sales_people.sales_person_id. -1 = Unknown."),
    ("tax_code_id", "INT NOT NULL", "-> dim_tax_codes.tax_code_id. -1 = Unknown."),
    ("fx_rate_id", "INT NOT NULL", "-> dim_fx_rates.fx_rate_id: the INR->JPY window holding the order date. -1 = order date before the first rate window (21-Dec-2024)."),
    ("so_number", "INT", "Sales order number. Numbers RESTART every financial year: identify an order by so_number + financial year of the order date, never by so_number alone."),
    ("customer_ref_no", "VARCHAR(50)", "Customer's purchase-order reference, e.g. 'PO/4256/24-25'."),
    ("status", "VARCHAR(20)", "'Open' = ordered, not yet (fully) invoiced; 'Closed' = completed; 'Canceled' = cancelled."),
    ("item_description", "VARCHAR(255)", "Item description on the line (NULL on service lines)."),
    ("hsn_code", "VARCHAR(20)", "HSN code on the line (NULL on service lines)."),
    ("quantity", "DECIMAL(15,3)", "Ordered quantity (0 on service lines)."),
    ("unit_price", "DECIMAL(15,2)", "Price per unit in INR, before discount."),
    ("discount_pct", "DECIMAL(6,2)", "Line discount in percent."),
    ("total_amount", "DECIMAL(15,2)", "Line value in INR after discount, before GST (file 'Total (LC)'). Service lines carry the charge here with quantity 0."),
    ("tax_total", "DECIMAL(15,2)", "GST on the line in INR."),
    ("payment_terms", "VARCHAR(50)", "Payment terms, e.g. 'Net-30', '100% ADVANCE'."),
    ("contact_person", "VARCHAR(100)", "Customer contact person for the order."),
    ("contact_number", "VARCHAR(30)", "Customer contact phone number."),
    ("bill_to_address", "VARCHAR(500)", "Bill-to address on the order."),
    ("ship_to_address", "VARCHAR(500)", "Ship-to address on the order."),
    ("remarks", "VARCHAR(500)", "Remarks on the order line."),
    ("src_customer_code", "VARCHAR(20)", "Customer code exactly as in the file (cleaned), to trace -1 rows."),
    ("src_customer_name", "VARCHAR(255)", "Customer name as in the file, for tracing (use dim_customers.customer_name in reports)."),
    ("src_product_code", "VARCHAR(30)", "Item number as in the file (NULL on service lines), to trace -1 rows."),
    ("src_sales_person", "VARCHAR(110)", "Sales employee as written in the file, for tracing."),
    ("src_tax_code", "VARCHAR(30)", "Tax information as written in the file, e.g. 'IGST 18', for tracing."),
], foreign_keys=[("order_date_id", "dim_calendar"), ("delivery_date_id", "dim_calendar"),
                 ("customer_id", "dim_customers"), ("product_id", "dim_products"),
                 ("sales_person_id", "dim_sales_people"), ("tax_code_id", "dim_tax_codes"),
                 ("fx_rate_id", "dim_fx_rates")],
   indexes=["so_number", "status"])

INVOICE_LINES = Table("fact_invoice_lines", (
    "Invoice lines and credit / debit note lines (fact). One row per line of "
    "Sales Invoice Details (document_type 'INVOICE') plus one row per line of "
    "GSTR1_Credit_Debit_Note.csv (document_type 'CREDIT_NOTE'). Amounts in INR. "
    "Net sales = SUM(net_taxable_value) (credit notes are negative there)."), [
    ("invoice_line_id", "INT NOT NULL", "Invoice line key: invoice lines first (file order), then note lines."),
    ("source_format", "VARCHAR(20) NOT NULL", "Source file: 'INVOICE_DETAILS' = Sales Invoice Details.xlsx; 'CREDIT_NOTE' / 'DEBIT_NOTE' = GSTR1_Credit_Debit_Note.csv."),
    ("document_type", "VARCHAR(15) NOT NULL", "'INVOICE', 'CREDIT_NOTE' (reduces sales, negative net_* values) or 'DEBIT_NOTE' (positive)."),
    ("source_row_no", "INT", "Row number in the source file ('#' for invoices, data line number for notes), for tracing."),
    ("invoice_date_id", "INT NOT NULL", "-> dim_calendar.date_id of invoice_date (for notes: the NOTE date). -1 = missing / outside the calendar."),
    ("invoice_date", "DATE", "Invoice date; for credit / debit notes the note date (so a note reduces sales in the month it is issued)."),
    ("customer_id", "INT NOT NULL", "-> dim_customers.customer_id. Found via the sales order (SO number + financial year), else the billing name; notes use the original invoice's customer. -1 = Unknown."),
    ("product_id", "INT NOT NULL", "-> dim_products.product_id (item code; for notes the original invoice line with the same description). -1 = no item (service line) or not found."),
    ("sales_person_id", "INT NOT NULL", "-> dim_sales_people.sales_person_id (notes: the original invoice's sales person). -1 = Unknown."),
    ("fx_rate_id", "INT NOT NULL", "-> dim_fx_rates.fx_rate_id: the INR->JPY window holding invoice_date. -1 = outside every window."),
    ("invoice_number", "VARCHAR(30)", "Invoice number, e.g. 'NOPI/D/2526/169'. For notes: the ORIGINAL invoice the note corrects."),
    ("invoice_series", "VARCHAR(5)", "Document series: D = domestic, E = export, S = service, DU = duplicate (from the invoice number); CN = credit note, DN = debit note."),
    ("transaction_type", "VARCHAR(30)", "Transaction type from the invoice file, e.g. 'GST Tax Invoice'. NULL on note rows."),
    ("so_number", "INT", "Sales order number the line was invoiced from (notes: from the original invoice). Restarts every financial year - pair it with so_date."),
    ("so_date", "DATE", "Date of that sales order."),
    ("customer_ref_no", "VARCHAR(50)", "Customer's purchase-order reference."),
    ("customer_type", "VARCHAR(10)", "'OEM' or 'AFT' (after-market); often blank."),
    ("territory", "VARCHAR(50)", "Sales territory, e.g. 'South Region - 1', 'Export'."),
    ("sale_type", "VARCHAR(10)", "'Domestic', 'Export' or 'Service' (file 'Type Export/Domestic'; notes: from the original invoice)."),
    ("customer_billing_name", "VARCHAR(255)", "Bill-to customer name as on the document."),
    ("customer_billing_city", "VARCHAR(100)", "Bill-to city as on the document."),
    ("place_of_supply_state", "VARCHAR(10)", "GST place of supply, 2-letter state code, e.g. 'KA'. NULL for exports."),
    ("country", "VARCHAR(100)", "Bill-to country (spelling corrected; notes: from the original invoice)."),
    ("customer_billing_gstin", "VARCHAR(20)", "Customer's billing GSTIN."),
    ("customer_shipping_gstin", "VARCHAR(20)", "Customer's shipping GSTIN."),
    ("customer_billing_address", "VARCHAR(500)", "Bill-to address as on the document."),
    ("customer_shipping_address", "VARCHAR(500)", "Ship-to address as on the document."),
    ("item_type", "VARCHAR(1)", "'G' = goods, 'S' = service."),
    ("src_product_code", "VARCHAR(30)", "SAP item code as in the invoice file ('Part Code SAP Code'), to trace -1 rows. NULL on service lines and on note rows (the note file has no item code)."),
    ("foreign_code", "VARCHAR(50)", "Client's product code as on the invoice line ('Item Foreign Code'); NULL when the item has none."),
    ("item_description", "VARCHAR(255)", "Item description as on the document."),
    ("hsn_code", "VARCHAR(20)", "HSN code (goods) as on the document."),
    ("sac_code", "VARCHAR(20)", "SAC code (services) as on the document."),
    ("uom", "VARCHAR(20)", "Unit of measure as in SAP, e.g. 'Manual'."),
    ("quantity", "DECIMAL(15,3)", "Quantity as printed on the document (always positive; see net_quantity)."),
    ("unit_price", "DECIMAL(15,2)", "Price per unit in INR."),
    ("taxable_value", "DECIMAL(15,2)", "Taxable value in INR, before GST and freight, as printed (always positive; see net_taxable_value)."),
    ("freight_amount", "DECIMAL(15,2)", "Freight / packing charged on the line, INR (NULL on note rows). Sales value = net_taxable_value + freight_amount."),
    ("freight_detail", "VARCHAR(50)", "What the freight amount is: 'Freight' or 'Packing Charges'."),
    ("freight_sac_code", "VARCHAR(20)", "SAC code of the freight charge."),
    ("igst_rate", "DECIMAL(5,2)", "IGST rate in percent (inter-state GST)."),
    ("igst_amount", "DECIMAL(15,2)", "IGST amount in INR."),
    ("cgst_rate", "DECIMAL(5,2)", "CGST rate in percent (intra-state, central half)."),
    ("cgst_amount", "DECIMAL(15,2)", "CGST amount in INR."),
    ("sgst_rate", "DECIMAL(5,2)", "SGST rate in percent (intra-state, state half)."),
    ("sgst_amount", "DECIMAL(15,2)", "SGST amount in INR."),
    ("cess_rate", "DECIMAL(5,2)", "GST cess rate in percent (note rows only; NULL on invoice rows)."),
    ("cess_amount", "DECIMAL(15,2)", "GST cess amount in INR (note rows only)."),
    ("line_total_incl_gst", "DECIMAL(15,2)", "Line total in INR including GST and freight, as printed (always positive)."),
    ("doc_round_off", "DECIMAL(15,2)", "Document-level rounding in INR."),
    ("invoice_total_incl_gst", "DECIMAL(15,2)", "Total of the WHOLE invoice incl. GST, repeated on every line of the invoice - do not SUM it over lines. NULL on note rows."),
    ("invoice_discount_pct", "DECIMAL(6,2)", "Invoice-level discount in percent."),
    ("src_sales_person", "VARCHAR(110)", "Sales employee as written in the invoice file, for tracing (NULL on note rows)."),
    ("remarks", "VARCHAR(500)", "Remarks on the invoice, e.g. 'Based On Sales Orders 182.'."),
    ("note_number", "VARCHAR(30)", "Credit / debit note number, e.g. 'NOPI/CN/2526/1' (series prefix + suffix + note no.). NULL on invoice rows."),
    ("note_series", "VARCHAR(20)", "Note series, e.g. 'CN/2526' (CN + financial year). NULL on invoice rows."),
    ("note_date_id", "INT NOT NULL", "-> dim_calendar.date_id of note_date. -1 on invoice rows (not a note) or unknown."),
    ("note_date", "DATE", "Date the credit / debit note was issued. NULL on invoice rows."),
    ("note_value", "DECIMAL(15,2)", "Total value of the note in INR incl. GST, as printed (positive). NULL on invoice rows."),
    ("original_invoice_number", "VARCHAR(30)", "Invoice the note corrects. NULL on invoice rows."),
    ("original_invoice_date", "DATE", "Date of the invoice the note corrects. NULL on invoice rows."),
    ("issue_reason", "VARCHAR(255)", "Reason given for the note, e.g. 'Rate difference / return - ...'."),
    ("net_quantity", "DECIMAL(15,3)", "Signed quantity: + for invoices and debit notes, - for credit notes."),
    ("net_taxable_value", "DECIMAL(15,2)", "Signed taxable value in INR: + for invoices and debit notes, - for credit notes. SUM(net_taxable_value) = net sales before GST and freight."),
    ("net_line_total_incl_gst", "DECIMAL(15,2)", "Signed line total incl. GST in INR (- for credit notes)."),
], foreign_keys=[("invoice_date_id", "dim_calendar"), ("note_date_id", "dim_calendar"),
                 ("customer_id", "dim_customers"), ("product_id", "dim_products"),
                 ("sales_person_id", "dim_sales_people"), ("fx_rate_id", "dim_fx_rates")],
   indexes=["invoice_number", "so_number", "document_type"])

STOCK_LEDGER = Table("fact_stock_ledger", (
    "Stock ledger (fact) from the Inventory Audit Report 'as on DDMMYY'. Per "
    "item: a Closing balance row, an Opening Balance row, then the movements. "
    "Never SUM every row: stock value on a date = SUM(cumulative_value) of the "
    "'Closing balance' rows of that report_date."), [
    ("stock_ledger_id", "INT NOT NULL", "Stock ledger row key, in file order."),
    ("source_row_no", "INT", "Row number ('#') in the inventory file, for tracing."),
    ("report_date_id", "INT NOT NULL", "-> dim_calendar.date_id of report_date. -1 = unknown."),
    ("report_date", "DATE", "Snapshot date, from the file name 'as on DDMMYY' (200926 = 20-Sep-2026)."),
    ("product_id", "INT NOT NULL", "-> dim_products.product_id (matched on the item number). -1 = item not in the master."),
    ("movement_type_id", "INT NOT NULL", "-> dim_stock_movement_types.movement_type_id. Blank document = Closing balance, 'Opening Balance' = Opening Balance, else the letters before the document number decide."),
    ("posting_date_id", "INT NOT NULL", "-> dim_calendar.date_id of posting_date. -1 on balance rows (no posting date) or unknown."),
    ("posting_date", "DATE", "Posting date of the movement. NULL on balance rows."),
    ("system_date", "DATE", "Date the movement was entered in SAP. NULL on balance rows."),
    ("src_product_code", "VARCHAR(30)", "Item number as in the file, filled down from the item's first row, to trace -1 rows."),
    ("item_description", "VARCHAR(255)", "Item description (filled down like the item number)."),
    ("document_no", "VARCHAR(50)", "SAP document, e.g. 'PD 578' (prefix + number); 'Opening Balance' on opening rows; NULL on closing-balance rows."),
    ("doc_row", "INT", "Line number inside the SAP document."),
    ("warehouse_code", "VARCHAR(10)", "SAP warehouse code, e.g. '03'. NULL on balance rows."),
    ("quantity", "DECIMAL(15,3)", "Movement quantity: + = into stock, - = out of stock. NULL on balance rows."),
    ("unit_cost", "DECIMAL(15,4)", "Cost per unit in INR."),
    ("transaction_value", "DECIMAL(15,2)", "Value of the movement in INR (+ in, - out); 0 on balance rows."),
    ("cumulative_qty", "DECIMAL(15,3)", "Running stock quantity after this row (on balance rows: the balance)."),
    ("cumulative_value", "DECIMAL(15,2)", "Running stock value in INR after this row (on balance rows: the balance value)."),
], foreign_keys=[("report_date_id", "dim_calendar"), ("posting_date_id", "dim_calendar"),
                 ("product_id", "dim_products"), ("movement_type_id", "dim_stock_movement_types")],
   indexes=["report_date"])

LOAD_LOG = Table("load_log", (
    "Load history: one row per gold table per run of load_gold.py (run 1 = the "
    "FULL load from inputdata/, then one run per INCREMENTAL batch). Rows read, "
    "inserted / updated / skipped, rows with an Unknown (-1) key, every cleaning "
    "fix. A full load starts the history again."), [
    ("load_log_id", "INT NOT NULL", "Log row key."),
    ("run_id", "INT NOT NULL", "Load run number: 1 = the full load; each incremental batch run adds 1. The latest run = MAX(run_id)."),
    ("run_type", "VARCHAR(12) NOT NULL", "'FULL' = every table dropped and rebuilt from inputdata/; 'INCREMENTAL' = one batch folder merged into the existing tables (nothing dropped)."),
    ("batch_name", "VARCHAR(100)", "Folder the run read: 'inputdata' for the full load, e.g. 'batch_001' for a batch."),
    ("table_name", "VARCHAR(64) NOT NULL", "Gold table this row is about."),
    ("source_file", "VARCHAR(255)", "Input file(s) the table was built from."),
    ("source_rows", "INT", "Data rows read from the source file(s), empty lines not counted (for dim_calendar: days generated; dim_sales_people / dim_tax_codes: distinct names / codes found)."),
    ("loaded_rows", "INT", "FULL run: rows loaded, not counting the -1 Unknown row. INCREMENTAL run: rows written by the run = inserted_rows + updated_rows."),
    ("inserted_rows", "INT", "Rows added by this run (business key not in the table before)."),
    ("updated_rows", "INT", "Rows already in the table (same business key) whose values changed: updated in place, same id. 0 on a FULL run."),
    ("skipped_rows", "INT", "Rows read but not written: already in the table with the same values, or exact duplicate lines inside the batch (see fixes). 0 on a FULL run. For facts: source_rows = inserted_rows + updated_rows + skipped_rows."),
    ("table_rows_after", "INT", "Rows in the table after this run, not counting the -1 Unknown row."),
    ("unknown_key_rows", "INT", "Fact rows of this run where a key that should have matched fell back to -1 (details in fixes)."),
    ("fixes", "TEXT", "Every cleaning fix with its count, '; ' separated. Rows are never dropped."),
    ("loaded_at", "DATETIME NOT NULL", "When this run loaded the table."),
])

# creation order: dimensions first, facts after, log last (drops go in reverse)
ALL_TABLES = [CALENDAR, CUSTOMERS, PRODUCTS, FX_RATES, SALES_PEOPLE, TAX_CODES,
              STOCK_MOVEMENT_TYPES, SALES_ORDER_LINES, INVOICE_LINES,
              STOCK_LEDGER, LOAD_LOG]


# ============================================================== dimensions
def build_calendar():
    """One row per day 01-Apr-2024 .. 31-Mar-2027 with financial year and NOP
    sales month (21st of the previous month .. 20th, named after the END month)."""
    rows = [{"date_id": UNKNOWN, "day_name": "Unknown", "month_name": "Unknown",
             "month_short": "Unk", "month_year": "Unknown", "financial_year": "Unk",
             "financial_year_label": "Unknown", "nop_sales_month": "Unknown",
             "nop_sales_month_name": "Unknown", "nop_sales_year": "Unk"}]
    day = CALENDAR_START
    while day <= CALENDAR_END:
        fy = fy_start_year(day)
        # NOP sales month: day 1-20 belongs to this month, day 21+ to the next month
        if day.day <= 20:
            end_year, end_month = day.year, day.month
        elif day.month == 12:
            end_year, end_month = day.year + 1, 1
        else:
            end_year, end_month = day.year, day.month + 1
        period_end = date(end_year, end_month, 20)
        period_start = (period_end.replace(day=1) - timedelta(days=1)).replace(day=21)
        nop_fy = end_year if end_month >= 4 else end_year - 1
        rows.append({
            "date_id": date_id(day), "full_date": day,
            "day_of_month": day.day, "day_name": day.strftime("%A"),
            "day_of_week": day.isoweekday(), "week_of_year": day.isocalendar()[1],
            "month_no": day.month, "month_name": day.strftime("%B"),
            "month_short": day.strftime("%b"), "month_year": day.strftime("%b %Y"),
            "calendar_quarter": (day.month - 1) // 3 + 1, "calendar_year": day.year,
            "financial_year": f"{fy % 100:02d}{(fy + 1) % 100:02d}",
            "financial_year_label": f"FY {fy}-{(fy + 1) % 100:02d}",
            "fiscal_period": (day.month - 4) % 12 + 1,
            "fiscal_quarter": ((day.month - 4) % 12) // 3 + 1,
            "is_month_end": "Y" if (day + timedelta(days=1)).day == 1 else "N",
            "is_weekend": "Y" if day.isoweekday() >= 6 else "N",
            "nop_sales_month": period_end.strftime("%b %Y"),
            "nop_sales_month_name": period_end.strftime("%B"),
            "nop_sales_month_no": end_month,
            "nop_sales_year": f"{nop_fy % 100:02d}{(nop_fy + 1) % 100:02d}",
            "nop_sales_period_no": (end_month - 4) % 12 + 1,
            "nop_sales_period_start": period_start,
            "nop_sales_period_end": period_end,
        })
        day += timedelta(days=1)
    info = load_info("dim_calendar", "generated (no file)", len(rows) - 1, rows,
                     Fixes(), has_unknown_row=True)
    return rows, info


def build_customers(src, sheet_only=True):
    """Customer Master rows + client codes, country ISO / segment from the
    client sheets + sheet-only customers (Customer list rows without BP code;
    left out when sheet_only is False: a batch without the client file)."""
    fixes = Fixes()
    master = records(read_excel(src.path(CUSTOMER_FILE)), fixes)
    client_file = src.reference_path(CLIENT_FILE)
    client_list = records(read_excel(client_file, "Customer list", header_row=3), fixes)
    countries = records(read_excel(client_file, "Country master", header_row=3), fixes)

    # client's Country master: formal name -> ISO code, ISO code -> segment
    iso_by_name, iso_segment = {}, {}
    for c in countries:
        iso = clean_code(c["Code"], fixes)
        iso_by_name[name_key(clean_text(c["Country Name"], fixes)).lower()] = iso
        iso_segment[iso] = clean_text(list(c.values())[4], fixes)   # 5th column = segment

    def country_iso(country):
        if not country:
            return None
        key = name_key(country).lower()
        return iso_by_name.get(key) or COUNTRY_ISO_ALIASES.get(key)

    # BP code -> client's own customer code (first sheet row wins)
    client_code_by_bp = {}
    for c in client_list:
        bp = clean_code(c["BP_CODE"], fixes)
        if bp and bp not in client_code_by_bp:
            client_code_by_bp[bp] = clean_code(c["Customer Code"], fixes)

    rows = [{"customer_id": UNKNOWN, "customer_code": "UNKNOWN",
             "customer_name": "Unknown customer", "source_system": "UNKNOWN",
             "is_current": "Y"}]
    for r in master:
        country = clean_country(r["Bill-to Country"], fixes)
        iso = country_iso(country)
        if country and not iso:
            fixes.add("country not in the client's Country master -> ISO/segment NULL")
        code = clean_code(r["CUSTOMER CODE"], fixes)
        active = clean_yes_no(r["ACTIVE"], fixes)
        inactive = clean_yes_no(r["INACTIVE"], Fixes())    # only checked, not stored
        if active and inactive and active == inactive:
            fixes.add("ACTIVE and INACTIVE contradict (ACTIVE kept)")
        rows.append({
            "customer_id": len(rows), "customer_code": code,
            "customer_name": clean_text(r["CUSTOMER NAME"], fixes),
            "client_customer_code": client_code_by_bp.get(code),
            "customer_group": clean_text(r["CUSTOMER GROUP"], fixes),
            "type_of_business": clean_text(r["TYPE OF BUSINESS"], fixes),
            "billing_address": clean_text(r["BUILDING/FLOOR/ROOM"], fixes),
            "city": clean_text(r["Bill-to City"], fixes),
            "zip_code": clean_text(r["ZIP CODE"], fixes),
            "state": clean_text(r["STATE"], fixes),
            "country": country, "country_iso_code": iso,
            "country_segment": iso_segment.get(iso),
            "gstin": clean_code(r["GSTIN"], fixes),
            "gst_type": clean_text(r["GST TYPE"], fixes),
            "pan_no": clean_code(r["PAN NO."], fixes),
            "mobile_phone": clean_text(r["MOBILE PHONE"], fixes),
            "email": clean_text(r["E-MAIL"], fixes),
            "accounts_receivable": clean_text(r["ACCOUNTS RECEIVABLE"], fixes),
            "is_active": active, "source_system": "CUSTOMER_MASTER", "is_current": "Y",
        })
    count_exact_duplicates(rows, {"customer_id"}, fixes)
    codes = [r["customer_code"] for r in rows if r["customer_code"]]
    fixes.add("duplicate customer code (first row used for matching)", len(codes) - len(set(codes)))

    # Customer list rows without a BP code: same name as a master customer ->
    # that customer (no duplicate row); otherwise a sheet-only customer row
    master_names = {name_key(r["customer_name"]) for r in rows[1:]}
    master_codes = set(codes)
    for c in (client_list if sheet_only else []):
        bp = clean_code(c["BP_CODE"], fixes)
        name = clean_text(c["Customer Name"], fixes)
        if bp:
            if bp not in master_codes:
                fixes.add("Customer list BP_CODE not in the Customer Master (ignored)")
            continue
        if not name:
            continue
        if name_key(name) in master_names:
            fixes.add("Customer list row without BP_CODE = same name as a master customer (no extra row)")
            continue
        rows.append({"customer_id": len(rows), "customer_code": None,
                     "customer_name": name,
                     "client_customer_code": clean_code(c["Customer Code"], fixes),
                     "source_system": "CLIENT_SHEET", "is_current": "Y"})
        fixes.add("sheet-only customer added from Customer list (source_system CLIENT_SHEET)")
    info = load_info("dim_customers", f"{CUSTOMER_FILE} + {CLIENT_FILE} (Customer list, Country master)",
                     len(master), rows, fixes, has_unknown_row=True)
    return rows, info


def build_products(src):
    """Item Master rows + client classification (PTC_NOPI / PCT_NOPJ) by foreign code."""
    fixes = Fixes()
    items = records(read_excel(src.path(ITEM_FILE), "Item Lists"), fixes)

    # client classification: product code -> classification columns
    classification = {}
    for sheet in ["PTC_NOPI", "PCT_NOPJ"]:
        df = read_excel(src.reference_path(CLIENT_FILE), sheet, header_row=5)
        for r in records(df, fixes):
            v = list(r.values())    # agency, code, name, category, seg cd, seg, middle cd, middle
            code = clean_code(v[1], fixes)
            if not code:
                continue
            if code in classification:
                fixes.add("product code in both client sheets (first kept)")
                continue
            classification[code] = {
                "sales_agency": clean_text(v[0], fixes),
                "product_category": clean_text(v[3], fixes),
                "product_segment_code": clean_code(v[4], fixes),
                "product_segment_name": clean_text(v[5], fixes),
                "middle_class_code": clean_code(v[6], fixes),
                "middle_class_name": clean_text(v[7], fixes),
            }

    rows = [{"product_id": UNKNOWN, "product_code": "UNKNOWN",
             "product_description": "Unknown product (code not found, or a line without item code)"}]
    for r in items:
        foreign = clean_code(r["foreign Code"], fixes)
        found = None
        if foreign:
            found = classification.get(foreign)
            # SAP sometimes adds '-I' (India) to the client's code
            if found is None and foreign.endswith("-I"):
                found = classification.get(foreign[:-2])
            if found is None:
                fixes.add("foreign code not in PTC_NOPI / PCT_NOPJ -> classification blank")
        else:
            foreign = NO_FOREIGN_CODE
            fixes.add(f"blank foreign code -> '{NO_FOREIGN_CODE}'")
        row = {
            "product_id": len(rows),
            "product_code": clean_code(r["Item No."], fixes),
            "product_description": clean_text(r["Item Description"], fixes),
            "item_group": clean_text(r["Item Group"], fixes),
            "foreign_code": foreign,
            "sap_segment": clean_text(r["Segment"], fixes),
            "sap_product_segment": clean_code(r["Product Segment"], fixes),
            "hsn_code": clean_code(r["HSN Code"], fixes),
            "amount": clean_number(r["Amount"], fixes),
            "in_stock_qty": clean_number(r["In Stock"], fixes),
            "ordered_from_supplier_qty": clean_number(r["Order to Supllier"], fixes),
            "ordered_by_customers_qty": clean_number(r["Order by Customer"], fixes),
            "minimum_inventory_qty": clean_number(r["Minimum Inventory"], fixes),
            "lead_time_days": clean_int(r["Lead Time"], fixes),
            "pricing_unit": clean_text(r["Pricing unit"], fixes),
            "is_active": clean_yes_no(r["Active"], fixes),
            "last_updated_on": clean_date(r["Date of Udate"], "%d/%m/%y", fixes),
        }
        row.update(found or {})
        rows.append(row)
    count_exact_duplicates(rows, {"product_id"}, fixes)
    codes = [r["product_code"] for r in rows]
    fixes.add("duplicate item number (first row used for matching)", len(codes) - len(set(codes)))
    info = load_info("dim_products", f"{ITEM_FILE} + {CLIENT_FILE} (PTC_NOPI, PCT_NOPJ)",
                     len(items), rows, fixes, has_unknown_row=True)
    return rows, info


def build_fx_rates(src):
    """Monthly INR -> JPY rate windows (21st .. 20th)."""
    fixes = Fixes()
    source = records(read_excel(src.path(FX_FILE), "INR to JPY", header_row=4), fixes)
    windows = []
    for r in source:
        month = clean_text(r["Rate Month"], fixes)
        month_label = rate_month_label(month, fixes)
        start = clean_date(r["Start Date"], "%d/%m/%Y", fixes)
        end = clean_date(r["End Date"], "%d/%m/%Y", fixes)
        if start and end and (start.day != 21 or end.day != 20):
            fixes.add("rate window not 21st..20th (kept as given)")
        rate = clean_number(r["Exchange Rate (1 INR = ? JPY)"], fixes)
        if rate is None:
            fixes.add("missing exchange rate (kept as NULL)")
        windows.append({"rate_month": month_label, "start_date": start, "end_date": end,
                        "from_currency": clean_code(r["From Currency"], fixes),
                        "to_currency": clean_code(r["To Currency"], fixes),
                        "exchange_rate": rate,
                        "remarks": clean_text(r["Remarks"], fixes)})
    windows.sort(key=lambda w: (w["start_date"] or date.max))
    rows = [{"fx_rate_id": UNKNOWN, "rate_month": "Unknown", "from_currency": "INR",
             "to_currency": "JPY", "remarks": "Unknown - date outside every rate window"}]
    for w in windows:
        rows.append({"fx_rate_id": len(rows), **w})
    count_exact_duplicates(rows, {"fx_rate_id"}, fixes)
    info = load_info("dim_fx_rates", FX_FILE, len(source), rows, fixes, has_unknown_row=True)
    return rows, info


def build_sales_people(sales_orders_raw, invoices_raw):
    """Distinct 'Sales Employee' names from the sales order and invoice files."""
    fixes = Fixes()
    forms = {}                  # matching key -> Counter of the ways it is written
    for r in sales_orders_raw + invoices_raw:
        written = clean_text(r.get("Sales Employee"), fixes)
        if written:
            forms.setdefault(person_key(written), Counter())[written] += 1
    # the way a person is written most often ('Mr. Rahul Verma', not 'RAHUL VERMA');
    # a tie keeps the form seen first
    names = {key: counts.most_common(1)[0][0] for key, counts in forms.items()}
    fixes.add("sales person written in other ways (matched without title / case / spaces)",
              sum(len(counts) - 1 for counts in forms.values()))
    rows = [{"sales_person_id": UNKNOWN, "sales_person_name": "Unknown",
             "designation": None, "is_current": "Y"}]
    for written in sorted(names.values(), key=lambda n: person_key(n)):
        rows.append({"sales_person_id": len(rows), "sales_person_name": strip_title(written),
                     "name_with_title": written, "designation": "Sales Person",
                     "is_current": "Y"})
    info = load_info("dim_sales_people", f"{SALES_ORDER_FILE} + {INVOICE_FILE} (Sales Employee)",
                     len(names), rows, fixes, has_unknown_row=True)
    return rows, info


def build_tax_codes(sales_orders_raw):
    """Distinct tax codes from the sales orders: 'IGST 18' -> IGST18 / IGST / 18."""
    fixes = Fixes()
    codes = {}
    for r in sales_orders_raw:
        written = clean_text(r["TAX Information"], fixes)
        if written:
            codes.setdefault(tax_key(written), set()).add(written)
    rows = [{"tax_code_id": UNKNOWN, "tax_code": "UNKNOWN", "tax_type": "Unknown",
             "tax_description": "Unknown tax code"}]
    for code in sorted(codes):
        if any(w != code for w in codes[code]):
            fixes.add("tax code spaces removed / upper-cased ('IGST 18' -> 'IGST18')")
        match = re.fullmatch(r"([A-Z]+)(\d+(?:\.\d+)?)", code)
        tax_type, rate = (match.group(1), float(match.group(2))) if match else ("Compound", None)
        if tax_type == "IGST":
            meaning = f"IGST {rate:g}% - inter-state GST"
        elif tax_type == "CSGST":
            meaning = f"CGST {rate / 2:g}% + SGST {rate / 2:g}% = {rate:g}% - intra-state GST"
        else:
            meaning = f"{code} - compound / unrecognised code (rate not guessed)"
        rows.append({"tax_code_id": len(rows), "tax_code": code, "tax_type": tax_type,
                     "tax_rate": rate, "tax_description": meaning})
    info = load_info("dim_tax_codes", f"{SALES_ORDER_FILE} (TAX Information)", len(codes),
                     rows, fixes, has_unknown_row=True)
    return rows, info


def build_stock_movement_types():
    """Fixed list (no source file) - NOP's real document-prefix map."""
    rows = [{"movement_type_id": i, "movement_type": name, "row_kind": kind,
             "doc_prefixes": prefixes, "direction": direction}
            for i, name, kind, prefixes, direction in MOVEMENT_TYPES]
    info = load_info("dim_stock_movement_types", "fixed list in load_gold.py",
                     len(rows) - 1, rows, Fixes(), has_unknown_row=True)
    return rows, info


# ============================================================== lookups for the facts
def make_lookups(customers, products, fx_rates, sales_people, tax_codes):
    """Business value -> dimension id maps used by the fact builders."""
    def first_wins(pairs):
        out = {}
        for key, value in pairs:
            if key and key not in out:
                out[key] = value
        return out

    def unique_only(pairs):
        """Key -> id only when the key points at exactly ONE id (never guess)."""
        seen = {}
        for key, value in pairs:
            if key:
                seen.setdefault(key, set()).add(value)
        return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}

    real_customers = [c for c in customers if c["customer_id"] != UNKNOWN]
    real_products = [p for p in products if p["product_id"] != UNKNOWN]
    return {
        "customer_by_code": first_wins((c["customer_code"], c["customer_id"]) for c in real_customers),
        "customer_by_name": unique_only((name_key(c["customer_name"]), c["customer_id"]) for c in real_customers),
        "product_by_code": first_wins((p["product_code"], p["product_id"]) for p in real_products),
        "product_by_description": unique_only((name_key(p["product_description"]), p["product_id"]) for p in real_products),
        "sales_person": {person_key(s["name_with_title"]): s["sales_person_id"]
                         for s in sales_people if s["sales_person_id"] != UNKNOWN},
        "tax_code": {t["tax_code"]: t["tax_code_id"] for t in tax_codes if t["tax_code_id"] != UNKNOWN},
        "fx_windows": [(f["fx_rate_id"], f["start_date"], f["end_date"]) for f in fx_rates
                       if f["fx_rate_id"] != UNKNOWN and f["start_date"] and f["end_date"]],
    }


def fx_rate_id(day, lookups):
    """The exchange-rate window holding this date; none -> -1."""
    if day is None:
        return UNKNOWN
    for window_id, start, end in lookups["fx_windows"]:
        if start <= day <= end:
            return window_id
    return UNKNOWN


def count_unknown_keys(rows, key_columns, fixes, reasons, skip=None):
    """Count rows whose key fell back to -1, per key, into fixes.
    skip(row, column) -> True when -1 means 'not applicable' for that row."""
    bad_rows = 0
    for row in rows:
        bad = [c for c in key_columns if row[c] == UNKNOWN and not (skip and skip(row, c))]
        for c in bad:
            fixes.add(f"{c} -> -1 ({reasons.get(c, 'not found')})")
        bad_rows += 1 if bad else 0
    return bad_rows


# ============================================================== facts
def build_sales_order_lines(source, lookups, fixes, batch=False):
    """One row per Sales Order Report line; keys looked up, never dropped.
    batch: exact duplicate lines are skipped (a line sent twice), not kept."""
    rows = []
    for r in source:
        order_date = clean_date(r["Posting Date"], "%d/%m/%y", fixes)
        delivery_date = clean_date(r["Delivery Date"], "%d/%m/%y", fixes)
        customer_code = clean_code(r["Customer Code"], fixes)
        product_code = clean_code(r["Item No"], fixes)
        sales_person = clean_text(r["Sales Employee"], fixes)
        tax_written = clean_text(r["TAX Information"], fixes)
        status = clean_status(r["Status"], fixes)
        terms = clean_payment_terms(r["Payment Terms"], fixes)
        rows.append({
            "sales_order_line_id": len(rows) + 1,
            "source_row_no": clean_int(r["#"], fixes),
            "order_date_id": date_id(order_date), "order_date": order_date,
            "delivery_date_id": date_id(delivery_date), "delivery_date": delivery_date,
            "customer_id": lookups["customer_by_code"].get(customer_code, UNKNOWN),
            "product_id": lookups["product_by_code"].get(product_code, UNKNOWN),
            "sales_person_id": lookups["sales_person"].get(person_key(sales_person), UNKNOWN),
            "tax_code_id": lookups["tax_code"].get(tax_key(tax_written), UNKNOWN),
            "fx_rate_id": fx_rate_id(order_date, lookups),
            "so_number": clean_int(r["SO No"], fixes),
            "customer_ref_no": clean_text(r["Customer Ref No"], fixes),
            "status": status,
            "item_description": clean_text(r["Item Description"], fixes),
            "hsn_code": clean_code(r["HSN"], fixes),
            "quantity": clean_number(r["Quantity"], fixes),
            "unit_price": clean_number(r["Unit Price"], fixes),
            "discount_pct": clean_number(r["Discount %"], fixes),
            "total_amount": clean_number(r["Total (LC)"], fixes),
            "tax_total": clean_number(r["Tax Total"], fixes),
            "payment_terms": terms,
            "contact_person": clean_text(r["Contact Person"], fixes),
            "contact_number": clean_text(r["Contact Number"], fixes),
            "bill_to_address": clean_text(r["Bill To"], fixes),
            "ship_to_address": clean_text(r["Ship To"], fixes),
            "remarks": clean_text(r["Remarks"], fixes),
            "src_customer_code": customer_code,
            "src_customer_name": clean_text(r["Customer Name"], fixes),
            "src_product_code": product_code,
            "src_sales_person": sales_person,
            "src_tax_code": tax_written,
        })
    if batch:
        rows = drop_exact_duplicates(rows, {"sales_order_line_id", "source_row_no"}, fixes)
    else:
        count_exact_duplicates(rows, {"sales_order_line_id", "source_row_no"}, fixes)
    unknown = count_unknown_keys(
        rows, ["order_date_id", "delivery_date_id", "customer_id", "product_id",
               "sales_person_id", "tax_code_id", "fx_rate_id"], fixes,
        {"product_id": "service line without item no. or item not in master",
         "fx_rate_id": "order date before the first rate window"})
    info = load_info("fact_sales_order_lines", SALES_ORDER_FILE, len(source), rows, fixes, unknown)
    return rows, info


def build_invoice_lines(invoices, notes, sales_orders, lookups, fixes, earlier_invoices=(),
                        batch=False):
    """Sales Invoice Details lines + credit/debit note lines in ONE fact.
    Credit notes: net_* are NEGATIVE and invoice_date = the note date.
    sales_orders: every sales order line known (for the customer of an invoice);
    earlier_invoices: invoice lines already in ai_gold (a batch's notes may
    correct them) - their rows are NOT returned."""
    # (SO number, financial year) -> customer codes, from the sales order lines
    so_customers = {}
    for s in sales_orders:
        if s["so_number"] is not None and s["order_date"]:
            key = (s["so_number"], fy_start_year(s["order_date"]))
            so_customers.setdefault(key, set()).add(s["src_customer_code"])

    def invoice_customer(so_number, so_date, billing_name):
        """SO number + financial year -> the order's customer; else billing name."""
        if so_number is not None and so_date:
            found = so_customers.get((so_number, fy_start_year(so_date)), set())
            if len(found) == 1:
                customer = lookups["customer_by_code"].get(next(iter(found)))
                if customer:
                    fixes.add("customer found via the sales order")
                    return customer
        customer = lookups["customer_by_name"].get(name_key(billing_name))
        if customer:
            fixes.add("customer found via the billing name")
            return customer
        return UNKNOWN

    rows = []
    # ---- part 1: invoice lines (Sales Invoice Details) ----
    for r in invoices:
        invoice_date = clean_date(r["Invoice Date"], "%d/%m/%Y", fixes)
        so_number = clean_int(r["SO Num"], fixes)
        so_date = clean_date(r["SO Date"], "%d/%m/%Y", fixes)
        billing_name = clean_text(r["Customer Billing Name"], fixes)
        invoice_number = clean_code(r["Invoice Num"], fixes)
        product_code = clean_code(r["Part Code SAP Code"], fixes)
        sales_person = clean_text(r["Sales Employee"], fixes)
        quantity = clean_number(r["Quantity"], fixes)
        taxable = clean_number(r["Taxable Value"], fixes)
        line_total = clean_number(r["Total Value"], fixes)
        parts = (invoice_number or "").split("/")
        rows.append({
            "source_format": "INVOICE_DETAILS", "document_type": "INVOICE",
            "source_row_no": clean_int(r["#"], fixes),
            "invoice_date_id": date_id(invoice_date), "invoice_date": invoice_date,
            "customer_id": invoice_customer(so_number, so_date, billing_name),
            "product_id": lookups["product_by_code"].get(product_code, UNKNOWN),
            "sales_person_id": lookups["sales_person"].get(person_key(sales_person), UNKNOWN),
            "fx_rate_id": fx_rate_id(invoice_date, lookups),
            "invoice_number": invoice_number,
            "invoice_series": parts[1] if len(parts) >= 3 else None,
            "transaction_type": clean_text(r["TransType"], fixes),
            "so_number": so_number, "so_date": so_date,
            "customer_ref_no": clean_text(r["Customer Ref. No."], fixes),
            "customer_type": clean_code(r["Customer Type"], fixes),
            "territory": clean_text(r["Territory"], fixes),
            "sale_type": clean_text(r["Type Export/Domestic"], fixes),
            "customer_billing_name": billing_name,
            "customer_billing_city": clean_text(r["Customer Billing City"], fixes),
            "place_of_supply_state": clean_code(r["State Place of Supply"], fixes),
            "country": clean_country(r["Country"], fixes),
            "customer_billing_gstin": clean_code(r["Customer Billing GSTIN"], fixes),
            "customer_shipping_gstin": clean_code(r["Customer Shipping GSTIN"], fixes),
            "customer_billing_address": clean_text(r["Customer Billing Address"], fixes),
            "customer_shipping_address": clean_text(r["Customer Shiping Address"], fixes),
            "item_type": clean_code(r["Item Type G or S"], fixes),
            "src_product_code": product_code,
            "foreign_code": clean_code(r["Item Foreign Code"], fixes),
            "item_description": clean_text(r["Item Description"], fixes),
            "hsn_code": clean_code(r["HSN Code"], fixes),
            "sac_code": clean_code(r["SAC Code"], fixes),
            "uom": clean_text(r["UOM"], fixes),
            "quantity": quantity,
            "unit_price": clean_number(r["Unit Price"], fixes),
            "taxable_value": taxable,
            "freight_amount": clean_number(r["FreightAmt"], fixes),
            "freight_detail": clean_text(r["FreightDetail"], fixes),
            "freight_sac_code": clean_code(r["FreightSACCode"], fixes),
            "igst_rate": clean_number(r["IGST Rate"], fixes),
            "igst_amount": clean_number(r["IGST Amt"], fixes),
            "cgst_rate": clean_number(r["CGST Rate"], fixes),
            "cgst_amount": clean_number(r["CGST Amt"], fixes),
            "sgst_rate": clean_number(r["SGST Rate"], fixes),
            "sgst_amount": clean_number(r["SGST Amt"], fixes),
            "line_total_incl_gst": line_total,
            "doc_round_off": clean_number(r["Doc Round Off"], fixes),
            "invoice_total_incl_gst": clean_number(r["Invoice Total Include GST"], fixes),
            "invoice_discount_pct": clean_number(r["Invoice Discount %"], fixes),
            "src_sales_person": sales_person,
            "remarks": clean_text(r["Remarks"], fixes),
            "note_date_id": UNKNOWN,        # not a note
            "net_quantity": quantity, "net_taxable_value": taxable,
            "net_line_total_incl_gst": line_total,
        })
    lines_by_invoice = {}       # invoice number -> its lines (earlier ones + this file's)
    for i in list(earlier_invoices) + rows:
        lines_by_invoice.setdefault(i["invoice_number"], []).append(i)

    def from_original(invoice_number, column):
        """A value of the ORIGINAL invoice, only when all its lines agree."""
        values = {i[column] for i in lines_by_invoice.get(invoice_number, ())}
        return next(iter(values)) if len(values) == 1 else None

    # ---- part 2: credit / debit note lines (GSTR1_Credit_Debit_Note.csv) ----
    for line_no, r in enumerate(notes, start=1):
        kind = clean_code(r["Type_Credit_or_Debit"], fixes)
        if kind not in ("C", "D"):
            fixes.add("unknown note type -> treated as CREDIT_NOTE")
        doc_type = "DEBIT_NOTE" if kind == "D" else "CREDIT_NOTE"
        sign = -1 if doc_type == "CREDIT_NOTE" else 1
        note_date = clean_date(r["CreditDebitNote_Date"], "%d-%m-%Y", fixes)
        original = clean_code(r["Invoice_Number"], fixes)
        description = clean_text(r["Item_Description"], fixes)
        number = clean_text(r["CreditDebitNote_Number"], fixes)
        prefix = clean_code(r["Doc_Series_Prefix"], fixes)
        suffix = clean_code(r["Doc_Series_Suffix"], fixes)
        billing_name = clean_text(r["Customer_Billing_Name"], fixes)
        quantity = clean_number(r["Item_Quantity"], fixes)
        taxable = clean_number(r["Item_Taxable_Value"], fixes)
        line_total = clean_number(r["Line_Total_Include_GST"], fixes)

        # customer / product / sales person / SO come from the ORIGINAL invoice
        if original in lines_by_invoice:
            fixes.add("note linked to its original invoice (customer, SO, territory ... copied)")
        else:
            fixes.add("note's original invoice not in the invoice file")
        customer = from_original(original, "customer_id")
        if customer in (None, UNKNOWN):
            customer = lookups["customer_by_name"].get(name_key(billing_name), UNKNOWN)
            if customer != UNKNOWN:
                fixes.add("customer found via the billing name")
        same_line = {i["product_id"] for i in lines_by_invoice.get(original, ())
                     if name_key(i["item_description"]) == name_key(description)}
        if len(same_line) == 1:     # the original invoice line with the same description
            product = next(iter(same_line))
        else:                       # else the item master, if the description is unique
            product = lookups["product_by_description"].get(name_key(description), UNKNOWN)
        rows.append({
            "source_format": doc_type, "document_type": doc_type,
            "source_row_no": line_no,
            "invoice_date_id": date_id(note_date), "invoice_date": note_date,
            "customer_id": customer, "product_id": product,
            "sales_person_id": from_original(original, "sales_person_id") or UNKNOWN,
            "fx_rate_id": fx_rate_id(note_date, lookups),
            "invoice_number": original,
            "invoice_series": "DN" if doc_type == "DEBIT_NOTE" else "CN",
            "so_number": from_original(original, "so_number"),
            "so_date": from_original(original, "so_date"),
            "customer_ref_no": from_original(original, "customer_ref_no"),
            "customer_type": from_original(original, "customer_type"),
            "territory": from_original(original, "territory"),
            "sale_type": from_original(original, "sale_type"),
            "customer_billing_name": billing_name,
            "customer_billing_city": clean_text(r["Customer_Billing_City"], fixes),
            "place_of_supply_state": clean_code(r["State_Place_of_Supply"], fixes),
            "country": from_original(original, "country"),
            "customer_billing_gstin": clean_code(r["Customer_Bill_To_GSTIN"], fixes),
            "customer_shipping_gstin": clean_code(r["Customer_Shipping/Billing_GSTIN"], fixes),
            "customer_billing_address": clean_text(r["Customer_Billing_Address"], fixes),
            "customer_shipping_address": clean_text(r["Customer_Shipping_Address"], fixes),
            "item_type": clean_code(r["Item_Type_G_or_S"], fixes),
            "item_description": description,
            "hsn_code": clean_code(r["HSN_SAC_code"], fixes),
            "uom": clean_text(r["Item_UoMCode"], fixes),
            "quantity": quantity,
            "unit_price": clean_number(r["Item_Unit_Price"], fixes),
            "taxable_value": taxable,
            "igst_rate": clean_number(r["IGST_Rate"], fixes),
            "igst_amount": clean_number(r["IGST_Amount"], fixes),
            "cgst_rate": clean_number(r["CGST_Rate"], fixes),
            "cgst_amount": clean_number(r["CGST_Amount"], fixes),
            "sgst_rate": clean_number(r["SGST_Rate"], fixes),
            "sgst_amount": clean_number(r["SGST_Amount"], fixes),
            "cess_rate": clean_number(r["CESS_Rate"], fixes),
            "cess_amount": clean_number(r["CESS_Amount"], fixes),
            "line_total_incl_gst": line_total,
            "doc_round_off": clean_number(r["Rounding_Doc_Level"], fixes),
            "note_number": f"{prefix}{suffix}{number}" if prefix and suffix and number else number,
            "note_series": clean_code(r["Doc_Series"], fixes),
            "note_date_id": date_id(note_date), "note_date": note_date,
            "note_value": clean_number(r["Credit_Debit_Note_Value"], fixes),
            "original_invoice_number": original,
            "original_invoice_date": clean_date(r["Invoice_Date"], "%d-%m-%Y", fixes),
            "issue_reason": clean_text(r["Issue_Reason"], fixes),
            "net_quantity": None if quantity is None else sign * quantity,
            "net_taxable_value": None if taxable is None else sign * taxable,
            "net_line_total_incl_gst": None if line_total is None else sign * line_total,
        })
        fixes.add(f"{doc_type.lower().replace('_', ' ')} line added, net values signed {'+' if sign > 0 else '-'}")

    for i, row in enumerate(rows, start=1):
        row["invoice_line_id"] = i
    if batch:
        rows = drop_exact_duplicates(rows, {"invoice_line_id", "source_row_no"}, fixes)
    else:
        count_exact_duplicates(rows, {"invoice_line_id", "source_row_no"}, fixes)
    unknown = count_unknown_keys(
        rows, ["invoice_date_id", "note_date_id", "customer_id", "product_id",
               "sales_person_id", "fx_rate_id"], fixes,
        {"product_id": "service line without item code or item not found",
         "fx_rate_id": "date outside every rate window"},
        skip=lambda row, col: col == "note_date_id" and row["document_type"] == "INVOICE")
    info = load_info("fact_invoice_lines", f"{INVOICE_FILE} + {NOTE_FILE}",
                     len(invoices) + len(notes), rows, fixes, unknown)
    return rows, info


def build_stock_ledger(lookups, src, batch=False):
    """Inventory Audit Report(s): item number filled down, report date from
    the file name, movement type from the document prefix."""
    fixes = Fixes()
    rows, source_rows, names = [], 0, []
    for path in src.stock_files():
        names.append(path.name)
        found = re.search(r"as on (\d{2})(\d{2})(\d{2})", path.name)
        report_date = date(2000 + int(found.group(3)), int(found.group(2)),
                           int(found.group(1))) if found else None
        source = records(read_excel(path), fixes)
        source_rows += len(source)
        item_code = item_description = None
        for r in source:
            code = clean_code(r["Item No."], fixes)
            if code:                         # first row of a new item block
                item_code = code
                item_description = clean_text(r["Description"], fixes)
            elif item_code:
                fixes.add("item no. filled down from the item's first row")
            else:
                fixes.add("row before the first item no. (item unknown)")
            document = clean_text(r["Document"], fixes)
            if document is None:
                movement = CLOSING_BALANCE
            elif document.upper() == "OPENING BALANCE":
                movement = OPENING_BALANCE
            else:
                prefix = re.match(r"[A-Za-z]*", document).group(0).upper()
                movement = PREFIX_TO_MOVEMENT.get(prefix, UNKNOWN)
            posting_date = clean_date(r["Posting Date"], "%d/%m/%y", fixes)
            rows.append({
                "stock_ledger_id": len(rows) + 1,
                "source_row_no": clean_int(r["#"], fixes),
                "report_date_id": date_id(report_date), "report_date": report_date,
                "product_id": lookups["product_by_code"].get(item_code, UNKNOWN),
                "movement_type_id": movement,
                "posting_date_id": date_id(posting_date), "posting_date": posting_date,
                "system_date": clean_date(r["System Date"], "%d/%m/%y", fixes),
                "src_product_code": item_code, "item_description": item_description,
                "document_no": document,
                "doc_row": clean_int(r["Doc. Row"], fixes),
                "warehouse_code": clean_code(r["Whse"], fixes),
                "quantity": clean_number(r["Quantity"], fixes),
                "unit_cost": clean_number(r["Cost"], fixes),
                "transaction_value": clean_number(r["Trans. Value"], fixes),
                "cumulative_qty": clean_number(r["Cumulative Qty"], fixes),
                "cumulative_value": clean_number(r["Cumulative Value"], fixes),
            })
    if batch:
        rows = drop_exact_duplicates(rows, {"stock_ledger_id", "source_row_no"}, fixes)
    else:
        count_exact_duplicates(rows, {"stock_ledger_id", "source_row_no"}, fixes)
    balance = {OPENING_BALANCE, CLOSING_BALANCE}
    unknown = count_unknown_keys(
        rows, ["report_date_id", "product_id", "movement_type_id", "posting_date_id"], fixes,
        {"movement_type_id": "document prefix not in the movement map"},
        skip=lambda row, col: col == "posting_date_id" and row["movement_type_id"] in balance)
    info = load_info("fact_stock_ledger", " + ".join(names), source_rows, rows, fixes, unknown)
    return rows, info


# ============================================================== database
def mysql_engine(database=None):
    """Engine for the admin login in .env (password never printed)."""
    url = URL.create("mysql+pymysql",
                     username=os.getenv("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD"),
                     host=os.getenv("MYSQL_HOST", "localhost"),
                     port=int(os.getenv("MYSQL_PORT", "3306")),
                     database=database, query={"charset": "utf8mb4"})
    # hide_parameters: SQL errors never show the values (e.g. a password)
    return create_engine(url, hide_parameters=True)


def sql_text(value):
    """A Python string as a MySQL string literal (for COMMENT '...')."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def run_ddl(conn, statement):
    """Run one DDL statement exactly as written (no %-parameter handling)."""
    cursor = conn.connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()


def create_table_sql(table):
    lines = [f"  `{name}` {sql_type} COMMENT {sql_text(comment)}"
             for name, sql_type, comment in table.columns]
    lines.append(f"  PRIMARY KEY (`{table.primary_key}`)")
    for column in table.indexes:
        lines.append(f"  KEY `ix_{table.name}_{column}` (`{column}`)")
    parents = {t.name: t.primary_key for t in ALL_TABLES}
    for column, parent in table.foreign_keys:
        lines.append(f"  CONSTRAINT `fk_{table.name}_{column}` FOREIGN KEY (`{column}`) "
                     f"REFERENCES `{parent}` (`{parents[parent]}`)")
    return (f"CREATE TABLE `{table.name}` (\n" + ",\n".join(lines) + "\n) ENGINE=InnoDB "
            f"DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT={sql_text(table.comment)}")


def plain(value):
    """Python value MySQL can store: numpy numbers -> int/float, NaN -> None."""
    if is_blank(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return value.item()
    return value


def insert_rows(conn, table, rows, into=None, chunk=5000):
    """INSERT the rows into the table (or into `into`, a staging copy), in chunks."""
    columns = table.column_names
    unknown = set().union(*(r.keys() for r in rows)) - set(columns) if rows else set()
    if unknown:
        raise ValueError(f"{table.name}: values for columns not in the table: {sorted(unknown)}")
    statement = (f"INSERT INTO `{into or table.name}` ({', '.join(f'`{c}`' for c in columns)}) "
                 f"VALUES ({', '.join(['%s'] * len(columns))})")
    for start in range(0, len(rows), chunk):
        data = [tuple(plain(row.get(c)) for c in columns) for row in rows[start:start + chunk]]
        conn.exec_driver_sql(statement, data)


def run_sql(conn, statement):
    """Run one statement exactly as written; return the first value of the
    first row, or None when it returns no rows."""
    cursor = conn.connection.cursor()
    try:
        cursor.execute(statement)
        row = cursor.fetchone() if cursor.description else None
        return row[0] if row else None
    finally:
        cursor.close()


def write_gold(table_rows, infos):
    """Create ai_gold if needed, drop + recreate every table, insert all rows."""
    if os.getenv("AI_GOLD_DATABASE", GOLD_DB) != GOLD_DB:
        raise SystemExit(f"AI_GOLD_DATABASE in .env must be '{GOLD_DB}' - this loader writes nowhere else.")
    server = mysql_engine()
    with server.connect() as conn:
        run_ddl(conn, f"CREATE DATABASE IF NOT EXISTS `{GOLD_DB}` "
                      "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    server.dispose()

    engine = mysql_engine(GOLD_DB)
    with engine.begin() as conn:
        current = conn.execute(text("SELECT DATABASE()")).scalar()
        if current != GOLD_DB:      # safety: never drop tables anywhere else
            raise SystemExit(f"Connected to '{current}', expected '{GOLD_DB}' - stopping.")
        for table in reversed(ALL_TABLES):          # facts first (foreign keys)
            run_ddl(conn, f"DROP TABLE IF EXISTS `{GOLD_DB}`.`{table.name}`")
        for table in ALL_TABLES:                    # dimensions first
            run_ddl(conn, create_table_sql(table))
        for table in ALL_TABLES:
            if table is not LOAD_LOG:
                insert_rows(conn, table, table_rows[table.name])
        loaded_at = datetime.now().replace(microsecond=0)
        log_rows = [{"load_log_id": i, "run_id": 1, "run_type": "FULL",
                     "batch_name": INPUT_DIR.name, "table_name": info["table_name"],
                     "source_file": info["source_file"], "source_rows": info["source_rows"],
                     "loaded_rows": info["loaded_rows"], "inserted_rows": info["loaded_rows"],
                     "updated_rows": 0, "skipped_rows": 0, "table_rows_after": info["loaded_rows"],
                     "unknown_key_rows": info["unknown_key_rows"],
                     "fixes": info["fixes"].text(), "loaded_at": loaded_at}
                    for i, info in enumerate(infos, start=1)]
        insert_rows(conn, LOAD_LOG, log_rows)
        counts = {t.name: conn.execute(text(f"SELECT COUNT(*) FROM `{t.name}`")).scalar()
                  for t in ALL_TABLES}
    engine.dispose()
    return counts


def create_reader_user():
    """Read-only MySQL user for the AI: SELECT on ai_gold only."""
    user = os.getenv("AI_DB_USER", READER_USER)
    password = os.getenv("AI_DB_PASSWORD")
    if user != READER_USER:
        raise SystemExit(f"AI_DB_USER in .env must be '{READER_USER}'.")
    if not password:
        print(f"AI_DB_PASSWORD is empty in .env - read-only user '{user}' NOT created.")
        return
    server = mysql_engine()
    try:
        with server.begin() as conn:
            # the password goes in as a bound value (escaped by the driver)
            conn.exec_driver_sql(f"CREATE USER IF NOT EXISTS '{user}'@'localhost' IDENTIFIED BY %s", (password,))
            conn.exec_driver_sql(f"ALTER USER '{user}'@'localhost' IDENTIFIED BY %s", (password,))
            conn.exec_driver_sql(f"GRANT SELECT ON `{GOLD_DB}`.* TO '{user}'@'localhost'")
    except Exception as exc:        # never show the statement (it holds the password)
        code = getattr(getattr(exc, "orig", None), "args", ["?"])[0]
        raise SystemExit(f"Could not create / update user '{user}' (MySQL error {code}).") from None
    finally:
        server.dispose()
    print(f"Read-only user '{user}'@'localhost': SELECT on {GOLD_DB}.* (password from .env)")


# ============================================================== incremental (batch) load
# Business key = what identifies a row in the source system, so a row sent
# again is recognised. The files give fact lines no line number, so a fact
# line's key is its document + its position inside that document: a document
# (sales order, invoice, note, item block of a stock report) is always sent
# whole, lines in the same order. Lines removed from a document are not deleted.
TABLES = {t.name: t for t in ALL_TABLES}
DIMENSION_KEY = {
    "dim_customers": lambda r: r["customer_code"] or ("SHEET-ONLY", name_key(r["customer_name"])),
    "dim_products": lambda r: r["product_code"],
    "dim_fx_rates": lambda r: r["rate_month"],
    "dim_sales_people": lambda r: person_key(r["name_with_title"]),
    "dim_tax_codes": lambda r: r["tax_code"],
}
FACT_DOCUMENT = {   # fact table -> (columns read from ai_gold, document of a row)
    "fact_sales_order_lines": (["so_number", "order_date"],
                               lambda r: (r["so_number"], fy_start_year(r["order_date"]) if r["order_date"] else None)),
    "fact_invoice_lines": (["document_type", "invoice_number", "note_number"],
                           lambda r: (r["document_type"], r["invoice_number"] if r["document_type"] == "INVOICE"
                                      else r["note_number"])),
    "fact_stock_ledger": (["report_date", "src_product_code"],
                          lambda r: (r["report_date"], r["src_product_code"])),
}
NOT_COMPARED = {"source_row_no"}    # the row number changes from one export to the next


def drop_exact_duplicates(rows, ignore, fixes):
    """A batch line that is an exact copy of an earlier line of the batch was
    sent twice: skipped (counted). Returns the remaining rows."""
    seen, unique = set(), []
    for row in rows:
        key = tuple((k, str(v)) for k, v in row.items() if k not in ignore)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    fixes.add(DUPLICATES_SKIPPED, len(rows) - len(unique))
    return unique


def line_keys(rows, document_of):
    """(document, line number inside the document) per row, in row order."""
    seen, keys = Counter(), []
    for row in rows:
        document = document_of(row)
        seen[document] += 1
        keys.append((document, seen[document]))
    return keys


def read_rows(conn, sql):
    return [dict(r) for r in conn.execute(text(sql)).mappings().all()]


def plan_dimension(table, batch_rows, gold_rows, keep_existing):
    """Give each batch row its id: the id of the ai_gold row with the same
    business key, else the next free id. keep_existing: a key already in
    ai_gold keeps its row as it is (sales people: a name written another way
    must not rename the person). A key twice in the batch: first row used."""
    pk, key_of = table.primary_key, DIMENSION_KEY[table.name]
    existing = {key_of(g): g for g in gold_rows if g[pk] != UNKNOWN}
    max_old_id = max([g[pk] for g in gold_rows] + [0])
    next_id, planned, seen = max_old_id + 1, [], set()
    real_rows = [r for r in batch_rows if r[pk] != UNKNOWN]
    for row in real_rows:
        key = key_of(row)
        if key in seen:
            continue
        seen.add(key)
        if key in existing:
            row = dict(existing[key]) if keep_existing else {**row, pk: existing[key][pk]}
        else:
            row = {**row, pk: next_id}
            next_id += 1
        planned.append(row)
    return planned, len(real_rows) - len(planned), max_old_id


def plan_fact(conn, table, rows):
    """Give each batch line its id: the same (document, line no.) already in
    ai_gold -> that id (update or skip), else the next free id (insert)."""
    pk = table.primary_key
    columns, document_of = FACT_DOCUMENT[table.name]
    gold = read_rows(conn, f"SELECT `{pk}`, {', '.join(f'`{c}`' for c in columns)} "
                           f"FROM `{table.name}` ORDER BY `{pk}`")
    existing = dict(zip(line_keys(gold, document_of), (g[pk] for g in gold)))
    max_old_id = max([g[pk] for g in gold] + [0])
    next_id = max_old_id + 1
    for row, key in zip(rows, line_keys(rows, document_of)):
        if key in existing:
            row[pk] = existing[key]
        else:
            row[pk] = next_id
            next_id += 1
    return max_old_id


def same_values(table):
    """SQL condition: staged row s has exactly the values of ai_gold row t
    (text compared byte for byte, so case and spaces count; NULL = NULL)."""
    parts = []
    for name, sql_type, _ in table.columns:
        if name == table.primary_key or name in NOT_COMPARED:
            continue
        if sql_type.startswith(("VARCHAR", "CHAR", "TEXT")):
            parts.append(f"CAST(t.`{name}` AS BINARY) <=> CAST(s.`{name}` AS BINARY)")
        else:
            parts.append(f"t.`{name}` <=> s.`{name}`")
    return " AND ".join(parts)


def stage(conn, table, rows, max_old_id):
    """Copy the planned rows into a TEMPORARY table and count what merging
    them would do. Nothing in the ai_gold tables changes here."""
    pk, staging = table.primary_key, f"stg_{table.name}"
    run_ddl(conn, f"DROP TEMPORARY TABLE IF EXISTS `{staging}`")
    run_ddl(conn, f"CREATE TEMPORARY TABLE `{staging}` LIKE `{table.name}`")
    insert_rows(conn, table, rows, into=staging)
    joined = f"FROM `{staging}` s JOIN `{table.name}` t ON t.`{pk}` = s.`{pk}`"
    matched = run_sql(conn, f"SELECT COUNT(*) {joined}")
    same = run_sql(conn, f"SELECT COUNT(*) {joined} WHERE {same_values(table)}")
    new = sum(1 for r in rows if r[pk] > max_old_id)
    if matched + new != len(rows):
        raise SystemExit(f"{table.name}: {len(rows)} rows planned but {matched} found + {new} new "
                         "- stopping, nothing written.")
    return {"inserted": new, "updated": matched - same, "unchanged": same}


def apply_staged(conn, table, max_old_id):
    """Update the changed rows, insert the new ones, then check that every
    staged row is now in ai_gold with the same values."""
    pk, staging = table.primary_key, f"stg_{table.name}"
    columns = table.column_names
    sets = ", ".join(f"t.`{c}` = s.`{c}`" for c in columns if c != pk)
    run_sql(conn, f"UPDATE `{table.name}` t JOIN `{staging}` s ON t.`{pk}` = s.`{pk}` "
                  f"SET {sets} WHERE NOT ({same_values(table)})")
    column_list = ", ".join(f"`{c}`" for c in columns)
    run_sql(conn, f"INSERT INTO `{table.name}` ({column_list}) SELECT {column_list} "
                  f"FROM `{staging}` WHERE `{pk}` > {max_old_id}")
    left = run_sql(conn, f"SELECT COUNT(*) FROM `{staging}` s LEFT JOIN `{table.name}` t "
                         f"ON t.`{pk}` = s.`{pk}` WHERE NOT ({same_values(table)})")
    if left:
        raise SystemExit(f"{table.name}: {left} rows differ after the merge - stopping, nothing written.")
    run_ddl(conn, f"DROP TEMPORARY TABLE `{staging}`")


def load_batch(batch_dir):
    """Merge ONE batch folder into the existing ai_gold (see the module docstring)."""
    started = time.time()
    src = Source(batch_dir, reference_folder=INPUT_DIR)
    batch_name = src.folder.name
    present = [n for n in (CUSTOMER_FILE, ITEM_FILE, FX_FILE, SALES_ORDER_FILE, INVOICE_FILE,
                           NOTE_FILE, CLIENT_FILE) if src.has(n)] + [p.name for p in src.stock_files()]
    if not present:
        raise SystemExit(f"No input files in {src.folder} - nothing to load.")
    print(f"Reading batch {batch_name} from {src.folder}")
    print("Files in the batch: " + "; ".join(present))

    def step(message):      # progress: a batch of ~100,000 lines takes a few minutes
        print(f"{time.time() - started:7.1f} s  {message}", flush=True)

    so_fixes, invoice_fixes = Fixes(), Fixes()
    sales_orders_raw = (records(read_excel(src.path(SALES_ORDER_FILE)), so_fixes)
                        if src.has(SALES_ORDER_FILE) else [])
    invoices_raw = records(read_excel(src.path(INVOICE_FILE)), invoice_fixes) if src.has(INVOICE_FILE) else []
    notes_raw = read_notes_csv(src.path(NOTE_FILE), invoice_fixes) if src.has(NOTE_FILE) else []
    step(f"read {len(sales_orders_raw):,} sales order lines, {len(invoices_raw):,} invoice lines, "
         f"{len(notes_raw):,} note lines")

    # dimensions the batch brings, built exactly like a full load:
    # table name -> (rows, info, keep_existing)
    dimensions = {}
    if src.has(CUSTOMER_FILE):
        dimensions["dim_customers"] = (*build_customers(src, sheet_only=src.has(CLIENT_FILE)), False)
    if src.has(ITEM_FILE):
        dimensions["dim_products"] = (*build_products(src), False)
    if src.has(FX_FILE):
        dimensions["dim_fx_rates"] = (*build_fx_rates(src), False)
    if sales_orders_raw or invoices_raw:
        dimensions["dim_sales_people"] = (*build_sales_people(sales_orders_raw, invoices_raw), True)
    if sales_orders_raw:
        dimensions["dim_tax_codes"] = (*build_tax_codes(sales_orders_raw), False)
    if not src.has(CLIENT_FILE):
        for name in ("dim_customers", "dim_products"):
            if name in dimensions:
                dimensions[name][1]["source_file"] += f" (client sheets: last version in {INPUT_DIR.name}/)"
    step("dimensions built: " + ", ".join(dimensions))

    engine = mysql_engine(GOLD_DB)
    with engine.begin() as conn:
        if conn.execute(text("SELECT DATABASE()")).scalar() != GOLD_DB:
            raise SystemExit(f"Not connected to '{GOLD_DB}' - stopping.")
        log_columns = {r["COLUMN_NAME"] for r in read_rows(
            conn, "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                  f"WHERE TABLE_SCHEMA = '{GOLD_DB}' AND TABLE_NAME = 'load_log'")}
        if "run_id" not in log_columns:
            raise SystemExit(f"{GOLD_DB} is missing or was built by an older load_gold.py - "
                             "run a full load first: venv\\Scripts\\python.exe loader\\load_gold.py")
        run_id = run_sql(conn, "SELECT COALESCE(MAX(run_id), 0) + 1 FROM load_log")

        # ---- plan: ids for every row (nothing written yet)
        plans = []          # (table, rows, max_old_id, info, duplicates)
        merged = {}         # dimension -> ai_gold rows with the batch rows on top
        for name in ("dim_customers", "dim_products", "dim_fx_rates", "dim_sales_people", "dim_tax_codes"):
            table = TABLES[name]
            gold_rows = read_rows(conn, f"SELECT * FROM `{name}` ORDER BY `{table.primary_key}`")
            by_id = {g[table.primary_key]: g for g in gold_rows}
            if name in dimensions:
                rows, info, keep_existing = dimensions[name]
                planned, duplicates, max_old_id = plan_dimension(table, rows, gold_rows, keep_existing)
                # a dimension key twice in the batch: first row used (no extra row)
                info["fixes"].counts.pop(DUPLICATES_KEPT, None)
                info["fixes"].counts.pop("duplicate customer code (first row used for matching)", None)
                info["fixes"].counts.pop("duplicate item number (first row used for matching)", None)
                info["fixes"].add("same business key twice in the batch (first row kept, rest skipped)", duplicates)
                info["source_rows"] = len([r for r in rows if r[table.primary_key] != UNKNOWN])
                by_id.update({r[table.primary_key]: r for r in planned})
                plans.append((table, planned, max_old_id, info, duplicates))
            merged[name] = list(by_id.values())
        lookups = make_lookups(merged["dim_customers"], merged["dim_products"], merged["dim_fx_rates"],
                               merged["dim_sales_people"], merged["dim_tax_codes"])

        so_rows = []
        if sales_orders_raw:
            so_rows, info = build_sales_order_lines(sales_orders_raw, lookups, so_fixes, batch=True)
            plans.append((TABLES["fact_sales_order_lines"], so_rows,
                          plan_fact(conn, TABLES["fact_sales_order_lines"], so_rows), info,
                          info["fixes"].counts.get(DUPLICATES_SKIPPED, 0)))
            step(f"fact_sales_order_lines: {len(so_rows):,} lines built, keys matched")
        if invoices_raw or notes_raw:
            known_orders = read_rows(conn, "SELECT so_number, order_date, src_customer_code "
                                           "FROM fact_sales_order_lines") + so_rows
            earlier = read_rows(conn, "SELECT invoice_number, customer_id, product_id, sales_person_id, "
                                      "so_number, so_date, customer_ref_no, customer_type, territory, "
                                      "sale_type, country, item_description FROM fact_invoice_lines "
                                      "WHERE document_type = 'INVOICE'")
            rows, info = build_invoice_lines(invoices_raw, notes_raw, known_orders, lookups,
                                             invoice_fixes, earlier_invoices=earlier, batch=True)
            plans.append((TABLES["fact_invoice_lines"], rows,
                          plan_fact(conn, TABLES["fact_invoice_lines"], rows), info,
                          info["fixes"].counts.get(DUPLICATES_SKIPPED, 0)))
            step(f"fact_invoice_lines: {len(rows):,} lines built, keys matched")
        if src.stock_files():
            rows, info = build_stock_ledger(lookups, src, batch=True)
            plans.append((TABLES["fact_stock_ledger"], rows,
                          plan_fact(conn, TABLES["fact_stock_ledger"], rows), info,
                          info["fixes"].counts.get(DUPLICATES_SKIPPED, 0)))
            step(f"fact_stock_ledger: {len(rows):,} rows built (stock files read), keys matched")

        # ---- stage + count + check every table before anything is written
        results = []
        for table, rows, max_old_id, info, duplicates in plans:
            counts = stage(conn, table, rows, max_old_id)
            accounted = counts["inserted"] + counts["updated"] + counts["unchanged"] + duplicates
            if accounted != info["source_rows"]:
                raise SystemExit(f"{table.name}: {info['source_rows']} rows read but {accounted} accounted "
                                 "for (inserted + updated + skipped) - stopping, nothing written.")
            results.append((table, max_old_id, info, counts, duplicates))
        step("every table staged and counted, all counts add up - writing")

        # ---- write: dimensions first (the facts point at them), then the log
        loaded_at = datetime.now().replace(microsecond=0)
        next_log_id = run_sql(conn, "SELECT COALESCE(MAX(load_log_id), 0) + 1 FROM load_log")
        log_rows = []
        for table, max_old_id, info, counts, duplicates in results:
            apply_staged(conn, table, max_old_id)
            rows_after = run_sql(conn, f"SELECT COUNT(*) FROM `{table.name}` "
                                       f"WHERE `{table.primary_key}` <> {UNKNOWN}")
            log_rows.append({
                "load_log_id": next_log_id + len(log_rows), "run_id": run_id,
                "run_type": "INCREMENTAL", "batch_name": batch_name,
                "table_name": table.name, "source_file": f"{batch_name}: {info['source_file']}"[:255],
                "source_rows": info["source_rows"],
                "loaded_rows": counts["inserted"] + counts["updated"],
                "inserted_rows": counts["inserted"], "updated_rows": counts["updated"],
                "skipped_rows": counts["unchanged"] + duplicates, "table_rows_after": rows_after,
                "unknown_key_rows": info["unknown_key_rows"], "fixes": info["fixes"].text(),
                "loaded_at": loaded_at})
        insert_rows(conn, LOAD_LOG, log_rows)
    engine.dispose()
    step("written and committed")

    print(f"\nMerged batch {batch_name} into {GOLD_DB} in {time.time() - started:.1f} s (load run {run_id})")
    print(f"{'table':<26}{'source':>9}{'inserted':>10}{'updated':>9}{'skipped':>9}{'rows after':>12}{'unknown key':>13}")
    for row in log_rows:
        print(f"{row['table_name']:<26}{row['source_rows']:>9}{row['inserted_rows']:>10}"
              f"{row['updated_rows']:>9}{row['skipped_rows']:>9}{row['table_rows_after']:>12}"
              f"{row['unknown_key_rows']:>13}")
    print("\nCleaning fixes per table (also in load_log.fixes):")
    for row in log_rows:
        print(f"- {row['table_name']}: {row['fixes']}")


# ============================================================== full load
def load_full():
    started = time.time()
    src = Source(INPUT_DIR)
    print(f"Reading input files from {INPUT_DIR}")
    # source rows the dimensions and facts share (read once)
    so_fixes, invoice_fixes = Fixes(), Fixes()
    sales_orders_raw = records(read_excel(src.path(SALES_ORDER_FILE)), so_fixes)
    invoices_raw = records(read_excel(src.path(INVOICE_FILE)), invoice_fixes)
    notes_raw = read_notes_csv(src.path(NOTE_FILE), invoice_fixes)

    calendar, calendar_info = build_calendar()
    customers, customers_info = build_customers(src)
    products, products_info = build_products(src)
    fx_rates, fx_info = build_fx_rates(src)
    sales_people, people_info = build_sales_people(sales_orders_raw, invoices_raw)
    tax_codes, tax_info = build_tax_codes(sales_orders_raw)
    movement_types, movement_info = build_stock_movement_types()

    lookups = make_lookups(customers, products, fx_rates, sales_people, tax_codes)
    sales_orders, so_info = build_sales_order_lines(sales_orders_raw, lookups, so_fixes)
    invoice_lines, invoice_info = build_invoice_lines(invoices_raw, notes_raw, sales_orders,
                                                      lookups, invoice_fixes)
    stock, stock_info = build_stock_ledger(lookups, src)

    # facts: every source row must be loaded - stop if not
    for info in (so_info, invoice_info, stock_info):
        if info["source_rows"] != info["loaded_rows"]:
            raise SystemExit(f"{info['table_name']}: {info['source_rows']} rows read but "
                             f"{info['loaded_rows']} built - stopping, nothing written.")

    table_rows = {"dim_calendar": calendar, "dim_customers": customers, "dim_products": products,
                  "dim_fx_rates": fx_rates, "dim_sales_people": sales_people, "dim_tax_codes": tax_codes,
                  "dim_stock_movement_types": movement_types, "fact_sales_order_lines": sales_orders,
                  "fact_invoice_lines": invoice_lines, "fact_stock_ledger": stock}
    infos = [calendar_info, customers_info, products_info, fx_info, people_info, tax_info,
             movement_info, so_info, invoice_info, stock_info]

    counts = write_gold(table_rows, infos)
    create_reader_user()

    print(f"\nLoaded database {GOLD_DB} in {time.time() - started:.1f} s")
    print(f"{'table':<26}{'rows in DB':>11}{'source':>8}{'loaded':>8}{'unknown key':>13}")
    for info in infos:
        name = info["table_name"]
        print(f"{name:<26}{counts[name]:>11}{info['source_rows']:>8}"
              f"{info['loaded_rows']:>8}{info['unknown_key_rows']:>13}")
    print(f"{'load_log':<26}{counts['load_log']:>11}")
    print("\nCleaning fixes per table (also in load_log.fixes):")
    for info in infos:
        print(f"- {info['table_name']}: {info['fixes'].text()}")


def main():
    parser = argparse.ArgumentParser(
        description="Build ai_gold from inputdata/ (full load), or merge one batch folder into it.")
    parser.add_argument("--batch", metavar="FOLDER",
                        help="batch folder (same file names as inputdata/) to load INCREMENTALLY")
    args = parser.parse_args()
    if not args.batch:
        load_full()
        return
    folder = Path(args.batch)
    if not folder.is_dir() and not folder.is_absolute():
        folder = REPO_DIR / args.batch
    if not folder.is_dir():
        raise SystemExit(f"Batch folder not found: {args.batch}")
    load_batch(folder.resolve())


if __name__ == "__main__":
    main()
