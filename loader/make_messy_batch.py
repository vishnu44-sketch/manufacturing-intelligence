"""
make_messy_batch.py - makes ONE messy INCREMENTAL batch of input files
(synthetic test data) for:  load_gold.py --batch <folder>

The batch has the same file names, sheet names, header rows and columns as the
base files in <repo>/inputdata. Its new business dates are 21-Sep-2026 ..
20-Mar-2027 (NOP sales months Oct 2026 .. Mar 2027), so every answer the base
data gives for earlier months stays the same. It also:
  - re-sends rows already loaded from inputdata: most unchanged (the loader
    must skip them), some changed (must be updated): open orders now closed or
    cancelled, a few customers / items / invoices corrected;
  - writes messy but recoverable cells: mixed date formats, Excel serial
    numbers, '1,23,456.00', 'Rs. 4500', '4500 INR', codes in lower case with
    spaces, 'Mr.  Rahul Verma', 'cancelled', 'igst_18', 'Inida', 'Yes' / '1' ...
    plus exact duplicate lines, empty lines, header cells with extra spaces,
    codes not in any master, impossible / out-of-calendar dates and a few truly
    bad amounts ('abc') that must become NULL;
  - keeps the clean TRUTH of every row it writes and writes
    EXPECTED_ANSWERS.txt (+ EXPECTED_ANSWERS.json for scripts): what ai_gold must
    show after the base full load and then this batch.

Run from the repo folder (same seed = same files, about 2 minutes):
    venv\\Scripts\\python.exe loader\\make_messy_batch.py --out inputdata_batches\\batch_001 --seed 1
The base files in inputdata/ are only read, never changed.
"""
import argparse
import csv
import itertools
import json
import random
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

REPO_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = REPO_DIR / "inputdata"

START, END = date(2026, 9, 21), date(2027, 3, 20)   # new business dates of the batch
CALENDAR_END = date(2027, 3, 31)                    # last day in dim_calendar
NEW_CUSTOMERS = 4957        # + 43 in ai_gold = 5,000 customers
NEW_ITEMS = 4850            # + 150 = 5,000 items (4,000 FG, 450 RM, 250 CO, 150 CA)
NEW_ORDERS = 32_200         # about 100,000 sales order lines

CUSTOMER_FILE = "Customer Master Report.xlsx"
ITEM_FILE = "Item Master Lists.xlsx"
FX_FILE = "Exchange Rate.xlsx"
SALES_ORDER_FILE = "Sales Order Report.xlsx"
INVOICE_FILE = "Sales Invoice Details.xlsx"
NOTE_FILE = "GSTR1_Credit_Debit_Note.csv"
BASE_STOCK_FILE = "Inventory Audit Report as on 200926.xlsx"

# what ai_gold holds after the base full load (verified 06-Oct-2026)
BASE_GOLD_ROWS = {"dim_calendar": 1096, "dim_customers": 44, "dim_products": 151, "dim_fx_rates": 23,
                  "dim_sales_people": 7, "dim_tax_codes": 4, "dim_stock_movement_types": 8,
                  "fact_sales_order_lines": 1098, "fact_invoice_lines": 343, "fact_stock_ledger": 162,
                  "load_log": 10}

INDIA_STATES = [  # state, place-of-supply code, GST state code, cities, territory
    ("Karnataka", "KA", "29", ["Bangalore", "Mysore", "Hubli"], "South Region - 1"),
    ("Tamil Nadu", "TN", "33", ["Chennai", "Coimbatore", "Hosur"], "South Region - 2"),
    ("Telangana", "TS", "36", ["Hyderabad"], "South Region"),
    ("Gujarat", "GJ", "24", ["Ahmedabad", "Rajkot"], "West Region - Gujarat"),
    ("Maharashtra", "MH", "27", ["Pune", "Nashik", "Mumbai"], "West Region - Maharashtra"),
    ("Delhi", "DL", "07", ["New Delhi"], "North-East-West Region"),
    ("Haryana", "HR", "06", ["Faridabad", "Gurgaon"], "North-East-West Region"),
]
STATE_BY_NAME = {s[0]: s for s in INDIA_STATES}
FOREIGN = [  # country, cities, legal forms, phone code
    ("Japan", ["Osaka", "Tokyo", "Nagoya"], ["Co., Ltd.", "K.K."], "+81"),
    ("Saudi Arabia", ["Dammam", "Riyadh"], ["Co.", "LLC"], "+966"),
    ("United Arab Emirates", ["Dubai", "Sharjah"], ["FZE", "LLC"], "+971"),
    ("United Kingdom", ["Birmingham", "London"], ["Ltd"], "+44"),
    ("United States of America", ["Chicago", "Houston"], ["Inc.", "LLC"], "+1"),
    ("Thailand", ["Bangkok"], ["Co., Ltd."], "+66"),
    ("Germany", ["Stuttgart", "Munich"], ["GmbH"], "+49"),
    ("China", ["Shanghai"], ["Co., Ltd."], "+86"),
    ("Sri Lanka", ["Colombo"], ["(Pvt) Ltd"], "+94"),
    ("Mexico", ["Monterrey"], ["S.A. de C.V."], "+52"),
    ("South Africa", ["Johannesburg"], ["(Pty) Ltd"], "+27"),
    ("Vietnam", ["Hanoi"], ["JSC"], "+84"),
]
COUNTRY_FIX = {"Unites Arab Emirates": "United Arab Emirates",
               "United State of America": "United States of America"}
NAME_WORDS = ["Aurora", "Apex", "Orion", "Neptune", "Delta", "Indus", "Meridian", "Coral", "Vega", "Zenith",
              "Everest", "Granite", "Tejas", "Pioneer", "Silverline", "Crescent", "Sapphire", "Blue Ridge",
              "Summit", "Horizon", "Falcon", "Phoenix", "Lotus", "Sterling", "Titan", "Nova", "Quantum",
              "Vertex", "Matrix", "Prism", "Kaveri", "Ganga", "Sahyadri", "Nilgiri", "Aravali", "Vindhya",
              "Saraswati", "Sunrise", "Evergreen", "Redwood", "Ironclad", "Precise", "Dynamic", "Global",
              "United", "Royal", "Eastern", "Western", "Southern", "Northern", "Supreme", "Allied",
              "Standard", "Elite", "Prime", "Bharat", "Shakti", "Vajra", "Agni", "Prithvi"]
NAME_TRADES = ["Fluid Power", "Machine Tools", "Precision Components", "Hydraulics", "Engineering Works",
               "Automation", "CNC Systems", "Industrial Solutions", "Grinding Machines", "Tech Industries",
               "Pumps", "Motors", "Castings", "Forgings", "Machining", "Tooling", "Fabricators", "Equipment",
               "Controls", "Motion Systems", "Coolant Systems", "Lubrication", "Gear Works", "Valves",
               "Compressors", "Robotics", "Metal Works", "Auto Components", "Power Systems",
               "Process Equipment"]
INDIA_FORMS = ["Pvt Ltd", "Private Limited", "Limited", "LLP", "Pvt. Ltd."]
FIRST_NAMES = ["Mahesh", "Suresh", "Vikram", "Anil", "John", "Omar", "Kenji", "Ravi", "Arun", "Deepak",
               "Sunil", "Ramesh", "Hiro", "Ahmed", "David", "Ajay", "Naveen", "Prakash"]
LAST_NAMES = ["Kumar", "Reddy", "Tanaka", "Smith", "Patel", "Shah", "Khan", "Iyer", "Nair", "Rao",
              "Menon", "Gupta", "Sato", "Ali", "Brown", "Joshi"]
NEW_SALES_PEOPLE = [
    "Mr. Anand Pillai", "Ms. Kavya Reddy", "Mr. Rohit Sharma", "Ms. Sneha Kulkarni", "Mr. Vivek Iyer",
    "Ms. Ananya Rao", "Mr. Manoj Nair", "Ms. Pooja Desai", "Mr. Harish Gowda", "Ms. Lakshmi Menon",
    "Mr. Nikhil Joshi", "Ms. Meera Shetty", "Mr. Suresh Babu", "Ms. Deepa Hegde", "Mr. Kiran Patil",
    "Ms. Rekha Pillai", "Mr. Abhishek Jain", "Ms. Shalini Gupta", "Mr. Prakash Rao", "Ms. Nandini Bhat",
    "Mr. Ganesh Murthy", "Ms. Swathi Krishnan", "Mr. Rakesh Verma", "Ms. Bhavna Shah"]
FAMILIES = {  # description start -> HSN, SAP segment, SAP product segment
    "Trochoid pump": ("84137099", "Trochoid pumps", "L-06"),
    "Coolant pump": ("84137099", "Coolant pumps", "A-22"),
    "GCI": ("84136090", "GCI", "L-20"),
    "Procon Pump": ("84136090", "Procon Pumps", "L-31"),
    "Hydraulic motor": ("84122990", "Hydraulic motors", "L-61"),
    "YTH-PARTS": ("84139190", "YTH-PARTS", "L-11"),
    "Coolant Unit": ("84669390", "Coolant Units", "L-82"),
}
PRICES = [2500, 4500, 6630, 7800, 12500, 26000, 38880, 53100, 59000, 81000, 123250, 145000, 231000]
TERMS = ["Net-30", "Net-45", "100% ADVANCE", "Immediate Against Supply", "Net-60 days"]
PLACEHOLDER_FORMS = ["NA", "N/A", "#N/A", "NULL", "-", "--"]


# ============================================================== small helpers
def nop_month(day):
    """NOP sales month of a date: 21st of the previous month .. 20th, named after the END month."""
    if day.day <= 20:
        year, month = day.year, day.month
    elif day.month == 12:
        year, month = day.year + 1, 1
    else:
        year, month = day.year, day.month + 1
    return date(year, month, 1).strftime("%b %Y")


def fy_of(day):
    return day.year if day.month >= 4 else day.year - 1


def name_key(name):
    return " ".join(str(name).split()).upper() if name else ""


def strip_title(name):
    for title in ("Mr. ", "Ms. ", "Mrs. ", "Dr. "):
        if name.startswith(title):
            return name[len(title):]
    return name


def rupees(paise):
    """paise (int) -> the number written in a file: int when whole rupees."""
    return paise // 100 if paise % 100 == 0 else paise / 100


def gst(paise, rate):
    """GST on an amount in paise, rounded half up to the paisa."""
    return (paise * rate * 100 + 5000) // 10000 if rate else 0


def indian_grouping(number):
    """1234567.5 -> '12,34,567.50'."""
    text = f"{abs(number):.2f}"
    whole, fraction = text.split(".")
    if len(whole) > 3:
        head, groups = whole[:-3], [whole[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups)
    return ("-" if number < 0 else "") + whole + "." + fraction


def read_sheet(path, sheet=None, header_row=1):
    """Raw cells of a sheet: (rows above the header, header, data rows padded to the header)."""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    all_rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    header = list(all_rows[header_row - 1])
    while header and header[-1] is None:
        header.pop()
    width = len(header)
    data = [(r + [None] * width)[:width] for r in all_rows[header_row:]]
    return all_rows[:header_row - 1], header, [r for r in data if any(v is not None for v in r)]


def weighted_picker(population, rng, skew=0.9, offset=3):
    """A function that picks from population with Zipf-like weights (random ranks)."""
    ranks = list(range(len(population)))
    rng.shuffle(ranks)
    cumulative = list(itertools.accumulate(1 / (r + offset) ** skew for r in ranks))
    return lambda: rng.choices(population, cum_weights=cumulative)[0]


# ============================================================== mess
class Mess:
    """Makes clean values messy - in ways the loader can read back - and counts it."""

    def __init__(self, rng):
        self.rng = rng
        self.done = Counter()

    def hit(self, p):
        return self.rng.random() < p

    def code(self, value, p=0.04):
        if not value or not self.hit(p):
            return value
        self.done["code in lower case / with spaces"] += 1
        return self.rng.choice([value.lower(), f" {value} ", value.lower() + "  ", f"{value} "])

    def spaces(self, value, p=0.03):
        if not value or not isinstance(value, str) or not self.hit(p):
            return value
        self.done["text with double / leading / trailing spaces"] += 1
        if " " in value and self.rng.random() < 0.6:
            i = value.index(" ")
            return value[:i] + "  " + value[i + 1:]
        return self.rng.choice([value + "  ", " " + value])

    def amount(self, number, p=0.08, rupee_sign=True):
        """A number written as text that cleans back to the same number."""
        if number is None or not self.hit(p):
            return number
        self.done["amount written as text ('1,23,456.00', 'Rs. 4500', '4500 INR' ...)"] += 1
        forms = ["indian", "plain", "spaces"] if number < 0 else \
            ["indian", "rs", "inr", "plain", "spaces"] + (["rupee"] if rupee_sign else [])
        form = self.rng.choice(forms)
        if form == "indian":
            return indian_grouping(number)
        if form == "rs":
            return f"Rs. {number:.2f}" if self.rng.random() < 0.5 else f"Rs.{number:,.2f}"
        if form == "inr":
            return f"{number:.2f} INR"
        if form == "rupee":
            return f"₹{number:,.2f}"
        if form == "plain":
            return f"{number:,.2f}"
        return f" {number} "

    def date(self, day, own_format, p=0.15, excel=True):
        """A date in the file's own text format, or (p) another readable form."""
        if day is None:
            return None
        if not self.hit(p):
            return day.strftime(own_format)
        forms = [f for f in ["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d"] if f != own_format]
        if excel:
            forms += ["datetime", "serial"]
        form = self.rng.choice(forms)
        self.done["date in another format / real date / Excel serial number"] += 1
        if form == "datetime":
            return datetime(day.year, day.month, day.day)
        if form == "serial":
            return (day - date(1899, 12, 30)).days
        return day.strftime(form)

    def yes_no(self, flag, p=0.35):
        if not self.hit(p):
            return "YES" if flag == "Y" else "NO"
        self.done["yes/no written as Yes / Y / TRUE / 1"] += 1
        forms = ["Yes", "Y", "TRUE", "1", "yes", True] if flag == "Y" else ["No", "N", "FALSE", "0", "no", False]
        return self.rng.choice(forms)

    def person(self, written, p=0.10):
        if not written or not self.hit(p):
            return written
        self.done["sales person written another way ('RAHUL VERMA', 'Mr.  Rahul Verma')"] += 1
        bare = strip_title(written)
        title = written[:len(written) - len(bare)].strip()
        return self.rng.choice([f"{title}  {bare}", bare.upper(), bare.lower(), bare,
                                f"{title.rstrip('.')} {bare}"])

    def status(self, status, p=0.10):
        if not self.hit(p):
            return status
        self.done["status casing / spelling ('OPEN', 'closed ', 'cancelled')"] += 1
        return self.rng.choice({"Open": ["OPEN", "open", "Open "],
                                "Closed": ["closed ", "CLOSED", "closed"],
                                "Canceled": ["cancelled", "Cancelled", "CANCELED"]}[status])

    def tax(self, written, p=0.10):
        if not self.hit(p):
            return written
        self.done["tax code written another way ('igst_18', 'IGST-18', 'Igst 18%')"] += 1
        kind, rate = written.split(" ") if " " in written else (written[:-1], written[-1])
        return self.rng.choice([f"{kind.lower()}_{rate}", f"{kind}-{rate}", f"{kind.title()} {rate}%",
                                f"{kind}{rate}"])

    def terms(self, terms, p=0.10):
        if not terms.startswith("Net") or not self.hit(p):
            return terms
        self.done["payment terms written another way ('NET 30', 'net-45 days')"] += 1
        days = "".join(ch for ch in terms if ch.isdigit())
        return self.rng.choice([f"NET {days}", f"net-{days} days", f"Net {days} days", f"NET-{days}"])

    def country(self, country, p=0.05):
        if not country or not self.hit(p):
            return country
        self.done["country misspelt / odd case ('Inida', 'U.A.E.', 'JAPAN')"] += 1
        forms = {"India": ["INDIA", "india", "Inida"],
                 "United Arab Emirates": ["U.A.E.", "UAE", "Unites Arab Emirates"],
                 "United States of America": ["U.S.A.", "USA", "United State of America"],
                 "United Kingdom": ["U.K.", "UK", "UNITED KINGDOM"],
                 "Saudi Arabia": ["Saudi Arabiya", "SAUDI ARABIA"]}.get(country, [country.upper()])
        return self.rng.choice(forms)

    def placeholder(self, value, p=0.3):
        """An empty cell written as 'NA' / '#N/A' / '-' ... (cleans back to empty)."""
        if value is not None or not self.hit(p):
            return value
        self.done["empty cell written as 'NA' / '#N/A' / 'NULL' / '-'"] += 1
        return self.rng.choice(PLACEHOLDER_FORMS)


def note_amount(mess, number, p):
    """An amount for the notes CSV: '4500.00', or (p) a messy text form (no rupee sign: cp1252)."""
    text = mess.amount(number, p, rupee_sign=False)
    return text if isinstance(text, str) else f"{number:.2f}"


def person_key(name):
    """'Mr. Rahul Verma' / 'RAHUL VERMA' -> 'RAHUL VERMA' (how the loader matches people)."""
    return " ".join(strip_title(" ".join(name.split())).split()).upper()


def write_xlsx(path, sheet, rows_above, header, rows, mess, messy_headers):
    """Write one sheet; header cells named in messy_headers get extra spaces."""
    header_out = []
    for h in header:
        if h in messy_headers:
            mess.done["header cell with extra spaces"] += 1
            h = f" {h} " if len(header_out) % 2 else f"{h}  "
        header_out.append(h)
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(sheet)
    for r in rows_above:
        ws.append(r)
    ws.append(header_out)
    for r in rows:
        ws.append(r)
    wb.save(path)


def finish_rows(rows, header, rng, mess, duplicates, empty_lines, can_copy=lambda r: True, near=400):
    """Dict rows -> lists in header order, '#' numbered, with exact duplicate
    lines (each copy placed up to `near` lines after its original) and
    completely empty lines added."""
    lines = [[r.get(h) for h in header] for r in rows]
    copyable = [i for i, r in enumerate(rows) if can_copy(r)]
    picks = sorted(rng.sample(copyable, duplicates))
    for offset, i in enumerate(reversed(picks)):
        where = rng.randint(i + 1, min(len(lines), i + near))
        lines.insert(where, list(lines[i]))
    mess.done["exact duplicate line"] += duplicates
    for _ in range(empty_lines):
        lines.insert(rng.randint(5, len(lines) - 5), [None] * len(header))
    mess.done["completely empty line"] += empty_lines
    counter = 0
    if header[0] == "#":
        for line in lines:
            if any(v is not None for v in line):
                counter += 1
                line[0] = counter
    return lines


# ============================================================== base data (read only)
class Base:
    def __init__(self):
        self.cust_above, self.cust_header, self.customers = read_sheet(BASE_DIR / CUSTOMER_FILE)
        self.item_above, self.item_header, self.items = read_sheet(BASE_DIR / ITEM_FILE, "Item Lists")
        self.fx_above, self.fx_header, self.fx = read_sheet(BASE_DIR / FX_FILE, "INR to JPY", header_row=4)
        _, self.so_header, self.orders = read_sheet(BASE_DIR / SALES_ORDER_FILE)
        _, self.inv_header, self.invoices = read_sheet(BASE_DIR / INVOICE_FILE)
        _, self.stock_header, self.stock = read_sheet(BASE_DIR / BASE_STOCK_FILE)
        with open(BASE_DIR / NOTE_FILE, encoding="cp1252", newline="") as fh:
            lines = [r for r in csv.reader(fh)]
        self.note_header, self.notes = lines[0], [r for r in lines[1:] if any(r)]

    @staticmethod
    def rows(header, rows):
        return [dict(zip(header, r)) for r in rows]


def so_date(text):
    return datetime.strptime(text, "%d/%m/%y").date()


def inv_date(text):
    return datetime.strptime(text, "%d/%m/%Y").date()


# ============================================================== generator
class Batch:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.mess = Mess(random.Random(seed + 1000))
        self.base = Base()
        self.truth = defaultdict(Counter)      # table -> counts (source / inserted / ...)
        self.bad_amounts = []
        self.people_found = set()               # sales people (matching key) in the batch files
        self.tax_found = set()                  # tax codes (matching key) in the sales order file
        self.started = time.time()

    # ---------------------------------------------------------- customers
    def make_customers(self):
        rng, mess, base = self.rng, self.mess, self.base
        orders = Base.rows(base.so_header, base.orders)
        invoices = Base.rows(base.inv_header, base.invoices)
        by_code = defaultdict(list)
        for o in orders:
            by_code[o["Customer Code"]].append(o)
        type_by_name = defaultdict(Counter)
        for i in invoices:
            if i["Customer Type"]:
                type_by_name[name_key(i["Customer Billing Name"])][i["Customer Type"]] += 1

        self.customers = []         # truth, every customer with a code
        rows = []
        changed = {"C0003": "mobile", "C0007": "email", "C0010": "mobile+email",
                    "C0015": "inactive", "C0026": "email", "C0030": "inactive"}
        for raw in Base.rows(base.cust_header, base.customers):
            code = raw["CUSTOMER CODE"]
            country = COUNTRY_FIX.get(raw["Bill-to Country"], raw["Bill-to Country"])
            state = STATE_BY_NAME.get(raw["STATE"]) if country == "India" else None
            history = by_code.get(code, [])
            person = Counter(o["Sales Employee"] for o in history).most_common(1)
            cust = {"code": code, "name": raw["CUSTOMER NAME"], "country": country,
                    "city": raw["Bill-to City"], "state": state, "gstin": raw["GSTIN"],
                    "address": raw["BUILDING/FLOOR/ROOM"], "zip": raw["ZIP CODE"],
                    "person": person[0][0] if person else rng.choice(NEW_SALES_PEOPLE),
                    "terms": Counter(o["Payment Terms"] for o in history).most_common(1)[0][0]
                    if history else rng.choice(TERMS),
                    "contact": history[0]["Contact Person"] if history else None,
                    "phone": raw["MOBILE PHONE"],
                    "ctype": type_by_name[name_key(raw["CUSTOMER NAME"])].most_common(1)[0][0]
                    if type_by_name[name_key(raw["CUSTOMER NAME"])] else None,
                    "base": True}
            row = dict(raw)
            change = changed.get(code)
            if change and "mobile" in change:
                row["MOBILE PHONE"] = f"+91 98{rng.randint(10000000, 99999999)}"
            if change and "email" in change:
                row["E-MAIL"] = f"accounts@{raw['CUSTOMER NAME'].split()[0].lower()}-group.example.com"
            if change == "inactive":
                row["ACTIVE"], row["INACTIVE"] = "NO", "YES"
            # recoverable mess only: the row must clean back to what ai_gold holds
            row["CUSTOMER CODE"] = mess.code(code, 0.3)
            row["CUSTOMER NAME"] = mess.spaces(row["CUSTOMER NAME"], 0.25)
            flag = "Y" if row["ACTIVE"] == "YES" else "N"
            row["ACTIVE"] = mess.yes_no(flag)
            row["INACTIVE"] = mess.yes_no("N" if flag == "Y" else "Y", 0.2)
            row["Bill-to Country"] = mess.country(country, 0.6) if mess.hit(0.5) else raw["Bill-to Country"]
            row["GSTIN"] = mess.code(raw["GSTIN"], 0.2)
            if isinstance(row["ZIP CODE"], str) and row["ZIP CODE"].isdigit() and mess.hit(0.3):
                row["ZIP CODE"] = int(row["ZIP CODE"])      # number instead of text: same value
            rows.append(row)
            self.customers.append(cust)
        self.truth["dim_customers"].update(updated=len(changed), unchanged=len(rows) - len(changed))

        used = {name_key(c["name"]) for c in self.customers}
        sales_people = [p for p in NEW_SALES_PEOPLE] + sorted({c["person"] for c in self.customers})
        for n in range(41, 41 + NEW_CUSTOMERS):
            code = f"C{n:04d}"
            foreign = rng.random() < 0.18
            if foreign:
                country, cities, forms, phone_code = rng.choice(FOREIGN)
                state, form = None, rng.choice(forms)
            else:
                country, state = "India", rng.choice(INDIA_STATES)
                cities, form, phone_code = state[3], rng.choice(INDIA_FORMS), "+91"
            while True:
                name = f"{rng.choice(NAME_WORDS)} {rng.choice(NAME_TRADES)} {form}"
                if name_key(name) not in used:
                    used.add(name_key(name))
                    break
            city = rng.choice(cities)
            gstin = (f"{state[2]}{''.join(rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(5))}"
                     f"{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}1Z"
                     f"{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ0123456789')}") if state else None
            cust = {"code": code, "name": name, "country": country, "city": city, "state": state,
                    "gstin": gstin, "zip": str(rng.randint(100000, 999999)),
                    "address": f"Plot {rng.randint(1, 499)}, {rng.choice(['KIADB', 'SIDCO', 'MIDC', 'GIDC', 'Phase 2', 'Sector 5'])} Industrial Area, {city}",
                    "person": rng.choice(sales_people), "terms": rng.choice(TERMS),
                    "contact": f"Mr. {rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                    "phone": f"{phone_code} {rng.randint(9000000000, 9999999999)}",
                    "ctype": rng.choice([None, None, None, "OEM", "OEM", "AFT"]), "base": False}
            active = "N" if rng.random() < 0.03 else "Y"
            word = name.split()[0].lower()
            row = {"CUSTOMER CODE": mess.code(code), "CUSTOMER NAME": mess.spaces(name),
                   "CUSTOMER GROUP": "Foreign Customer" if foreign else rng.choice(["Local Customer"] * 9 + ["Customers"]),
                   "MOBILE PHONE": cust["phone"],
                   "E-MAIL": mess.placeholder(None, 0.7) if mess.hit(0.03) else f"purchase@{word}{n}.example.com",
                   "TYPE OF BUSINESS": "Company", "ACTIVE": mess.yes_no(active),
                   "INACTIVE": mess.yes_no("N" if active == "Y" else "Y", 0.2), "ADDRESS 2": name,
                   "Bill-to City": mess.spaces(city), "ZIP CODE": cust["zip"] if rng.random() < 0.7 else int(cust["zip"]),
                   "STATE": state[0] if state else None, "Bill-to Country": mess.country(country),
                   "BUILDING/FLOOR/ROOM": cust["address"],
                   "GSTIN": mess.code(gstin, 0.05) if gstin else mess.placeholder(None, 0.2),
                   "GST TYPE": "Regular/TDS/ISD" if state else None, "BANK CODE": "-1",
                   "PAN NO.": gstin[2:10] if gstin else None,
                   "ACCOUNTS RECEIVABLE": "Sundry Debtors - Foreign" if foreign else "Sundry Debtors - India"}
            rows.append(row)
            self.customers.append(cust)
        self.truth["dim_customers"]["inserted"] = NEW_CUSTOMERS
        base_codes = {c["code"] for c in self.customers if c["base"]}
        lines = finish_rows(rows, base.cust_header, rng, mess, duplicates=15, empty_lines=3,
                            can_copy=lambda r: r["CUSTOMER CODE"].strip().upper() not in base_codes)
        self.truth["dim_customers"].update(source=len(rows) + 15, duplicates=15)
        write_xlsx(self.out / CUSTOMER_FILE, "Sheet1", base.cust_above, base.cust_header, lines, mess,
                   {"CUSTOMER NAME", "Bill-to City"})
        self.customer_by_code = {c["code"]: c for c in self.customers}

    # ---------------------------------------------------------- items
    def make_items(self):
        rng, mess, base = self.rng, self.mess, self.base
        self.items = []
        rows = []
        changed_price = {"FG00011": 58500, "FG00047": 85000, "FG00072": 13500, "FG00084": 245000,
                         "FG00111": 152000}
        changed_stock = {"FG00013": 45, "FG00029": 30, "RM0003": 120}
        descriptions = set()
        prefix_max, widths = Counter(), {}
        for raw in Base.rows(base.item_header, base.items):
            code = raw["Item No."]
            prefix, digits = code[:2], code[2:]
            prefix_max[prefix] = max(prefix_max[prefix], int(digits))
            widths[prefix] = len(digits)
            row = dict(raw)
            if code in changed_price:
                row["Amount"] = changed_price[code]
            if code in changed_stock:
                row["In Stock"] = changed_stock[code]
            descriptions.add(name_key(raw["Item Description"]))
            family = next((f for f in FAMILIES if raw["Item Description"].startswith(f)), None)
            self.items.append({"code": code, "desc": raw["Item Description"], "price": row["Amount"] * 100,
                               "hsn": raw["HSN Code"], "family": family, "foreign": raw["foreign Code"],
                               "group": raw["Item Group"], "base": True})
            # recoverable mess only
            row["Item No."] = mess.code(code, 0.3)
            row["Active"] = mess.yes_no("Y" if raw["Active"] == "Yes" else "N", 0.5)
            if row["Active"] in ("YES", "NO"):
                row["Active"] = raw["Active"]
            if raw["Date of Udate"]:
                row["Date of Udate"] = mess.date(datetime.strptime(raw["Date of Udate"], "%d/%m/%y").date(),
                                                 "%d/%m/%y", 0.4)
            row["Amount"] = mess.amount(row["Amount"], 0.3)
            row["Item Description"] = mess.spaces(raw["Item Description"], 0.1)
            if raw["Lead Time"] is None:
                row["Lead Time"] = mess.placeholder(None, 0.3)
            rows.append(row)
        self.truth["dim_products"].update(updated=len(changed_price) + len(changed_stock),
                                          unchanged=len(rows) - len(changed_price) - len(changed_stock))

        plan = [("FG", 4000), ("RM", 450), ("CO", 250), ("CA", 150)]
        foreign_used = {r["foreign Code"] for r in Base.rows(base.item_header, base.items) if r["foreign Code"]}
        bad_dates = 5
        for prefix, count in plan:
            for n in range(prefix_max[prefix] + 1, prefix_max[prefix] + 1 + count):
                code = f"{prefix}{n:0{widths[prefix]}d}"
                if prefix == "FG":
                    family = rng.choice(list(FAMILIES))
                    while True:
                        desc = (f"{family} {rng.choice(['CP', 'GX', 'HM', 'PR', 'TX', 'VT'])}-"
                                f"{rng.randint(100, 999)}-{rng.choice(['1B', '2C', '3A'])} "
                                f"{rng.choice(['0.4', '0.75', '1.5', '2.2', '3.7', '7.5'])}kW (415V 50Hz)")
                        if name_key(desc) not in descriptions:
                            break
                    hsn, segment, product_segment = FAMILIES[family]
                    price = rng.choice(PRICES)
                    group = "Finished goods"
                    foreign = None
                    if rng.random() < 0.7:
                        while not foreign or foreign in foreign_used:
                            foreign = (f"IN{rng.randint(100, 999)}{rng.choice('ABCDEFGHJK')}{rng.randint(100, 999)}"
                                       if rng.random() < 0.6 else f"{rng.randint(10000000, 99999999)}T")
                        foreign_used.add(foreign)
                else:
                    family, segment, product_segment, foreign = None, None, None, None
                    word, hsn, group = {"RM": ("Cast iron housing blank", "73259999", "Raw material"),
                                        "CO": ("Packing tape", "39191000", "Consumables"),
                                        "CA": ("Test bench fixture", "84669390", "Capital Item")}[prefix]
                    desc = f"{word} {n}" if prefix != "CA" else f"{word} {n} - tool cost"
                    price = rng.choice([150, 450, 1200, 2500, 8800]) if prefix != "CA" else rng.choice([45000, 98000, 137500])
                descriptions.add(name_key(desc))
                self.items.append({"code": code, "desc": desc, "price": price * 100, "hsn": hsn,
                                   "family": family, "foreign": foreign, "group": group, "base": False})
                updated = date(2025, 1, 1) + timedelta(days=rng.randint(0, 600))
                if bad_dates and prefix == "FG" and rng.random() < 0.01:
                    when, bad_dates = "31/02/26", bad_dates - 1
                    self.mess.done["impossible date (31/02/26) -> must become NULL"] += 1
                else:
                    when = mess.date(updated, "%d/%m/%y", 0.2)
                rows.append({"Item No.": mess.code(code), "Item Description": mess.spaces(desc),
                             "In Stock": rng.randint(0, 60), "Order to Supllier": rng.choice([0, 0, 5, 10]),
                             "Order by Customer": rng.choice([0, 0, 1, 2]), "Value": 0,
                             "foreign Code": mess.code(foreign, 0.05), "Active": mess.yes_no("Y" if rng.random() > 0.02 else "N"),
                             "Amount": mess.amount(price, 0.1), "HSN Code": hsn, "Segment": segment,
                             "Product Segment": product_segment,
                             "Lead Time": rng.choice(["15", "30", " 30 ", 15, None]) if rng.random() < 0.9
                             else mess.placeholder(None, 1.0),
                             "Item Group": group, "GL A/c": "Item Group", "Minimum Inventory": 0,
                             "Pricing unit": "Manual", "Date of Udate": when})
        self.truth["dim_products"]["inserted"] = NEW_ITEMS
        base_codes = {i["code"] for i in self.items if i["base"]}
        lines = finish_rows(rows, base.item_header, rng, mess, duplicates=12, empty_lines=3,
                            can_copy=lambda r: r["Item No."].strip().upper() not in base_codes)
        self.truth["dim_products"].update(source=len(rows) + 12, duplicates=12)
        write_xlsx(self.out / ITEM_FILE, "Item Lists", base.item_above, base.item_header, lines, mess,
                   {"Item Description", "Amount"})
        self.item_by_code = {i["code"]: i for i in self.items}

    # ---------------------------------------------------------- exchange rates
    def make_fx(self):
        base, mess = self.base, self.mess
        header = base.fx_header
        rates = {"Sep 2026": 1.69, "Oct 2026": 1.79, "Nov 2026": 1.74, "Dec 2026": 1.77,
                 "Jan 2027": 1.71, "Feb 2027": 1.68, "Mar 2027": 1.73}
        written = {"Sep 2026": "September 2026", "Oct 2026": "Oct-26", "Nov 2026": "Nov 2026",
                   "Dec 2026": "December 2026", "Jan 2027": "jan-27", "Feb 2027": "FEB-2027",
                   "Mar 2027": "2027-03"}
        rows = []
        for i, (label, rate) in enumerate(rates.items()):
            end = datetime.strptime(label, "%b %Y").date().replace(day=20)
            start = (end.replace(day=1) - timedelta(days=1)).replace(day=21)
            start_cell = [datetime(start.year, start.month, start.day), start.strftime("%d/%m/%Y"),
                          (start - date(1899, 12, 30)).days, start.strftime("%Y-%m-%d")][i % 4]
            end_cell = [end.strftime("%d-%m-%Y"), datetime(end.year, end.month, end.day),
                        end.strftime("%d/%m/%Y"), (end - date(1899, 12, 30)).days][i % 4]
            rows.append([written[label], start_cell, end_cell, "inr" if label == "Dec 2026" else "INR",
                         "JPY", f"{rate} " if label == "Feb 2027" else rate, None])
        self.mess.done["rate month written another way ('September 2026', 'jan-27', '2027-03')"] += 6
        self.truth["dim_fx_rates"].update(source=7, inserted=5, unchanged=2)
        self.fx_rates = rates
        write_xlsx(self.out / FX_FILE, "INR to JPY", base.fx_above, header, rows, mess, {"Rate Month"})

    # ---------------------------------------------------------- sales orders + invoices
    def make_orders_and_invoices(self):
        rng, mess, base = self.rng, self.mess, self.base
        pick_customer = weighted_picker([c for c in self.customers], rng, skew=0.95, offset=4)
        goods = [i for i in self.items if i["group"] == "Finished goods"]
        pick_item = weighted_picker(goods, rng, skew=0.7, offset=8)

        # ---- new orders
        days = (END - START).days
        postings = sorted(START + timedelta(days=rng.randint(0, days)) for _ in range(NEW_ORDERS))
        self.orders = []
        unknown_customers = 0
        unknown_items = 0
        for n, posting in enumerate(postings, start=137):
            if rng.random() < 0.003:
                unknown_customers += 1
                state = rng.choice(INDIA_STATES)
                customer = {"code": f"C9{unknown_customers:03d}", "name": f"Walk-in Customer {unknown_customers}",
                            "country": "India", "city": state[3][0], "state": state, "gstin": None,
                            "address": f"Shop {unknown_customers}, Market Road, {state[3][0]}", "zip": "560001",
                            "person": rng.choice(NEW_SALES_PEOPLE), "terms": "100% ADVANCE",
                            "contact": None, "phone": None, "ctype": None, "base": False, "unknown": True}
            else:
                customer = pick_customer()
            order = {"so": n, "posting": posting, "customer": customer, "lines": [],
                     "ref": f"PO/{rng.randint(1000, 9999)}/26-27",
                     "delivery": min(posting + timedelta(days=rng.randint(7, 21)), CALENDAR_END),
                     "person": None if rng.random() < 0.003 else customer["person"], "base": False}
            if rng.random() < 0.03:
                price = rng.choice([2500, 5000, 7500]) * 100
                order["service"] = True
                order["lines"].append({"item": None, "qty": 0, "price": price, "disc": 0, "total": price})
            else:
                order["service"] = False
                k = rng.choices([1, 2, 3, 4, 5, 6], [20, 20, 20, 15, 13, 12])[0]
                chosen = []
                while len(chosen) < k:
                    if rng.random() < 0.002:
                        unknown_items += 1
                        item = {"code": f"FG9{unknown_items:04d}", "desc": f"Special pump assembly SP-{unknown_items}",
                                "price": rng.choice(PRICES) * 100, "hsn": "84137099", "family": None,
                                "foreign": None, "unknown": True}
                    else:
                        item = pick_item()
                    if item["code"] not in {c["code"] for c in chosen}:
                        chosen.append(item)
                for item in chosen:
                    qty = rng.choices([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20], [30, 20, 12, 8, 8, 5, 5, 5, 3, 2, 2])[0]
                    disc = rng.choices([0, 5, 10, 25], [75, 10, 10, 5])[0]
                    unit = item["price"] * (100 - disc) // 100
                    order["lines"].append({"item": item, "qty": qty, "price": item["price"], "disc": disc,
                                           "total": qty * unit, "unit": unit})
            for line in order["lines"]:
                line["unit"] = line.get("unit", line["price"])
                line["tax"] = self.tax_for(customer, line["item"])
            # shipments: invoices
            if rng.random() < 0.03:
                order["status"], order["shipments"] = "Canceled", []
            else:
                first = posting + timedelta(days=rng.randint(1, 20))
                if not order["service"] and any(l["qty"] >= 2 for l in order["lines"]) and rng.random() < 0.15:
                    second = first + timedelta(days=rng.randint(5, 25))
                    part1 = [(l, (l["qty"] + 1) // 2) for l in order["lines"]]
                    part2 = [(l, l["qty"] - q) for l, q in part1 if l["qty"] - q > 0]
                    shipments = [(first, part1), (second, part2)]
                else:
                    shipments = [(first, [(l, l["qty"]) for l in order["lines"]])]
                order["shipments"] = [s for s in shipments if s[0] <= END]
                order["status"] = "Closed" if len(order["shipments"]) == len(shipments) else "Open"
            self.orders.append(order)
        self.unknown_counts = {"customers": unknown_customers, "items": unknown_items}

        # ---- base orders sent again
        base_orders = defaultdict(list)
        for raw in Base.rows(base.so_header, base.orders):
            d = so_date(raw["Posting Date"])
            base_orders[(raw["SO No"], fy_of(d))].append(raw)
        open_keys = sorted(k for k, lines in base_orders.items() if lines[0]["Status"] == "Open")
        close_keys, cancel_keys = set(open_keys[:15]), set(open_keys[15:17])
        resend_keys = sorted(k for k, lines in base_orders.items()
                             if k in set(open_keys) or so_date(lines[0]["Posting Date"]) >= date(2026, 9, 1))
        self.base_open_kept = [k for k in open_keys if k not in close_keys and k not in cancel_keys]
        self.base_orders = base_orders
        self.base_closing = []      # base orders invoiced in this batch
        for key in sorted(close_keys):
            self.base_closing.append(key)

        # ---- invoices (numbers in date order per series)
        invoices = []
        for order in self.orders:
            for idx, (when, parts) in enumerate(order["shipments"]):
                invoices.append({"date": when, "order": order, "parts": parts, "idx": idx})
        for key in self.base_closing:
            lines = base_orders[key]
            when = START + timedelta(days=rng.randint(0, 19))
            invoices.append({"date": when, "base_order": key, "base_lines": lines, "idx": 0})
        invoices.sort(key=lambda i: (i["date"], i.get("order", {}).get("so", 0) or i["base_order"][0], i["idx"]))
        next_no = {"D": 98, "E": 28, "S": 7}
        for inv in invoices:
            if "order" in inv:
                order = inv["order"]
                series = "S" if order["service"] else ("D" if order["customer"]["country"] == "India" else "E")
            else:
                raw = inv["base_lines"][0]
                cust = self.customer_by_code[raw["Customer Code"]]
                series = "S" if raw["Item No"] is None else ("D" if cust["country"] == "India" else "E")
            inv["series"] = series
            inv["number"] = f"NOPI/{series}/2627/{next_no[series]}"
            next_no[series] += 1
        self.invoices = invoices
        self.write_sales_orders(base_orders, resend_keys, close_keys, cancel_keys)
        self.write_invoices()

    def tax_for(self, customer, item):
        """(written tax code, GST rate %, 'IGST' or 'CSGST') of a line."""
        if customer["country"] != "India":
            return "IGST0", 0, "IGST"
        rate = 12 if item and item.get("family") == "Coolant Unit" else 18
        if customer["state"] and customer["state"][1] == "KA":
            return f"CSGST {rate}", rate, "CSGST"
        return f"IGST {rate}", rate, "IGST"

    def write_sales_orders(self, base_orders, resend_keys, close_keys, cancel_keys):
        rng, mess, base = self.rng, self.mess, self.base
        header = base.so_header
        rows = []
        updated = unchanged = 0
        # base orders again (recoverable mess only; status changes = updates)
        for key in resend_keys:
            for raw in base_orders[key]:
                row = dict(raw)
                status = raw["Status"]
                if key in close_keys:
                    status = "Closed"
                elif key in cancel_keys:
                    status = "Canceled"
                if status != raw["Status"]:
                    updated += 1
                else:
                    unchanged += 1
                row["Status"] = mess.status(status, 0.3)
                row["Customer Code"] = mess.code(raw["Customer Code"], 0.2)
                row["Customer Name"] = mess.spaces(raw["Customer Name"], 0.2)
                row["Posting Date"] = mess.date(so_date(raw["Posting Date"]), "%d/%m/%y", 0.3)
                row["Delivery Date"] = mess.date(so_date(raw["Delivery Date"]), "%d/%m/%y", 0.3)
                row["Item No"] = mess.code(raw["Item No"], 0.2)
                for col in ("Unit Price", "Total (LC)", "Tax Total"):
                    row[col] = mess.amount(raw[col], 0.2)
                row["Payment Terms"] = mess.terms(raw["Payment Terms"], 0.3) \
                    if raw["Payment Terms"] != "Net-60 days" else rng.choice(["Net-60 days", "net 60 days", "NET-60"])
                rows.append(row)
                self.people_found.add(person_key(raw["Sales Employee"]))
                self.tax_found.add(raw["TAX Information"].replace(" ", ""))
        self.truth["fact_sales_order_lines"].update(updated=updated, unchanged=unchanged)

        # new orders (any mess)
        bad_delivery = {"impossible": 15, "placeholder": 20, "outside": 20}
        bad_tax = 2
        lines_total = sum(len(o["lines"]) for o in self.orders)
        for order in self.orders:
            cust = order["customer"]
            for line_no, line in enumerate(order["lines"], start=1):
                item = line["item"]
                delivery = mess.date(order["delivery"], "%d/%m/%y", 0.12)
                kind = None
                r = rng.random()
                if r < 55 / lines_total:
                    kind = rng.choice([k for k, v in bad_delivery.items() if v > 0] or [None])
                if kind == "impossible":
                    delivery = "31/02/27"
                elif kind == "placeholder":
                    delivery = rng.choice(["NA", "#N/A", "", "-", None])
                elif kind == "outside":
                    delivery = rng.choice(["15/03/28", "2028-04-30", "01/06/2028"])
                if kind:
                    bad_delivery[kind] -= 1
                    line["bad_delivery"] = True
                    self.mess.done[f"bad delivery date ({kind}) -> delivery_date_id -1"] += 1
                tax_written, rate, _ = line["tax"]
                tax_paise = gst(line["total"], rate)
                tax_cell = mess.amount(rupees(tax_paise), 0.08)
                if bad_tax and order["status"] == "Closed" and rng.random() < 0.001:
                    bad_tax -= 1
                    tax_cell = rng.choice(["abc", "#VALUE!"])
                    self.bad_amounts.append(f"Sales Order Report.xlsx: SO {order['so']} (FY 2026-27) line {line_no}, "
                                            f"'Tax Total' = '{tax_cell}' -> fact_sales_order_lines.tax_total NULL")
                rows.append({
                    "Customer Code": mess.code(cust["code"]), "Customer Name": mess.spaces(cust["name"]),
                    "Contact Person": cust["contact"] if cust["contact"] else mess.placeholder(None, 0.5),
                    "Contact Number": cust["phone"], "Customer Ref No": order["ref"], "SO No": order["so"],
                    "Status": mess.status(order["status"]),
                    "Posting Date": mess.date(order["posting"], "%d/%m/%y", 0.15),
                    "Delivery Date": delivery,
                    "Item No": mess.code(item["code"]) if item else None,
                    "Item Description": mess.spaces(item["desc"]) if item else None,
                    "Quantity": line["qty"] if rng.random() > 0.03 else f"{line['qty']}.000",
                    "Unit Price": mess.amount(rupees(line["price"])), "Discount %": line["disc"],
                    "Total (LC)": mess.amount(rupees(line["total"])), "Tax Total": tax_cell,
                    "HSN": item["hsn"] if item else None,
                    "Bill To": f"{cust['address']} {cust['city']}-{cust['zip']} IN",
                    "Ship To": f"{cust['address']} {cust['city']}-{cust['zip']}",
                    "Payment Terms": mess.terms(cust["terms"]), "TAX Information": mess.tax(tax_written),
                    "Sales Employee": mess.person(order["person"]) if order["person"] else None,
                    "Remarks": order["ref"] + (" SO for service charges" if order["service"] else "")})
                if order["person"]:
                    self.people_found.add(person_key(order["person"]))
                self.tax_found.add(tax_written.replace(" ", ""))
        self.truth["fact_sales_order_lines"]["inserted"] = lines_total
        lines = finish_rows(rows, header, rng, mess, duplicates=60, empty_lines=6)
        self.truth["fact_sales_order_lines"].update(source=len(rows) + 60, duplicates=60)
        write_xlsx(self.out / SALES_ORDER_FILE, "Sheet1", [], header, lines, mess,
                   {"Customer Code", "Posting Date", "Total (LC)"})

    def write_invoices(self):
        rng, mess, base = self.rng, self.mess, self.base
        header = base.inv_header
        rows = []
        self.invoice_truth = []     # one dict per invoice line written (new lines only)
        bad_price = 2
        for inv in self.invoices:
            if "order" in inv:
                order, cust = inv["order"], inv["order"]["customer"]
                parts = inv["parts"]
                person = order["person"]
                so_no, so_posting, ref = order["so"], order["posting"], order["ref"]
                lines = [(l["item"], qty, l["unit"], qty * l["unit"] if qty else l["unit"], l["tax"])
                         for l, qty in parts]
            else:
                raw_lines = inv["base_lines"]
                cust = self.customer_by_code[raw_lines[0]["Customer Code"]]
                person = raw_lines[0]["Sales Employee"]
                so_no, so_posting, ref = raw_lines[0]["SO No"], so_date(raw_lines[0]["Posting Date"]), \
                    raw_lines[0]["Customer Ref No"]
                lines = []
                for raw in raw_lines:
                    item = self.item_by_code.get(raw["Item No"]) if raw["Item No"] else None
                    total = round(raw["Total (LC)"] * 100)
                    qty = raw["Quantity"] or 0
                    unit = total // qty if qty else total
                    kind, rate = ("CSGST", 18) if raw["TAX Information"] == "CSGST 18" else \
                        (("IGST", 0) if raw["TAX Information"] == "IGST0" else ("IGST", 18))
                    lines.append((item, qty, unit, total, (raw["TAX Information"], rate, kind)))
            sale_type = {"D": "Domestic", "E": "Export", "S": "Service"}[inv["series"]]
            state = cust["state"]
            freight = rng.choice([500, 1000, 1500, 2500, 5000]) * 100 if rng.random() < 0.12 else 0
            freight_kind = rng.choice(["Freight", "Freight", "Freight", "Packing Charges"]) if freight else None
            built = []
            for n, (item, qty, unit, taxable, (tax_written, rate, kind)) in enumerate(lines, start=1):
                igst = gst(taxable, rate) if kind == "IGST" else 0
                cgst = gst(taxable, rate // 2) if kind == "CSGST" else 0
                line_freight = freight if n == 1 else 0
                total = taxable + line_freight + igst + cgst * 2
                built.append((n, item, qty, unit, taxable, line_freight, rate, kind, igst, cgst, total))
            invoice_total = sum(b[-1] for b in built)
            customer_name = "Unknown customer" if cust.get("unknown") else cust["name"]
            person_name = strip_title(person) if person else "Unknown"
            if person:
                self.people_found.add(person_key(person))
            address = (f"{cust['name']},{cust['name']},,{cust['address']},{cust['city']},{cust['zip']},"
                       f"{state[0] if state else ''},{cust['country']}")
            for n, item, qty, unit, taxable, line_freight, rate, kind, igst, cgst, total in built:
                price_cell = mess.amount(rupees(unit), 0.06)
                if bad_price and rng.random() < 0.0005:
                    bad_price -= 1
                    price_cell = rng.choice(["abc", "12..50"])
                    self.bad_amounts.append(f"Sales Invoice Details.xlsx: {inv['number']} line {n}, "
                                            f"'Unit Price' = '{price_cell}' -> fact_invoice_lines.unit_price NULL")
                rows.append({
                    "TransType": "GST Tax Invoice", "SO Date": mess.date(so_posting, "%d/%m/%Y", 0.12),
                    "SO Num": so_no, "Customer Ref. No.": ref,
                    "Customer Type": mess.code(cust["ctype"], 0.2) if cust["ctype"] else mess.placeholder(None, 0.2),
                    "Invoice Num": mess.code(inv["number"], 0.03),
                    "Invoice Date": mess.date(inv["date"], "%d/%m/%Y", 0.15),
                    "Customer Billing Name": mess.spaces(cust["name"]),
                    "Customer Billing City": cust["city"],
                    "State Place of Supply": mess.code(state[1], 0.03) if state else None,
                    "Country": mess.country(cust["country"]),
                    "Item Type G or S": "S" if item is None else "G",
                    "Part Code SAP Code": mess.code(item["code"]) if item else None,
                    "Item Foreign Code": mess.code(item.get("foreign"), 0.03) if item else None,
                    "Item Description": item["desc"] if item else "Pump service charges",
                    "HSN Code": item["hsn"] if item else mess.placeholder(None, 0.2),
                    "SAC Code": None if item else "998717", "Quantity": qty, "UOM": "Manual" if item else None,
                    "Unit Price": price_cell, "Taxable Value": mess.amount(rupees(taxable)),
                    "FreightAmt": mess.amount(rupees(line_freight), 0.05),
                    "FreightDetail": freight_kind if line_freight else None,
                    "FreightSACCode": ("00996511" if freight_kind == "Freight" else "00998540") if line_freight else None,
                    "IGST Rate": rate if kind == "IGST" else 0, "IGST Amt": rupees(igst),
                    "CGST Rate": rate // 2 if kind == "CSGST" else 0, "CGST Amt": rupees(cgst),
                    "SGST Rate": rate // 2 if kind == "CSGST" else 0, "SGST Amt": rupees(cgst),
                    "Total Value": mess.amount(rupees(total)), "Type Export/Domestic": sale_type,
                    "Customer Billing Address": address, "Customer Shiping Address": address,
                    "Doc Round Off": 0, "Invoice Total Include GST": mess.amount(rupees(invoice_total), 0.05),
                    "Invoice Discount %": 0,
                    "Customer Shipping GSTIN": cust["gstin"], "Customer Billing GSTIN": mess.code(cust["gstin"], 0.03),
                    "Sales Employee": mess.person(person) if person else None,
                    "Territory": state[4] if state else "Export",
                    "Remarks": f"{ref} Based On Sales Orders {so_no}."})
                self.invoice_truth.append({
                    "number": inv["number"], "line": n, "date": inv["date"], "customer": customer_name,
                    "sale_type": sale_type, "person": person_name, "taxable": taxable, "freight": line_freight,
                    "item": item, "unknown_customer": bool(cust.get("unknown")),
                    "unknown_item": item is None or bool(item.get("unknown")), "no_person": person is None,
                    "qty": qty, "unit": unit, "rate": rate, "kind": kind, "cust": cust,
                    "desc": item["desc"] if item else "Pump service charges", "hsn": item["hsn"] if item else "998717"})
        inserted = len(rows)

        # base invoices again: 01..13-Sep-2026 unchanged; 4 Jan-2026 invoices get Customer Type 'OEM'
        raw_invoices = Base.rows(header, base.invoices)
        noted = {r[base.note_header.index("Invoice_Number")] for r in base.notes}
        by_number = defaultdict(list)
        for raw in raw_invoices:
            by_number[raw["Invoice Num"]].append(raw)
        candidates = [no for no, ls in by_number.items()
                      if inv_date(ls[0]["Invoice Date"]).month == 1 and inv_date(ls[0]["Invoice Date"]).year == 2026
                      and no not in noted and all(l["Customer Type"] is None for l in ls)]
        corrected = set(sorted(candidates)[:4])
        resent = [no for no, ls in by_number.items() if inv_date(ls[0]["Invoice Date"]) >= date(2026, 9, 1)]
        updated = unchanged = 0
        base_rows = []
        for no in sorted(corrected) + resent:
            for raw in by_number[no]:
                row = dict(raw)
                if no in corrected:
                    row["Customer Type"] = rng.choice(["OEM", "oem", " OEM"])
                    updated += 1
                else:
                    row["Customer Type"] = mess.placeholder(None, 0.5) if raw["Customer Type"] is None \
                        else mess.code(raw["Customer Type"], 0.3)
                    unchanged += 1
                row["Invoice Num"] = mess.code(raw["Invoice Num"], 0.3)
                row["Invoice Date"] = mess.date(inv_date(raw["Invoice Date"]), "%d/%m/%Y", 0.4)
                row["SO Date"] = mess.date(inv_date(raw["SO Date"]), "%d/%m/%Y", 0.3)
                row["Customer Billing Name"] = mess.spaces(raw["Customer Billing Name"], 0.3)
                row["State Place of Supply"] = mess.code(raw["State Place of Supply"], 0.3)
                row["Part Code SAP Code"] = mess.code(raw["Part Code SAP Code"], 0.3)
                for col in ("Unit Price", "Taxable Value", "Total Value", "Invoice Total Include GST"):
                    row[col] = mess.amount(raw[col], 0.3)
                if raw["Country"] in ("India", "Japan", "Saudi Arabia") and mess.hit(0.3):
                    row["Country"] = mess.country(raw["Country"], 1.0)
                base_rows.append(row)
                self.people_found.add(person_key(raw["Sales Employee"]))
        self.corrected_invoices = sorted(corrected)
        self.truth["fact_invoice_lines"].update(updated=updated, unchanged=unchanged, inserted=inserted)
        rows = base_rows + rows
        lines = finish_rows(rows, header, rng, mess, duplicates=60, empty_lines=5)
        self.truth["fact_invoice_lines"].update(source=len(rows) + 60, duplicates=60)
        write_xlsx(self.out / INVOICE_FILE, "Sheet1", [], header, lines, mess,
                   {"Invoice Date", "Taxable Value", "Customer Billing Name"})

    # ---------------------------------------------------------- credit / debit notes
    def make_notes(self):
        rng, mess, base = self.rng, self.mess, self.base
        header = base.note_header
        col = {h: i for i, h in enumerate(header)}
        rows = []
        # base FY 2026-27 notes again, unchanged (recoverable mess only)
        resent = 0
        for raw in base.notes:
            if not raw[col["Doc_Series"]].endswith("2627"):
                continue
            row = list(raw)
            note_day = datetime.strptime(raw[col["CreditDebitNote_Date"]], "%d-%m-%Y").date()
            row[col["CreditDebitNote_Date"]] = mess.date(note_day, "%d-%m-%Y", 0.7, excel=False)
            row[col["Type_Credit_or_Debit"]] = rng.choice(["c", "C ", "C"])
            row[col["Invoice_Number"]] = mess.code(raw[col["Invoice_Number"]], 0.7)
            row[col["Item_Taxable_Value"]] = note_amount(mess, float(raw[col["Item_Taxable_Value"]]), 0.7)
            rows.append(row)
            resent += 1

        # new notes on invoice lines of the batch (85%) and on base FY 2026-27 invoices (15%)
        candidates = [t for t in self.invoice_truth if t["date"] <= END - timedelta(days=3)]
        base_lines = self.base_invoice_lines_for_notes()
        self.note_truth = []
        credit_no, debit_no = 4, 1
        planned = []
        for _ in range(240):
            use_base = rng.random() < 0.15
            original = rng.choice(base_lines if use_base else candidates)
            first_day = max(START, original["date"] + timedelta(days=3))
            note_day = first_day + timedelta(days=rng.randint(0, max(0, min(30, (END - first_day).days))))
            if note_day > END:
                continue
            debit = rng.random() < 0.08
            lines = [original]
            if rng.random() < 0.15:
                siblings = [t for t in (base_lines if use_base else self.lines_of(original["number"]))
                            if t["number"] == original["number"] and t["line"] != original["line"]]
                if siblings:
                    lines.append(rng.choice(siblings))
            planned.append((note_day, debit, lines))
        planned.sort(key=lambda p: p[0])
        for note_day, debit, lines in planned:
            if debit:
                number, series, debit_no = str(debit_no), "DN/2627", debit_no + 1
            else:
                number, series, credit_no = str(credit_no), "CN/2627", credit_no + 1
            built = []
            for original in lines:
                if debit:
                    qty, taxable, reason = original["qty"], max(100, original["taxable"] * 3 // 100), "Additional charges"
                elif rng.random() < 0.6 and original["qty"]:
                    qty = rng.randint(1, original["qty"])
                    taxable, reason = qty * original["unit"], "Rate difference / return"
                else:
                    qty, taxable, reason = original["qty"], max(100, original["taxable"] * 5 // 100), "Rate difference / return"
                igst = gst(taxable, original["rate"]) if original["kind"] == "IGST" else 0
                cgst = gst(taxable, original["rate"] // 2) if original["kind"] == "CSGST" else 0
                built.append((original, qty, taxable, igst, cgst, taxable + igst + 2 * cgst, reason))
            note_value = sum(b[5] for b in built)
            for original, qty, taxable, igst, cgst, line_total, reason in built:
                cust = original["cust"]
                state = cust["state"]
                values = {h: "" for h in header}
                values.update({
                    "CreditDebitNote_Date": mess.date(note_day, "%d-%m-%Y", 0.15, excel=False),
                    "CreditDebitNote_Number": number, "Type_Credit_or_Debit": mess.code("D" if debit else "C", 0.2),
                    "Invoice_Date": original["date"].strftime("%d-%m-%Y"),
                    "Invoice_Number": mess.code(original["number"], 0.1),
                    "Customer_Billing_Name": mess.spaces(cust["name"]),
                    "Customer_Shipping/Billing_GSTIN": cust["gstin"] or "",
                    "State_Place_of_Supply": state[1] if state else "", "State_POS_GSTCode": state[2] if state else "",
                    "Item_Type_G_or_S": "S" if original["item"] is None else "G",
                    "Item_Description": original["desc"], "HSN_SAC_code": original["hsn"],
                    "Item_Quantity": f"{qty:.2f}", "Item_UoMCode": "Manual", "Item_UoMName": "NOS",
                    "Item_Unit_Price": f"{original['unit'] / 100:,.6f}", "Item_Rate": f"{original['unit'] / 100:,.6f}",
                    "Item_Taxable_Value": note_amount(mess, taxable / 100, 0.1),
                    "IGST_Rate": f"{original['rate'] if original['kind'] == 'IGST' else 0:.2f}",
                    "IGST_Amount": f"{igst / 100:.2f}",
                    "CGST_Rate": f"{original['rate'] / 2 if original['kind'] == 'CSGST' else 0:.2f}",
                    "CGST_Amount": f"{cgst / 100:.2f}",
                    "SGST_Rate": f"{original['rate'] / 2 if original['kind'] == 'CSGST' else 0:.2f}",
                    "SGST_Amount": f"{cgst / 100:.2f}", "CESS_Rate": "0.00", "CESS_Amount": "0.00",
                    "Flag_Reverse_Charge": "N", "Original_Customer_Billing_GSTIN": cust["gstin"] or "",
                    "Supplier_GSTIN": "29AAAAA0000A1Z5", "Customer_Billing_Address": cust["address"],
                    "Customer_Billing_City": cust["city"], "Customer_Billing_State": state[1] if state else "",
                    "Customer_Billing_State_GSTCode": state[2] if state else "",
                    "Line_Total_Include_GST": f"{line_total / 100:.2f}", "Non_GST_Taxes": "0.00",
                    "Item_GST_Type": "R", "Location_Name": "Bengaluru", "Location_State_Code": "KA",
                    "Location_State_GSTCode": "29", "Customer_Shipping_Address": cust["address"],
                    "Customer_Shipping_City": cust["city"], "Customer_Shipping_State": state[1] if state else "",
                    "Customer_Shipping_State_GSTCode": state[2] if state else "",
                    "Credit_Debit_Note_Value": f"{note_value / 100:.2f}", "Revision_Month": str(note_day.month),
                    "Duty_Status": "WPAY", "BP_Type": "Regular/TDS/ISD" if state else "Overseas",
                    "Doc_Series": series, "Doc_Series_Prefix": "NOPI", "Doc_Series_Suffix": f"/{series}/",
                    "Issue_Reason": f"{reason} - {original['number']}", "Pre_GST": "N",
                    "GSTIN_As_per_Billing_Address": "N", "Customer_Bill_To_GSTIN": cust["gstin"] or "",
                    "Tax_Only": "N", "Stock_Impact": "Y" if reason.endswith("return") else "N",
                    "Rounding_Doc_Level": "0.00",
                    "Inter_Intra_State": "INTRA_STATE" if original["kind"] == "CSGST" else "INTER_STATE",
                    "Tax_Liable": "Y"})
                rows.append([values[h] for h in header])
                sign = 1 if debit else -1
                self.note_truth.append({
                    "number": f"NOPI/{series}/{number}", "date": note_day, "customer": original["customer"],
                    "sale_type": original["sale_type"], "person": original["person"],
                    "taxable": sign * taxable, "printed_taxable": taxable, "debit": debit,
                    "unknown_customer": original["unknown_customer"],
                    "unknown_item": original["unknown_item"], "no_person": original["no_person"]})
        self.truth["fact_invoice_lines"]["inserted"] += len(self.note_truth)
        self.truth["fact_invoice_lines"]["unchanged"] += resent
        self.truth["fact_invoice_lines"]["source"] += len(rows) + 3
        self.truth["fact_invoice_lines"]["duplicates"] += 3
        # 3 exact duplicate lines, 3 empty lines
        for _ in range(3):
            i = rng.randint(resent, len(rows) - 1)
            rows.insert(rng.randint(i + 1, len(rows)), list(rows[i]))
        self.mess.done["exact duplicate line"] += 3
        with open(self.out / NOTE_FILE, "w", encoding="cp1252", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([f" {h}" if h == "Item_Taxable_Value" else h for h in header])
            for i, row in enumerate(rows):
                if i in (40, 120, 200):
                    writer.writerow([])
                    self.mess.done["completely empty line"] += 1
                writer.writerow(row)

    def lines_of(self, number):
        if not hasattr(self, "_lines_by_number"):
            self._lines_by_number = defaultdict(list)
            for t in self.invoice_truth:
                self._lines_by_number[t["number"]].append(t)
        return self._lines_by_number[number]

    def base_invoice_lines_for_notes(self):
        """Base FY 2026-27 goods invoice lines (not in the Sep re-send window) as
        truth dicts, customer found via the sales order like the loader does."""
        base = self.base
        so_customer = {}
        for raw in Base.rows(base.so_header, base.orders):
            so_customer.setdefault((raw["SO No"], fy_of(so_date(raw["Posting Date"]))), set()).add(raw["Customer Code"])
        lines, counter = [], Counter()
        for raw in Base.rows(base.inv_header, base.invoices):
            day = inv_date(raw["Invoice Date"])
            counter[raw["Invoice Num"]] += 1
            if not (date(2026, 4, 1) <= day < date(2026, 9, 1)) or raw["Part Code SAP Code"] is None:
                continue
            codes = so_customer.get((raw["SO Num"], fy_of(inv_date(raw["SO Date"]))), set())
            if len(codes) != 1:
                continue
            cust = self.customer_by_code[next(iter(codes))]
            qty = raw["Quantity"]
            taxable = round(raw["Taxable Value"] * 100)
            kind, rate = ("CSGST", 18) if raw["CGST Rate"] else ("IGST", raw["IGST Rate"])
            lines.append({"number": raw["Invoice Num"], "line": counter[raw["Invoice Num"]], "date": day,
                          "customer": cust["name"], "sale_type": raw["Type Export/Domestic"],
                          "person": strip_title(raw["Sales Employee"]), "taxable": taxable,
                          "item": self.item_by_code.get(raw["Part Code SAP Code"]), "qty": qty,
                          "unit": taxable // qty if qty else taxable, "rate": rate, "kind": kind,
                          "cust": cust, "desc": raw["Item Description"], "hsn": raw["HSN Code"],
                          "unknown_customer": False, "unknown_item": False, "no_person": False})
        # only invoices whose lines all have a known item (the note's product is matched on them)
        return [l for l in lines if counter[l["number"]] == sum(1 for x in lines if x["number"] == l["number"])]

    # ---------------------------------------------------------- stock
    def make_stock(self):
        rng, mess, base = self.rng, self.mess, self.base
        header = base.stock_header
        # 1) the base report again, unchanged (recoverable mess only)
        rows = []
        closing_base = {}
        current = None
        for raw in Base.rows(header, base.stock):
            row = dict(raw)
            if raw["Item No."]:
                current = raw["Item No."]
                closing_base.setdefault(current, None)
                row["Item No."] = mess.code(raw["Item No."], 0.3)
            if raw["Document"] is None and raw["Item No."]:
                closing_base[current] = (raw["Cumulative Qty"], round(raw["Cumulative Value"] * 100))
            for c in ("System Date", "Posting Date"):
                if raw[c]:
                    row[c] = mess.date(so_date(raw[c]), "%d/%m/%y", 0.3)
            for c in ("Cost", "Trans. Value", "Cumulative Value"):
                row[c] = mess.amount(raw[c], 0.2)
            rows.append(row)
        base_lines = finish_rows(rows, header, rng, mess, duplicates=0, empty_lines=0)
        self.truth["fact_stock_ledger"].update(unchanged=len(rows))
        write_xlsx(self.out / BASE_STOCK_FILE, "Sheet1", [], header, base_lines, mess, set())

        # 2) the new report as on 20-Mar-2027: every item + 10 codes not in the item master
        items = list(self.items) + [{"code": f"FG8{n:04d}", "desc": f"Old pump model OP-{n}", "price": 900000,
                                     "unknown": True} for n in range(1, 11)]
        rows = []
        doc_no = {"PD": 579, "IN": 1, "SI": 95, "IM": 1, "XX": 1}
        self.stock_truth = {"items": 0, "qty": 0, "value": 0, "cogs_rows": 0, "cogs_qty": 0, "cogs_value": 0,
                            "unknown_item_rows": 0, "unknown_movement_rows": 0, "rows": 0, "by_item": {}}
        bad_cost, bad_system_dates, unknown_prefix = 2, 8, 30
        for item in sorted(items, key=lambda i: i["code"]):
            cost = (item["price"] * rng.randint(55, 85)) // 100
            if item["code"] in closing_base and closing_base[item["code"]]:
                open_qty, open_value = closing_base[item["code"]]
                if open_qty:
                    cost = open_value // open_qty
            else:
                open_qty = rng.choice([0, 0, 0] + list(range(1, 40)))
                open_value = open_qty * cost
            qty, value = open_qty, open_value
            balance_rows = []
            span = (END - START).days
            for day in sorted(START + timedelta(days=rng.randint(0, span)) for _ in range(rng.randint(0, 36))):
                kind = rng.choices(["PD", "IN", "SI", "IM"], [50, 35, 8, 7])[0]
                if unknown_prefix and rng.random() < 0.0004:
                    kind, unknown_prefix = "XX", unknown_prefix - 1
                if kind in ("IN", "SI", "IM") and qty < 1:
                    kind = "PD"
                doc = f"{kind} {doc_no[kind]}"
                doc_no[kind] += 1
                if kind == "IM":        # transfer: out of one warehouse, into the other
                    move = rng.randint(1, min(qty, 5))
                    for doc_row, whse, step in ((1, "03", -move), (2, "02", move)):
                        qty, value = qty + step, value + step * cost
                        balance_rows.append((day, doc, doc_row, whse, step, step * cost, qty, value))
                    continue
                move = rng.randint(1, 20) if kind in ("PD", "XX") else -rng.randint(1, min(qty, 10))
                qty, value = qty + move, value + move * cost
                balance_rows.append((day, doc, rng.randint(1, 20), "03" if rng.random() < 0.8 else "02",
                                     move, move * cost, qty, value))
            unknown = bool(item.get("unknown"))
            code_cell = mess.code(item["code"], 0.04)
            rows.append({"Item No.": code_cell, "Description": item["desc"], "Cost": 0, "Trans. Value": 0,
                         "Cumulative Qty": qty, "Cumulative Value": mess.amount(rupees(value), 0.08)})
            rows.append({"Document": "Opening Balance", "Cost": 0, "Trans. Value": 0, "Cumulative Qty": open_qty,
                         "Cumulative Value": mess.amount(rupees(open_value), 0.08)})
            for day, doc, doc_row, whse, move, trans, run_qty, run_value in balance_rows:
                system_day = mess.date(day, "%d/%m/%y", 0.1)
                if bad_system_dates and rng.random() < 0.0002:
                    bad_system_dates -= 1
                    system_day = "31/02/27"
                    self.mess.done["impossible system date (31/02/27) -> must become NULL"] += 1
                cost_cell = mess.amount(rupees(cost), 0.08)
                if bad_cost and rng.random() < 0.0002:
                    bad_cost -= 1
                    cost_cell = rng.choice(["abc", "n.a.5"])
                    self.bad_amounts.append(f"Inventory Audit Report as on 200327.xlsx: item {item['code']}, "
                                            f"document {doc} row {doc_row}, 'Cost' = '{cost_cell}' "
                                            "-> fact_stock_ledger.unit_cost NULL")
                rows.append({"System Date": system_day, "Posting Date": mess.date(day, "%d/%m/%y", 0.1),
                             "Document": doc.lower() if mess.hit(0.03) else doc, "Doc. Row": doc_row,
                             "Whse": whse if mess.hit(0.97) else f" {whse} ",
                             "Quantity": move, "Cost": cost_cell, "Trans. Value": mess.amount(rupees(trans), 0.08),
                             "Cumulative Qty": run_qty, "Cumulative Value": mess.amount(rupees(run_value), 0.08)})
                if doc.startswith("IN"):
                    self.stock_truth["cogs_rows"] += 1
                    self.stock_truth["cogs_qty"] += -move
                    self.stock_truth["cogs_value"] += -trans
                if doc.startswith("XX"):
                    self.stock_truth["unknown_movement_rows"] += 1
            block_rows = 2 + len(balance_rows)
            self.stock_truth["rows"] += block_rows
            if unknown:
                self.stock_truth["unknown_item_rows"] += block_rows
            self.stock_truth["items"] += 1
            self.stock_truth["qty"] += qty
            self.stock_truth["value"] += value
            self.stock_truth["by_item"][item["code"]] = (qty, value)
        lines = finish_rows(rows, header, rng, mess, duplicates=40, empty_lines=5,
                            can_copy=lambda r: r.get("Document") not in (None, "Opening Balance")
                            and r.get("Cost") not in ("abc", "n.a.5")
                            and r.get("System Date") != "31/02/27", near=1)
        self.truth["fact_stock_ledger"].update(inserted=len(rows), source=len(rows) + 40 + len(base_lines),
                                               duplicates=40)
        write_xlsx(self.out / "Inventory Audit Report as on 200327.xlsx", "Sheet1", [], header, lines, mess,
                   {"Item No.", "Cumulative Value"})

    # ---------------------------------------------------------- sales people / tax codes truth
    def people_and_tax_truth(self):
        """dim_sales_people / dim_tax_codes: distinct people / tax codes in the batch files."""
        base_people = {person_key(r[self.base.so_header.index("Sales Employee")]) for r in self.base.orders}
        found = self.people_found
        self.truth["dim_sales_people"].update(source=len(found), inserted=len(found - base_people),
                                              unchanged=len(found & base_people))
        base_codes = {"IGST18", "CSGST18", "IGST0"}
        self.truth["dim_tax_codes"].update(source=len(self.tax_found), inserted=len(self.tax_found - base_codes),
                                           unchanged=len(self.tax_found & base_codes))

    # ---------------------------------------------------------- expected answers
    def expected(self):
        base = self.base
        inv_rows = Base.rows(base.inv_header, base.invoices)
        note_col = {h: i for i, h in enumerate(base.note_header)}
        base_sales = defaultdict(int)        # NOP month -> paise (base invoices + notes)
        base_fy_invoiced = base_fy_notes = 0
        base_cal_sep = 0
        for raw in inv_rows:
            day, taxable = inv_date(raw["Invoice Date"]), round(raw["Taxable Value"] * 100)
            base_sales[nop_month(day)] += taxable
            if day >= date(2026, 4, 1):
                base_fy_invoiced += taxable
            if date(2026, 9, 1) <= day <= date(2026, 9, 30):
                base_cal_sep += taxable
        base_fy_note_count = 0
        for raw in base.notes:
            day = datetime.strptime(raw[note_col["CreditDebitNote_Date"]], "%d-%m-%Y").date()
            taxable = round(float(raw[note_col["Item_Taxable_Value"]]) * 100)
            base_sales[nop_month(day)] -= taxable
            if day >= date(2026, 4, 1):
                base_fy_notes += taxable
                base_fy_note_count += 1

        months = ["Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027"]
        net = defaultdict(int)
        split = defaultdict(lambda: defaultdict(int))
        by_customer = defaultdict(lambda: defaultdict(int))
        by_person = defaultdict(lambda: defaultdict(int))
        invoices_in_month = defaultdict(set)
        freight = defaultdict(int)
        batch_invoiced = sum(t["taxable"] for t in self.invoice_truth)
        cal_sep_batch = 0
        for t in self.invoice_truth:
            m = nop_month(t["date"])
            net[m] += t["taxable"]
            split[m][t["sale_type"]] += t["taxable"]
            by_customer[m][t["customer"]] += t["taxable"]
            by_person[m][t["person"]] += t["taxable"]
            invoices_in_month[m].add(t["number"])
            freight[m] += t["freight"]
            if t["date"] <= date(2026, 9, 30):
                cal_sep_batch += t["taxable"]
        credit_total = debit_total = 0
        credit_notes, debit_notes = set(), set()
        for t in self.note_truth:
            m = nop_month(t["date"])
            net[m] += t["taxable"]
            split[m][t["sale_type"]] += t["taxable"]
            by_customer[m][t["customer"]] += t["taxable"]
            by_person[m][t["person"]] += t["taxable"]
            if t["debit"]:
                debit_total += t["printed_taxable"]
                debit_notes.add(t["number"])
            else:
                credit_total += t["printed_taxable"]
                credit_notes.add(t["number"])
            if t["date"] <= date(2026, 9, 30):
                cal_sep_batch += t["taxable"]

        # open orders after the batch: base orders still open + new open orders
        open_orders = open_lines = open_value = open_value_gst = 0
        for key in self.base_open_kept:
            open_orders += 1
            for raw in self.base_orders[key]:
                open_lines += 1
                open_value += round(raw["Total (LC)"] * 100)
                open_value_gst += round(raw["Total (LC)"] * 100) + round(raw["Tax Total"] * 100)
        for o in self.orders:
            if o["status"] == "Open":
                open_orders += 1
                for line in o["lines"]:
                    open_lines += 1
                    open_value += line["total"]
                    open_value_gst += line["total"] + gst(line["total"], line["tax"][1])

        st = self.stock_truth
        fy_net = (base_fy_invoiced - base_fy_notes) + batch_invoiced + sum(t["taxable"] for t in self.note_truth)
        top_month = "Feb 2027"
        top5 = sorted(by_customer[top_month].items(), key=lambda kv: -kv[1])[:5]
        person_month = "Mar 2027"
        top_person = max(by_person[person_month].items(), key=lambda kv: kv[1])
        split_month = "Jan 2027"

        # -1 keys added by the batch (new rows only)
        so_new = [(o, l) for o in self.orders for l in o["lines"]]
        unknown = {
            "fact_sales_order_lines.customer_id": sum(1 for o, l in so_new if o["customer"].get("unknown")),
            "fact_sales_order_lines.product_id": sum(1 for o, l in so_new if l["item"] is None or l["item"].get("unknown")),
            "fact_sales_order_lines.delivery_date_id": sum(1 for o, l in so_new if l.get("bad_delivery")),
            "fact_sales_order_lines.sales_person_id": sum(1 for o, l in so_new if o["person"] is None),
            "fact_sales_order_lines.tax_code_id": 0, "fact_sales_order_lines.fx_rate_id": 0,
            "fact_sales_order_lines.order_date_id": 0,
            "fact_invoice_lines.customer_id": sum(1 for t in self.invoice_truth + self.note_truth if t["unknown_customer"]),
            "fact_invoice_lines.product_id": sum(1 for t in self.invoice_truth + self.note_truth if t["unknown_item"]),
            "fact_invoice_lines.sales_person_id": sum(1 for t in self.invoice_truth + self.note_truth if t["no_person"]),
            "fact_invoice_lines.fx_rate_id": 0,
            "fact_stock_ledger.product_id": st["unknown_item_rows"],
            "fact_stock_ledger.movement_type_id": st["unknown_movement_rows"],
        }
        counts = {}
        for table, c in self.truth.items():
            counts[table] = {"source_rows": c["source"], "inserted": c["inserted"], "updated": c["updated"],
                             "skipped_unchanged": c["unchanged"], "skipped_duplicates": c["duplicates"],
                             "skipped": c["unchanged"] + c["duplicates"]}
        rows_after = dict(BASE_GOLD_ROWS)
        for table, c in counts.items():
            rows_after[table] += c["inserted"]
        rows_after["load_log"] += len(counts)

        metrics = {
            "nop_month_net_sales": {m: net[m] / 100 for m in months},
            "nop_month_net_sales_base_unchanged": {"Aug 2026": base_sales["Aug 2026"] / 100,
                                                   "Sep 2026": base_sales["Sep 2026"] / 100},
            "aug_2026_split": {"Domestic": 5889340.00, "Export": 1699975.00, "Service": 15000.00},
            "split_month": split_month,
            "split": {k: v / 100 for k, v in sorted(split[split_month].items())},
            "top5_month": top_month,
            "top5_customers": [[name, v / 100] for name, v in top5],
            "top_person_month": person_month,
            "top_person": [top_person[0], top_person[1] / 100],
            "open_orders": [open_orders, open_lines, open_value / 100, open_value_gst / 100],
            "stock_20_mar_2027": [st["items"], st["qty"], st["value"] / 100],
            "stock_20_sep_2026": [52, 542, 23856971.91],
            "cogs_20_mar_2027": [st["cogs_rows"], st["cogs_qty"], st["cogs_value"] / 100],
            "fy_2627": {"invoiced": (base_fy_invoiced + batch_invoiced) / 100,
                        "credit_notes": -(base_fy_notes + credit_total) / 100,
                        "debit_notes": debit_total / 100, "net": fy_net / 100},
            "credit_notes_fy_2627": [base_fy_note_count + len(credit_notes), (base_fy_notes + credit_total) / 100],
            "debit_notes_fy_2627": [len(debit_notes), debit_total / 100],
            "fx_feb_2027": 1.68,
            "customers": 43 + NEW_CUSTOMERS, "products": 150 + NEW_ITEMS,
            "products_without_foreign_code": 47 + sum(1 for i in self.items if not i["base"] and not i["foreign"]),
            "invoices_in_nov_2026": len(invoices_in_month["Nov 2026"]),
            "freight_dec_2026": freight["Dec 2026"] / 100,
            "calendar_sep_2026_net_sales": (base_cal_sep + cal_sep_batch) / 100,
        }
        return {"rows_after": rows_after, "counts": counts, "metrics": metrics, "unknown_keys_added": unknown,
                "bad_amounts": self.bad_amounts, "mess": dict(self.mess.done),
                "unknown_codes": self.unknown_counts, "corrected_invoices": self.corrected_invoices}

    def write_expected(self, exp):
        m = exp["metrics"]
        questions = [
            ("What were net sales in Dec 2026?",
             f"NOP sales month Dec 2026 (21-Nov-2026 to 20-Dec-2026): INR {m['nop_month_net_sales']['Dec 2026']:,.2f}"),
            ("What were net sales in each NOP sales month from Oct 2026 to Mar 2027?",
             "; ".join(f"{k} {v:,.2f}" for k, v in m["nop_month_net_sales"].items())),
            (f"What were domestic, export and service sales in {m['split_month']}?",
             "; ".join(f"{k} {v:,.2f}" for k, v in m["split"].items())),
            (f"Who were the top 5 customers by invoice value in {m['top5_month']}?",
             "; ".join(f"{n} {v:,.2f}" for n, v in m["top5_customers"])),
            ("How many sales orders are open and what is their value?",
             f"{m['open_orders'][0]:,} open orders, {m['open_orders'][1]:,} lines, INR {m['open_orders'][2]:,.2f} "
             f"before GST ({m['open_orders'][3]:,.2f} incl. GST)"),
            ("What is the stock value as on 20-Mar-2027?",
             f"{m['stock_20_mar_2027'][0]:,} items, quantity {m['stock_20_mar_2027'][1]:,}, "
             f"value INR {m['stock_20_mar_2027'][2]:,.2f}"),
            ("What were the total net sales in FY 2026-27?",
             f"invoiced {m['fy_2627']['invoiced']:,.2f}; credit notes {m['fy_2627']['credit_notes']:,.2f}; "
             f"debit notes {m['fy_2627']['debit_notes']:,.2f}; net {m['fy_2627']['net']:,.2f}"),
            ("How many credit notes were issued in FY 2026-27 and for how much?",
             f"{m['credit_notes_fy_2627'][0]:,} credit notes, taxable value INR {m['credit_notes_fy_2627'][1]:,.2f}"),
            ("What is the INR to JPY exchange rate for Feb 2027?", "1.68 JPY per INR (21-Jan-2027 to 20-Feb-2027)"),
            (f"Which sales person had the highest net sales in {m['top_person_month']}?",
             f"{m['top_person'][0]} INR {m['top_person'][1]:,.2f}"),
            ("How many customers and how many products do we have?",
             f"{m['customers']:,} customers and {m['products']:,} products (the Unknown -1 rows not counted)"),
            ("How many invoices did we raise in Nov 2026?", f"{m['invoices_in_nov_2026']:,} invoices"),
            ("What were net sales in Aug 2026?", "INR 7,604,315.00 (unchanged by the batch)"),
            ("What was the COGS in the stock report as on 20-Mar-2027?",
             f"{m['cogs_20_mar_2027'][0]:,} COGS rows, {m['cogs_20_mar_2027'][1]:,} units, "
             f"INR {m['cogs_20_mar_2027'][2]:,.2f}"),
        ]
        exp["questions"] = [{"question": q, "expected": a} for q, a in questions]
        (self.out / "EXPECTED_ANSWERS.json").write_text(json.dumps(exp, indent=1, default=str), encoding="utf-8")

        lines = [f"EXPECTED ANSWERS - {self.out.name}",
                 "Computed by make_messy_batch.py from the clean truth it generated (not from the loader),",
                 "for ai_gold after: (1) load_gold.py full load of inputdata/, then (2) load_gold.py --batch "
                 f"{self.out.name}.", "",
                 "ROWS PER TABLE AFTER THE BATCH (incl. the -1 Unknown row in dimensions)"]
        lines += [f"- {t}: {n:,}" for t, n in exp["rows_after"].items()]
        lines += ["", "WHAT THE BATCH LOAD MUST DO PER TABLE (source rows = inserted + updated + skipped)"]
        for t, c in exp["counts"].items():
            lines.append(f"- {t}: source rows {c['source_rows']:,}; inserted {c['inserted']:,}; updated "
                         f"{c['updated']:,}; skipped {c['skipped']:,} (already loaded, same values "
                         f"{c['skipped_unchanged']:,} + exact duplicate lines {c['skipped_duplicates']:,})")
        lines += ["", "NUMBERS (net sales = SUM(net_taxable_value), NOP months, credit notes negative)"]
        lines += [f"- Net sales NOP {k}: {v:,.2f}" for k, v in m["nop_month_net_sales"].items()]
        lines += [f"- UNCHANGED: net sales NOP {k}: {v:,.2f}" for k, v in m["nop_month_net_sales_base_unchanged"].items()]
        lines += ["- UNCHANGED: NOP Aug 2026 Domestic 5,889,340.00 / Export 1,699,975.00 / Service 15,000.00",
                  "- UNCHANGED: top 5 customers NOP Aug 2026: Aurora Fluid Power Limited 1,730,000.00; ...",
                  "- UNCHANGED: stock value as on 20-Sep-2026: 52 items, 542 units, 23,856,971.91",
                  f"- Calendar month Sep 2026 (1-30 Sep) net sales: {m['calendar_sep_2026_net_sales']:,.2f} "
                  "(was 1,623,375.00: batch invoices dated 21-30 Sep 2026 are added)",
                  f"- Split NOP {m['split_month']}: " + "; ".join(f"{k} {v:,.2f}" for k, v in m["split"].items()),
                  f"- Top 5 customers NOP {m['top5_month']}: " + "; ".join(f"{n} {v:,.2f}" for n, v in m["top5_customers"]),
                  f"- Top sales person NOP {m['top_person_month']}: {m['top_person'][0]} {m['top_person'][1]:,.2f}",
                  f"- Open orders after the batch: {m['open_orders'][0]:,} orders, {m['open_orders'][1]:,} lines, "
                  f"{m['open_orders'][2]:,.2f} before GST, {m['open_orders'][3]:,.2f} incl. GST",
                  f"- Stock as on 20-Mar-2027: {m['stock_20_mar_2027'][0]:,} items, qty {m['stock_20_mar_2027'][1]:,}, "
                  f"value {m['stock_20_mar_2027'][2]:,.2f}",
                  f"- COGS in the 20-Mar-2027 report: {m['cogs_20_mar_2027'][0]:,} rows, {m['cogs_20_mar_2027'][1]:,} "
                  f"units, {m['cogs_20_mar_2027'][2]:,.2f}",
                  f"- FY 2026-27: invoiced {m['fy_2627']['invoiced']:,.2f}; credit notes {m['fy_2627']['credit_notes']:,.2f}; "
                  f"debit notes {m['fy_2627']['debit_notes']:,.2f}; net {m['fy_2627']['net']:,.2f}",
                  f"- Credit notes FY 2026-27: {m['credit_notes_fy_2627'][0]:,} notes, {m['credit_notes_fy_2627'][1]:,.2f}; "
                  f"debit notes {m['debit_notes_fy_2627'][0]:,}, {m['debit_notes_fy_2627'][1]:,.2f}",
                  f"- Exchange rate Feb 2027: {m['fx_feb_2027']}",
                  f"- Customers {m['customers']:,}; products {m['products']:,}; products without a foreign code "
                  f"{m['products_without_foreign_code']:,}",
                  f"- Invoices in NOP Nov 2026: {m['invoices_in_nov_2026']:,}; freight NOP Dec 2026: {m['freight_dec_2026']:,.2f}",
                  "", "ROWS WITH A -1 (UNKNOWN) KEY ADDED BY THE BATCH (new rows only)"]
        lines += [f"- {k}: {v:,}" for k, v in exp["unknown_keys_added"].items()]
        lines += ["", "TRULY BAD AMOUNTS (must load as NULL; text like 'abc' is logged as 'bad number -> NULL', "
                      "an Excel error cell like #VALUE! is read as an empty cell)"]
        lines += [f"- {b}" for b in exp["bad_amounts"]]
        lines += ["", "BASE ROWS RE-SENT WITH CHANGES (must be UPDATED, same id)",
                  "- sales orders: the 27 open orders of FY 2026-27 re-sent; the first 15 (by SO number) now Closed "
                  "and invoiced in this batch, the next 2 Canceled, the last 10 still Open (unchanged)",
                  "- customers C0003, C0007, C0010, C0015, C0026, C0030: new mobile / e-mail / inactive",
                  "- items FG00011, FG00047, FG00072, FG00084, FG00111 new price; FG00013, FG00029, RM0003 new stock qty",
                  "- invoices " + ", ".join(self.corrected_invoices) + ": Customer Type now 'OEM'",
                  "", "MESS WRITTEN INTO THE FILES (cells)"]
        lines += [f"- {k}: {v:,}" for k, v in sorted(exp["mess"].items())]
        lines += ["", "QUESTIONS TO ASK THE APP (expected answer)"]
        lines += [f"{i}. {q['question']}\n   -> {q['expected']}" for i, q in enumerate(exp["questions"], start=1)]
        (self.out / "EXPECTED_ANSWERS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Make one messy incremental batch for load_gold.py --batch.")
    parser.add_argument("--out", default="inputdata_batches/batch_001", help="output folder")
    parser.add_argument("--seed", type=int, default=1, help="random seed (same seed = same files)")
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_DIR / out
    if out.resolve() == BASE_DIR.resolve():
        raise SystemExit("Refusing to write into inputdata/ (the base files).")
    out.mkdir(parents=True, exist_ok=True)
    batch = Batch(args.seed)
    batch.out = out
    batch.make_customers()
    batch.make_items()
    batch.make_fx()
    batch.make_orders_and_invoices()
    batch.make_notes()
    batch.make_stock()
    batch.people_and_tax_truth()
    exp = batch.expected()
    batch.write_expected(exp)
    print(f"Wrote batch {out} in {time.time() - batch.started:.0f} s")
    for t, c in exp["counts"].items():
        print(f"- {t}: {c}")
    print("See EXPECTED_ANSWERS.txt")


if __name__ == "__main__":
    main()
