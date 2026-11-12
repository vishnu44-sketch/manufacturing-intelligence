"""The Knowledge graph page (/graph): who buys what, from whom and where, built live from the NOP data (MySQL
ai_gold) on every call. No database of its own, nothing is written, and no AI call (0 tokens): fixed SQL written
here, run read-only with driver parameters (warehouse.run_select_params), so what a user types never becomes SQL.

Nodes - "type:key" ids that stay the same between calls:
    customer:16   product:45   category:Trochoid pumps   sales_person:5   state:Tamil Nadu   sale_type:Export
    document:product_catalogue.pdf#2   (one page of a company PDF in pdfs/)
    A foreign customer has no Indian state: its country is its "state" node (state:Germany).
Edges:
    customer -BOUGHT-> product            net sales, quantity and invoices of the customer's lines of that product
    product -IN_CATEGORY-> category       the client's product_category, else SAP's product family (sap_segment)
    customer -HANDLED_BY-> sales_person   the sales person on the customer's invoices, with the amount
    customer -IN_STATE-> state            the customer's bill-to state (or country), with its sales
    customer -BUYS_AS-> sale_type         Domestic / Export / Service, with the amount
    category -COVERED_BY-> document       a PDF page that names the category or its series ("TP series", "TP-50")
    product -COVERED_BY-> document        a PDF page with the product's model code, else its category's pages
    customer -BUYS_LIKE-> customer        similar(): customers who buy the same products

The rules of the data (docs/business_rules.md): sales = SUM(net_taxable_value) (credit notes are negative
already); never a line dated after today (invoice_date <= CURDATE()), so the current FY counts "so far"; a FY
through dim_calendar.financial_year. The Unknown (-1) customer, product and sales person are never nodes: their
amount stays in the totals and is named in a note, so nothing is hidden.

Why the category falls back to sap_segment: only 93 of the 5,000 items have a client category, so 97% of the
sales would sit in one "Not classified" node; where both exist they are always the same.

search(q, types, offset, limit)  up to 20 nodes whose name holds q (2 characters or more); a type word
                          ("customers", "sales person rekha") gives the top 10 of that type by net sales; a small
                          spelling mistake ("aurra") gives close names marked fuzzy ("Did you mean ...?"). The reply
                          says how many there are in all (total), and offset / limit page through them ("Show
                          more": 10 at a time, never past the 50th)
node(type, key, fy, limit) one node, its totals, and its top `limit` neighbours of each edge type
similar(customer, fy, limit) the customers who buy the most of the same products
"""
import datetime
import decimal
import difflib
import logging
import re
import threading
import time

from .rag import warehouse

log = logging.getLogger(__name__)

NODE_TYPES = ("customer", "product", "category", "sales_person", "state", "sale_type", "document")
TYPE_NAMES = {"customer": "Customer", "product": "Product", "category": "Category", "sales_person": "Sales person",
              "state": "State / country", "sale_type": "Sale type", "document": "Document"}
SALE_TYPES = ("Domestic", "Export", "Service")
MIN_SEARCH = 2           # characters before a search runs
MAX_SEARCH_CHARS = 100
SEARCH_LIMIT = 20        # nodes in one search reply
DEFAULT_LIMIT = 25       # neighbours of each edge type
MAX_LIMIT = 50
SIMILAR_LIMIT = 10
MAX_SIMILAR = 25
CANDIDATES = 200         # customers looked at for similar()
CACHE_SECONDS = 600      # the FY dates, the small totals and the document links are kept 10 minutes
MYSQL_DOWN = "The NOP data (MySQL) cannot be read right now - please try again in a minute."

# the smarter search box (no AI): type words, and close spellings of the names
TOP_LIMIT = 10           # nodes in a reply to a type word ("customers", "customer tamil")
FUZZY_LIMIT = 10         # "did you mean" nodes at most
FUZZY_PER_TYPE = 5       # ... and at most this many of one type, so the types mix
FUZZY_BELOW = 3          # close spellings are tried when the plain search finds fewer nodes than this
FUZZY_CUTOFF = 0.75      # difflib ratio a typed word needs to a word of a name (aurra ~ aurora 0.91)
FUZZY_MIN_WORD = 4       # shorter typed words are never matched loosely
FUZZY_CANDIDATES = 200   # names of one type looked at closely for one search
MAX_TYPED_WORDS = 6      # words of a query looked at (the rest are ignored)
NAMES_MAX = 50_000       # rows of the names query (5,000 customers + 5,000 products + a few)
NAMED_TYPES = ("customer", "product", "category", "sales_person", "state")
TYPE_WORDS = {           # a word (or two) that means a node type
    **dict.fromkeys(("customer", "customers"), "customer"),
    **dict.fromkeys(("product", "products", "item", "items"), "product"),
    **dict.fromkeys(("category", "categories"), "category"),
    **dict.fromkeys(("sales person", "sales persons", "sales people", "salesperson", "salespersons", "salespeople",
                     "sales-person", "sales-persons", "sales-people", "sales_person", "sales rep", "sales reps",
                     "sales-rep", "sales-reps", "rep", "reps"), "sales_person"),
    **dict.fromkeys(("state", "states", "country", "countries", "region", "regions"), "state"),
}
TYPE_PLURALS = {"customer": "customers", "product": "products", "category": "categories",
                "sales_person": "sales people", "state": "states / countries"}
TYPE_ONE = {"customer": "customer", "product": "product", "category": "category", "sales_person": "sales person",
            "state": "state / country"}
MAX_SEARCH_HITS = 50     # "Show more" never lists more than this many nodes (offset + limit)
PAGE_LIMIT = 10          # nodes one "Show more" call may ask for (?limit=1..10)
NARROW = " - type more to narrow"
LEAD_WORDS = frozenset(("top", "all", "best"))               # "top customers" = "customers"
FILLER_WORDS = frozenset(("in", "of", "the", "from", "for", "at", "by", "a", "an", "with", "on", "near", "named",
                          "called"))
WORD = re.compile(r"[^\W_]+")


class BadRequest(ValueError):
    """A value the API cannot use (the reply is 400 with this text)."""


class NotFound(LookupError):
    """No such node (the reply is 404 with this text)."""


# ------------------------------------------------------------------ the SQL pieces (fixed text, never user input)
CATEGORY = "COALESCE(p.product_category, p.sap_segment, 'Not classified')"
STATE = "COALESCE(cu.state, cu.country, 'Unknown')"
FACTS = ("fact_invoice_lines f JOIN dim_customers cu ON cu.customer_id = f.customer_id "
         "JOIN dim_products p ON p.product_id = f.product_id "
         "JOIN dim_sales_people sp ON sp.sales_person_id = f.sales_person_id")
CALENDAR = " JOIN dim_calendar c ON c.date_id = f.invoice_date_id"
INVOICES = "COUNT(DISTINCT CASE WHEN f.document_type = 'INVOICE' THEN f.invoice_number END)"

# the lines of one node (%s = its key)
NODE_FILTER = {
    "customer": "f.customer_id = %s",
    "product": "f.product_id = %s",
    "category": f"{CATEGORY} = %s AND f.product_id <> -1",
    "sales_person": "f.sales_person_id = %s",
    "state": f"{STATE} = %s AND f.customer_id <> -1",
    "sale_type": "f.sale_type = %s",
}
# a neighbour type: (its key, its label, a short second line, the condition that leaves the Unknown row out)
GROUP = {
    "customer": ("f.customer_id", "cu.customer_name", STATE, "f.customer_id <> -1"),
    "product": ("f.product_id", "p.product_description", "p.product_code", "f.product_id <> -1"),
    "category": (CATEGORY, CATEGORY, "", "f.product_id <> -1"),
    "sales_person": ("f.sales_person_id", "sp.sales_person_name", "", "f.sales_person_id <> -1"),
    "state": (STATE, STATE, "", "f.customer_id <> -1"),
    "sale_type": ("f.sale_type", "f.sale_type", "", "f.sale_type IS NOT NULL"),
}
# the edges of each node type found in the sales lines: (edge, neighbour type, the node is the edge's source)
LINKS = {
    "customer": [("BOUGHT", "product", True), ("HANDLED_BY", "sales_person", True), ("IN_STATE", "state", True),
                 ("BUYS_AS", "sale_type", True)],
    "product": [("BOUGHT", "customer", False), ("IN_CATEGORY", "category", True)],
    "category": [("IN_CATEGORY", "product", False)],
    "sales_person": [("HANDLED_BY", "customer", False)],
    "state": [("IN_STATE", "customer", False)],
    "sale_type": [("BUYS_AS", "customer", False)],
}
# the Unknown (-1) rows: in the totals, never a node
UNKNOWN = {
    "customer": ("f.customer_id = -1", "Unknown customer"),
    "product": ("f.product_id = -1", "Unknown product (service lines, or items not in the master)"),
    "sales_person": ("f.sales_person_id = -1", "Unknown sales person"),
}


# ------------------------------------------------------------------ small helpers
def _rows(sql, params=(), max_rows=warehouse.MAX_ROWS):
    """The rows of one fixed read-only SELECT with its parameters."""
    return warehouse.run_select_params(sql, params, max_rows)["rows"]


def _num(value):
    """A MySQL number as a float (None -> 0.0)."""
    if value is None:
        return 0.0
    return float(value) if isinstance(value, (decimal.Decimal, int, float)) else 0.0


def indian(value, places=2):
    """12345678.5 -> '1,23,45,678.50': Indian commas (lakh, crore), as the app writes amounts."""
    number = round(float(value or 0), places)
    text = f"{abs(number):.{places}f}"
    whole, _, fraction = text.partition(".")
    if len(whole) > 3:
        head, groups = whole[:-3], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, whole[-3:]]) if head else ",".join([*groups, whole[-3:]])
    sign = "-" if number < 0 else ""
    return f"{sign}{whole}.{fraction}" if fraction else f"{sign}{whole}"


def quantity_text(value):
    """2462.000 -> '2,462', 12.500 -> '12.5' (quantities drop their extra zeros)."""
    number = _num(value)
    if number == int(number):
        return indian(number, 0)
    return indian(number, 3).rstrip("0").rstrip(".")


def _day(value):
    """A date as the answers write it: 21-Dec-2025 ('' for none)."""
    return value.strftime("%d-%b-%Y") if isinstance(value, datetime.date) else ""


def escape_like(text):
    """Text for a LIKE pattern: its own % and _ (and the escape sign) are plain characters."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_cache = {}
_cache_lock = threading.Lock()


def _cached(key, make):
    """make() once per key and day for CACHE_SECONDS (the FY dates, the small totals, the document links)."""
    full = (datetime.date.today(), *key)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(full)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = make()
    with _cache_lock:
        _cache[full] = (now, value)
    return value


def clear_cache():
    """Forget the kept values (tests; a new data load shows at once)."""
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------------ checking what the API was given
def parse_type(value, allowed=NODE_TYPES):
    kind = str(value or "").strip().lower()
    if kind not in allowed:
        raise BadRequest(f"Unknown node type '{kind[:30]}'. Use one of: {', '.join(allowed)}.")
    return kind


def parse_types(value):
    """'customer,product' -> ('customer', 'product'); '' = every type."""
    names = [part.strip().lower() for part in str(value or "").split(",") if part.strip()]
    return tuple(parse_type(name) for name in names) or NODE_TYPES


def parse_fy(value):
    """'' or 'all' -> '' (all data up to today); '2627' -> '2627' (FY 2026-27). Anything else: BadRequest."""
    fy = str(value or "").strip().lower()
    if fy in ("", "all"):
        return ""
    if re.fullmatch(r"\d{4}", fy) and int(fy[2:]) == (int(fy[:2]) + 1) % 100:
        return fy
    raise BadRequest("Pick a financial year such as 2627 (FY 2026-27), or all for all data.")


def parse_limit(value, default=DEFAULT_LIMIT, most=MAX_LIMIT):
    if value in (None, ""):
        return default
    try:
        limit = int(str(value).strip())
    except ValueError:
        raise BadRequest("limit must be a whole number.") from None
    if not 1 <= limit <= most:
        raise BadRequest(f"limit must be between 1 and {most}.")
    return limit


def parse_page(offset, limit):
    """(offset, limit) of one search page: offset 0..49 (0 when not given); limit 1..10, or None when not given
    (the search's own size then: 20 for names, 10 for a type word). The caller keeps offset + limit <= 50."""
    if offset in (None, ""):
        start = 0
    else:
        try:
            start = int(str(offset).strip())
        except ValueError:
            raise BadRequest("offset must be a whole number.") from None
        if not 0 <= start < MAX_SEARCH_HITS:
            raise BadRequest(f"offset must be between 0 and {MAX_SEARCH_HITS - 1}: type more to narrow the search.")
    return start, parse_limit(limit, None, PAGE_LIMIT)


def parse_key(kind, value):
    """The key of a node: '16' or 'customer:16' -> 16 for a customer; a name for a category, state ..."""
    key = str(value or "").strip()
    if key.lower().startswith(f"{kind}:"):
        key = key[len(kind) + 1:].strip()
    if not key:
        raise BadRequest("Give the node's id.")
    if kind in ("customer", "product", "sales_person"):
        try:
            number = int(key)
        except ValueError:
            raise BadRequest(f"A {TYPE_NAMES[kind].lower()} id is a number (e.g. {kind}:16).") from None
        if number == -1:
            raise NotFound(f"The {UNKNOWN[kind][1].split(' (')[0]} (-1) is not drawn in the graph: its amount is "
                           "shown as a note on the nodes it belongs to.")
        return number
    if len(key) > 200:
        raise BadRequest("That id is too long.")
    return key


# ------------------------------------------------------------------ the period (all data / a FY)
def _period_sql(fy):
    """(join, where, params) that keep the lines of the period - never a line after today."""
    if fy:
        return CALENDAR, " AND c.financial_year = %s AND f.invoice_date <= CURDATE()", [fy]
    return "", " AND f.invoice_date <= CURDATE()", []


def fy_label(fy):
    return f"FY 20{fy[:2]}-{fy[2:]}"


def period(fy):
    """{fy, label, from, to, so_far, text}: the dates the numbers cover. A FY that is not over counts up to today."""
    def make():
        if fy:
            rows = _rows("SELECT MIN(full_date), MAX(full_date), CURDATE() FROM dim_calendar "
                         "WHERE financial_year = %s AND date_id <> -1", [fy])
            start, end, today = rows[0] if rows else (None, None, None)
            if start is None:
                raise BadRequest(f"{fy_label(fy)} is not in the calendar of the data.")
            if today < start:
                raise BadRequest(f"{fy_label(fy)} has not started yet.")
            so_far = today <= end
            label = fy_label(fy) + (" so far" if so_far else "")
            last = min(end, today)
        else:
            rows = _rows("SELECT MIN(invoice_date), CURDATE() FROM fact_invoice_lines")
            start, today = rows[0] if rows else (None, datetime.date.today())
            start, last, so_far, label = start or today, today, True, "All data up to today"
        return {"fy": fy, "label": label, "from": _day(start), "to": _day(last), "so_far": so_far,
                "text": f"{label} ({_day(start)} to {_day(last)})"}
    return _cached(("period", fy), make)


# ------------------------------------------------------------------ nodes and edges as JSON
def _node(kind, key, label, sub="", amount=None):
    node = {"id": f"{kind}:{key}", "type": kind, "type_name": TYPE_NAMES[kind], "key": str(key),
            "label": str(label or ""), "sub": str(sub or ""), "amount": None, "amount_text": ""}
    if amount is not None:
        node.update(amount=round(_num(amount), 2), amount_text=indian(amount))
    return node


def _edge(source, target, kind, amount=None, quantity=None, invoices=None, **extra):
    edge = {"id": f"{source}|{kind}|{target}", "source": source, "target": target, "type": kind}
    if amount is not None:
        edge.update(amount=round(_num(amount), 2), amount_text=indian(amount))
    if quantity is not None:
        edge.update(quantity=_num(quantity), quantity_text=quantity_text(quantity))
    if invoices is not None:
        edge.update(invoices=int(invoices), invoices_text=indian(invoices, 0))
    edge.update(extra)
    return edge


def _ask(kind, label, when):
    """A question for the Ask page about this node ("Top products bought by Aurora ... in FY 2026-27 so far")."""
    period_words = f" in {when['label']}" if when and when.get("fy") else ""
    return {
        "customer": f"Top products bought by {label}{period_words}",
        "product": f"Top customers of {label}{period_words}",
        "category": f"Top customers for {label}{period_words}",
        "sales_person": f"Top customers handled by {label}{period_words}",
        "state": f"Top customers in {label}{period_words}",
        "sale_type": f"Top {label} customers{period_words}",
        "document": f"What does the {label} say?",
    }[kind]


# ------------------------------------------------------------------ what a node is (its own row)
def _info(kind, key):
    """(label, sub) of a node from its dimension row; NotFound when there is none."""
    if kind == "customer":
        rows = _rows("SELECT customer_name, CONCAT_WS(', ', city, COALESCE(state, country)), customer_group "
                     "FROM dim_customers WHERE customer_id = %s AND customer_id <> -1", [key])
        if rows:
            name, place, group = rows[0]
            return name, " · ".join(part for part in (place, group) if part)
    elif kind == "product":
        rows = _rows("SELECT p.product_description, p.product_code, " + CATEGORY + " "
                     "FROM dim_products p WHERE p.product_id = %s AND p.product_id <> -1", [key])
        if rows:
            name, code, category = rows[0]
            return name, " · ".join(part for part in (code, category) if part)
    elif kind == "category":
        rows = _rows(f"SELECT {CATEGORY}, COUNT(*) FROM dim_products p WHERE p.product_id <> -1 AND {CATEGORY} = %s "
                     f"GROUP BY {CATEGORY}", [key])
        if rows:
            return rows[0][0], f"{indian(rows[0][1], 0)} items"
    elif kind == "sales_person":
        rows = _rows("SELECT sales_person_name, designation FROM dim_sales_people "
                     "WHERE sales_person_id = %s AND sales_person_id <> -1", [key])
        if rows:
            return rows[0][0], rows[0][1] or ""
    elif kind == "state":
        rows = _rows(f"SELECT {STATE}, COUNT(*), MAX(cu.state IS NULL) FROM dim_customers cu "
                     f"WHERE cu.customer_id <> -1 AND {STATE} = %s GROUP BY {STATE}", [key])
        if rows:
            name, customers, foreign = rows[0]
            return name, f"{'Country' if foreign else 'State'} · {indian(customers, 0)} customers"
    elif kind == "sale_type":
        for name in SALE_TYPES:
            if name.lower() == str(key).lower():
                return name, "Sale type"
    raise NotFound(f"No {TYPE_NAMES[kind].lower()} '{key}' in the data.")


# ------------------------------------------------------------------ the numbers of a node and its links
def _totals(kind, key, fy):
    """The node's own numbers in the period, how many neighbours of each type it has, and its Unknown amounts."""
    join, where, params = _period_sql(fy)
    neighbours = [other for _, other, _ in LINKS[kind]]
    counts = [f"COUNT(DISTINCT CASE WHEN {GROUP[o][3]} THEN {GROUP[o][0]} END)" for o in neighbours]
    unknowns = [o for o in neighbours if o in UNKNOWN]
    sums = [f"SUM(CASE WHEN {UNKNOWN[o][0]} THEN f.net_taxable_value ELSE 0 END)" for o in unknowns]
    sql = (f"SELECT SUM(f.net_taxable_value), SUM(f.net_quantity), {INVOICES}, COUNT(*), MIN(f.invoice_date), "
           f"MAX(f.invoice_date), {', '.join(counts + sums)} FROM {FACTS}{join} WHERE {NODE_FILTER[kind]}{where}")
    row = _rows(sql, [key, *params])[0]
    amount, qty, invoices, lines, first, last = row[:6]
    found = {other: int(row[6 + i] or 0) for i, other in enumerate(neighbours)}
    unknown = {other: _num(row[6 + len(neighbours) + i]) for i, other in enumerate(unknowns)}
    return {"amount": _num(amount), "quantity": _num(qty), "invoices": int(invoices or 0), "lines": int(lines or 0),
            "from": _day(first), "to": _day(last), "found": found, "unknown": unknown}


def _links(kind, key, fy, limit):
    """[(edge, neighbour type, out, key, label, sub, amount, quantity, invoices)]: the top `limit` neighbours of
    each edge type by net sales - one UNION query."""
    join, where, params = _period_sql(fy)
    parts, args = [], []
    for edge, other, out in LINKS[kind]:
        group_key, label, sub, keep = GROUP[other]
        grouped = list(dict.fromkeys(part for part in (group_key, label, sub) if part))
        parts.append(
            f"(SELECT '{edge}' AS edge, '{other}' AS other, {group_key} AS k, {label} AS label, "
            f"{sub or chr(39) * 2} AS sub, SUM(f.net_taxable_value) AS amount, SUM(f.net_quantity) AS quantity, "
            f"{INVOICES} AS invoices FROM {FACTS}{join} WHERE {NODE_FILTER[kind]} AND {keep}{where} "
            f"GROUP BY {', '.join(grouped)} ORDER BY amount DESC, label LIMIT %s)")
        args += [key, *params, limit]
    outs = {edge + other: out for edge, other, out in LINKS[kind]}
    return [(edge, other, outs[edge + other], k, label, sub, amount, qty, invoices)
            for edge, other, k, label, sub, amount, qty, invoices in _rows(" UNION ALL ".join(parts), args)]


def _small_totals(fy):
    """{(type, key): net sales} of every category, state, sales person and sale type in the period (kept a while:
    these few nodes are on almost every graph, and adding them up reads all the lines)."""
    def make():
        join, where, params = _period_sql(fy)
        parts, args = [], []
        for kind in ("category", "state", "sales_person", "sale_type"):
            group_key, _, _, keep = GROUP[kind]
            parts.append(f"(SELECT '{kind}' AS kind, {group_key} AS k, SUM(f.net_taxable_value) AS amount "
                         f"FROM {FACTS}{join} WHERE {keep}{where} GROUP BY {group_key})")
            args += params
        return {(kind, str(k)): _num(amount) for kind, k, amount in _rows(" UNION ALL ".join(parts), args, 5000)}
    return _cached(("small", fy), make)


def _big_totals(keys, fy):
    """{(type, key): net sales} of the given customers and products in the period (their own index makes it quick)."""
    join, where, params = _period_sql(fy)
    parts, args = [], []
    for kind, column in (("customer", "f.customer_id"), ("product", "f.product_id")):
        wanted = sorted({int(k) for t, k in keys if t == kind})
        if wanted:
            marks = ", ".join(["%s"] * len(wanted))
            parts.append(f"(SELECT '{kind}' AS kind, {column} AS k, SUM(f.net_taxable_value) AS amount "
                         f"FROM fact_invoice_lines f{join} WHERE {column} IN ({marks}){where} GROUP BY {column})")
            args += [*wanted, *params]
    if not parts:
        return {}
    return {(kind, str(k)): _num(amount) for kind, k, amount in _rows(" UNION ALL ".join(parts), args, 1000)}


def _neighbour_amounts(keys, fy):
    """The net sales of each neighbour node (its size on the graph)."""
    totals = dict(_small_totals(fy)) if any(t in ("category", "state", "sales_person", "sale_type") for t, _ in keys) else {}
    totals.update(_big_totals(keys, fy))
    return totals


# ------------------------------------------------------------------ the company PDFs (documents)
def document_pages():
    """The pages of the company PDFs in pdfs/, read once: [{id, source, title, page, text}] ([] when they
    cannot be read - the graph then simply has no documents)."""
    def make():
        from .lc import pdfs  # the PDF reader is slow to import: only when documents are needed

        try:
            pages = pdfs.load_pdfs()
        except Exception as exc:  # no folder, no PDFs, a broken file
            log.warning("Knowledge graph: the PDFs could not be read: %s", exc)
            return []
        return [{"id": f"{page.metadata['source']}#{page.metadata['page']}", "source": page.metadata["source"],
                 "title": page.metadata["title"], "page": page.metadata["page"],
                 "text": " ".join(page.page_content.split())} for page in pages]
    return _cached(("pdf pages",), make)


SERIES_CODE = re.compile(r"\(([A-Z]{2,3}) series\)")
MODEL_CODE = re.compile(r"\b([A-Z]{2,3}-\d{2,4})\b")


def _series_code(pages, category):
    """'TP' when a PDF writes 'Trochoid pumps (TP series)' for this category; '' when none does."""
    heading = re.compile(_name_pattern(category).pattern + r"\s*\(([A-Z]{2,3}) series\)", re.I)
    for page in pages:
        found = heading.search(page["text"])
        if found:
            return found.group(1)
    return ""


def _name_pattern(name):
    """'Hydraulic motors' -> matches 'hydraulic motor' and 'hydraulic motors' (any case)."""
    base = name[:-1] if name.lower().endswith("s") else name
    return re.compile(r"\b" + re.escape(base) + r"s?\b", re.I)


def _code_pattern(code):
    """'TP' -> matches 'TP series', 'TP-50', 'GP and TP' (capitals only)."""
    return re.compile(r"\b" + re.escape(code) + r"\b")


def _categories():
    """Every category name of the items (not the Unknown row)."""
    return _cached(("categories",), lambda: [row[0] for row in _rows(
        f"SELECT DISTINCT {CATEGORY} FROM dim_products p WHERE p.product_id <> -1 ORDER BY 1")])


def document_links():
    """{category: [(document id, mentions)]}: the PDF pages that name a category ('Trochoid pumps' or
    'Trochoid pump') or its series code from the PDF's own headings ('TP series', 'TP-50'). Matched words only - no
    AI and no vectors, so the same pages come back every time. A category no page names has no entry."""
    def make():
        pages = document_pages()
        if not pages:
            return {}
        links = {}
        for category in _categories():
            patterns = [_name_pattern(category)]
            code = _series_code(pages, category)
            if code:
                patterns.append(_code_pattern(code))
            for page in pages:
                mentions = sum(len(pattern.findall(page["text"])) for pattern in patterns)
                if mentions:
                    links.setdefault(category, []).append((page["id"], mentions))
        return links
    return _cached(("document links",), make)


def _model_documents(text):
    """[(document id, model)]: the PDF pages that list a model code found in a product's description / code."""
    pages = document_pages()
    codes = {code for page in pages for code in SERIES_CODE.findall(page["text"])}
    found = []
    for page in pages:
        for model in sorted(set(MODEL_CODE.findall(page["text"]))):
            if model.split("-")[0] in codes and re.search(r"\b" + re.escape(model) + r"\b", text or ""):
                found.append((page["id"], model))
    return found


def _document_node(page):
    node = _node("document", page["id"], f"{page['title']}, page {page['page']}", page["source"])
    node["text"] = page["text"][:400]
    return node


def _page(key):
    for page in document_pages():
        if page["id"] == key:
            return page
    raise NotFound(f"No document page '{key}' (the company PDFs could not be read, or the page does not exist).")


# ------------------------------------------------------------------ the search box: names, type words, close spellings
def _names():
    """{"entries": {type: [entry]}, "words": {(type, field): {word: [position]}}}: every customer, product,
    category, sales person and state, read once and kept CACHE_SECONDS. An entry is {key, label, sub, find}: find
    is the lower-case text a type word filters on (a customer's name, city and state; a product's description,
    code and category). The words are those of the label ("label") and of find ("find"), for close spellings."""
    def make():
        rows = _rows(
            "(SELECT 'customer' AS kind, customer_id AS k, customer_name AS label, "
            "CONCAT_WS(', ', city, COALESCE(state, country)) AS sub, '' AS more FROM dim_customers "
            "WHERE customer_id <> -1) UNION ALL "
            "(SELECT 'product', product_id, product_description, product_code, "
            "COALESCE(product_category, sap_segment, 'Not classified') FROM dim_products WHERE product_id <> -1) "
            "UNION ALL (SELECT 'category', cat, cat, CONCAT(COUNT(*), ' items'), '' FROM (SELECT "
            "COALESCE(product_category, sap_segment, 'Not classified') AS cat FROM dim_products "
            "WHERE product_id <> -1) x GROUP BY cat) UNION ALL "
            "(SELECT 'sales_person', sales_person_id, sales_person_name, COALESCE(designation, ''), '' "
            "FROM dim_sales_people WHERE sales_person_id <> -1) UNION ALL "
            "(SELECT 'state', st, st, CONCAT(COUNT(*), ' customers'), '' FROM (SELECT COALESCE(state, country) AS st "
            "FROM dim_customers WHERE customer_id <> -1) x WHERE st IS NOT NULL GROUP BY st)", [], NAMES_MAX)
        entries = {kind: [] for kind in NAMED_TYPES}
        words = {(kind, field): {} for kind in NAMED_TYPES for field in ("label", "find")}
        for kind, k, label, sub, more in rows:
            if kind not in entries or label is None:
                continue
            label, sub = str(label), str(sub or "")
            find = label if kind in ("category", "sales_person", "state") else " ".join((label, sub, str(more or "")))
            entry = {"key": str(k), "label": label, "sub": sub, "find": find.lower()}
            position = len(entries[kind])
            entries[kind].append(entry)
            for field, text in (("label", label), ("find", find)):
                for word in set(_words(text)):
                    words[(kind, field)].setdefault(word, []).append(position)
        return {"entries": entries, "words": words}
    return _cached(("names",), make)


def _words(text):
    """The words of a name that close spellings can match, in lower case: 'Trochoid pump CP-107' -> trochoid, pump
    (words of fewer than 3 characters and numbers are left out)."""
    return [word for word in WORD.findall(str(text or "").lower()) if len(word) >= 3 and not word.isdigit()]


def _sales():
    """{(type, key): net sales} of every customer, product, category, state and sales person in all the data up to
    today (the same sums as the graph: SUM(net_taxable_value), credit notes are negative already, never after
    today), kept CACHE_SECONDS - the ranking of a type word."""
    def make():
        join, where, params = _period_sql("")
        parts, args = [], []
        for kind, column in (("customer", "f.customer_id"), ("product", "f.product_id")):
            parts.append(f"(SELECT '{kind}' AS kind, {column} AS k, SUM(f.net_taxable_value) AS amount "
                         f"FROM fact_invoice_lines f{join} WHERE {column} <> -1{where} GROUP BY {column})")
            args += params
        totals = {(kind, str(k)): _num(amount)
                  for kind, k, amount in _rows(" UNION ALL ".join(parts), args, NAMES_MAX)}
        totals.update(_small_totals(""))
        return totals
    return _cached(("sales",), make)


def _type_query(text):
    """('customer', ['tamil']) for 'customers in Tamil', ('sales_person', []) for 'sales people', (None, []) when
    the text does not start with a type word. Small words such as in / of / the are dropped."""
    words = [word.strip(".,;:!?\"'()") for word in text.lower().split()]
    words = [word for word in words if word]
    first = 0
    while first < len(words) - 1 and words[first] in LEAD_WORDS:
        first += 1
    for size in (2, 1):
        head = " ".join(words[first:first + size])
        if len(words) - first >= size and head in TYPE_WORDS:
            rest = [word for word in words[first + size:] if word not in FILLER_WORDS]
            return TYPE_WORDS[head], rest[:MAX_TYPED_WORDS]
    return None, []


def _top(kind, words, offset=0, size=TOP_LIMIT):
    """([node], total): the nodes offset .. offset + size of a type by net sales, and how many there are in all;
    with words, only those whose find text holds every word (a customer's name, city or state; a product's
    description, code or category; a sales person's name). The order is fixed - net sales, then the name, then
    the id - so the pages of "Show more" never repeat or skip a node. Counted from the kept names: no SQL."""
    entries = _names()["entries"][kind]
    if words:
        entries = [entry for entry in entries if all(word in entry["find"] for word in words)]
        if not entries:
            return [], 0
    amounts = _sales()
    ranked = sorted(entries, key=lambda e: (-amounts.get((kind, e["key"]), 0.0), e["label"].lower(),
                                            int(e["key"]) if e["key"].isdigit() else 0, e["key"]))
    return ([_node(kind, e["key"], e["label"], e["sub"], amounts.get((kind, e["key"]), 0.0))
             for e in ranked[offset:offset + size]], len(entries))


def _many(count, kind):
    """'4,982 customers', '1 customer' (Indian commas, as the app writes numbers)."""
    return f"{indian(count, 0)} {TYPE_ONE[kind] if count == 1 else TYPE_PLURALS[kind]}"


def _close(text, kinds, field="label"):
    """Nodes whose name is a close spelling of the text ('aurra' -> Aurora Hydraulics ..., 'rekka' -> Rekha Pillai),
    marked fuzzy: every typed word of 4 characters or more must be near a word of the name (difflib ratio
    FUZZY_CUTOFF or more); the best first (the words, then the whole name), at most FUZZY_PER_TYPE of a type and
    FUZZY_LIMIT in all. Python only: the typed text never goes into SQL here."""
    typed = list(dict.fromkeys(w for w in WORD.findall(text.lower())
                               if len(w) >= FUZZY_MIN_WORD and not w.isdigit() and w not in FILLER_WORDS))
    typed = typed[:MAX_TYPED_WORDS]
    if not typed:
        return []
    names = _names()
    amounts = _sales()
    whole_typed = " ".join(typed)
    found = []
    for kind in kinds:
        entries, index = names["entries"].get(kind, []), names["words"].get((kind, field), {})
        if not entries:
            continue
        vocabulary = list(index)
        per_word = []  # for each typed word: {position: the best ratio of a word of that name}
        for word in typed:
            best = {}
            for match in difflib.get_close_matches(word, vocabulary, n=25, cutoff=FUZZY_CUTOFF):
                ratio = difflib.SequenceMatcher(None, word, match).ratio()
                for position in index[match]:
                    if ratio > best.get(position, 0.0):
                        best[position] = ratio
            per_word.append(best)
        common = set(per_word[0]).intersection(*per_word[1:])
        scored = []
        for position in common:
            entry = entries[position]
            words_score = sum(best[position] for best in per_word) / len(per_word)
            scored.append((round(words_score, 2), amounts.get((kind, entry["key"]), 0.0), entry))
        scored.sort(key=lambda s: (-s[0], -s[1], s[2]["label"].lower()))
        for words_score, amount, entry in scored[:FUZZY_CANDIDATES]:
            # the words first, then the bigger seller; the whole name only breaks a tie ('hydrolic': the
            # category Hydraulic motors before the many hydraulic motor items)
            whole = difflib.SequenceMatcher(None, whole_typed, entry["label"].lower()).ratio()
            found.append((words_score, amount, round(whole, 2), kind, entry))
    found.sort(key=lambda s: (-s[0], -s[1], -s[2], s[4]["label"].lower()))
    # a fair mix: at most FUZZY_PER_TYPE of a type first, then the rest of the best until FUZZY_LIMIT
    per_type, first, later = {}, [], []
    for hit in found:
        per_type[hit[3]] = per_type.get(hit[3], 0) + 1
        (first if per_type[hit[3]] <= FUZZY_PER_TYPE else later).append(hit)
    chosen = (first + later)[:FUZZY_LIMIT]
    chosen.sort(key=lambda s: (-s[0], -s[1], -s[2], s[4]["label"].lower()))
    nodes = []
    for _, amount, _, kind, entry in chosen:
        hit = _node(kind, entry["key"], entry["label"], entry["sub"], amount)
        hit["fuzzy"] = True
        nodes.append(hit)
    return nodes


def _reply(text, results, match="name", match_type="", note="", total=None):
    """The search reply: {q, results} as always, and (optional, for the page) how the nodes were found:
    match = name (the name holds the text) / top (a type word) / type (a type word and text); fuzzy = some
    nodes are close spellings; note = a line for under the box; total = how many nodes the search finds in all
    (left out for close spellings: those are one short list, with no "Show more")."""
    reply = {"q": text, "results": results, "match": match, "match_type": match_type, "note": note,
             "fuzzy": any(hit.get("fuzzy") for hit in results)}
    if total is not None:
        reply["total"] = int(total)
    return reply


def _type_search(text, kind, words, offset=0, size=TOP_LIMIT):
    """The reply to a type word ('customers', 'customer tamil'), or None when the words find nothing (then the
    plain search runs on the whole text: a name may start with a type word). The note counts them all:
    'Top 10 of 4,982 customers by net sales ...'."""
    plural = TYPE_PLURALS[kind]
    hits, total = _top(kind, words, offset, size)
    shown = offset + len(hits)
    if not words:
        if not total:
            return _reply(text, [], "top", kind, f"No {plural} in the data.", total=0)
        if total > shown:
            note = f"Top {shown} of {_many(total, kind)} by net sales (all data up to today){NARROW}"
        else:
            note = f"{'All ' if total > 1 else ''}{_many(total, kind)} by net sales (all data up to today)"
        return _reply(text, hits, "top", kind, note, total)
    said = " ".join(words)
    if total:
        if total > shown:
            note = f"{shown} of {_many(total, kind)} matching \"{said}\" by net sales (all data up to today){NARROW}"
        else:
            note = f"{_many(total, kind)} matching \"{said}\" by net sales (all data up to today)"
        return _reply(text, hits, "type", kind, note, total)
    close = _close(said, [kind], "find")[:TOP_LIMIT]
    if close:  # close spellings come on the first page only (no "Show more" for them)
        return _reply(text, [] if offset else close, "type", kind,
                      f"No {plural} match \"{said}\" exactly - did you mean one of these?")
    return None


# ------------------------------------------------------------------ the three calls of the API
def search(q, types="", offset=None, limit=None):
    """{q, results: [node, ...], match, match_type, note, fuzzy, total}: what the search box shows - 0 AI tokens.
    1. a type word ('customers', 'sales people', 'states'): the top 10 of that type by net sales;
    2. a type word and text ('customer tamil', 'customers in haryana', 'sales person rekha'): that type filtered
       by the text (a customer's name, city or state ...), top by net sales;
    3. else up to 20 nodes whose name (or product code) holds the text, as before;
    4. when that finds fewer than 3: close spellings of the names ('aurra', 'rekka', 'hydrolic'), marked fuzzy.
    total = how many nodes 1-3 find in all; offset / limit (1..10) give the next ones in the same order ("Show
    more"), never past the 50th (offset + limit <= 50). Close spellings are one list, with no total and no pages.
    The typed text only ever goes into SQL as a LIKE parameter (the names and sales are read with fixed SQL and
    kept a while; type words and close spellings are matched in Python)."""
    text = " ".join(str(q or "").split())[:MAX_SEARCH_CHARS]
    if len(text) < MIN_SEARCH:
        raise BadRequest(f"Type at least {MIN_SEARCH} characters to search.")
    wanted = parse_types(types)
    offset, limit = parse_page(offset, limit)
    kind, words = _type_query(text)
    fuzzy_text = text
    if kind in wanted:
        reply = _type_search(text, kind, words, offset, min(limit or TOP_LIMIT, MAX_SEARCH_HITS - offset))
        if reply is not None:
            return reply
        fuzzy_text = " ".join(words)  # the type word itself is not a name to spell
    results, total = _name_search(text, wanted, offset, min(limit or SEARCH_LIMIT, MAX_SEARCH_HITS - offset))
    named = [kind for kind in wanted if kind in NAMED_TYPES]
    if total < FUZZY_BELOW and named:
        seen = {hit["id"] for hit in results}
        close = [hit for hit in _close(fuzzy_text, named) if hit["id"] not in seen][:FUZZY_LIMIT - total]
        if close:  # one list on the first page only, with no total (no "Show more" for close spellings)
            if offset:
                return _reply(text, [])
            return _reply(text, results + close, note=f"No exact match for \"{text}\" - did you mean one of these?"
                          if not results else "")
    shown = offset + len(results)
    note = (f"{indian(shown, 0)} of {indian(total, 0)} matches{NARROW}" if total > shown
            else f"All {indian(total, 0)} matches" if offset and total else "")
    return _reply(text, results, note=note, total=total)


# the name search of each type: (its rows - names that start with the text first, then a-z, then the id, so the
# pages never repeat or skip; its count). Fixed SQL text: the typed text is only ever a LIKE parameter.
NAME_SQL = {
    "customer": (
        "(SELECT 'customer' AS kind, customer_id AS k, customer_name AS label, "
        "CONCAT_WS(', ', city, COALESCE(state, country)) AS sub, customer_name LIKE %s AS starts "
        "FROM dim_customers WHERE customer_id <> -1 AND customer_name LIKE %s "
        "ORDER BY starts DESC, customer_name, customer_id LIMIT %s)",
        "(SELECT 'customer' AS kind, COUNT(*) AS found FROM dim_customers "
        "WHERE customer_id <> -1 AND customer_name LIKE %s)"),
    "product": (
        "(SELECT 'product' AS kind, product_id AS k, product_description AS label, "
        "product_code AS sub, (product_description LIKE %s OR product_code LIKE %s) AS starts "
        "FROM dim_products WHERE product_id <> -1 AND (product_description LIKE %s OR product_code LIKE %s) "
        "ORDER BY starts DESC, product_description, product_id LIMIT %s)",
        "(SELECT 'product' AS kind, COUNT(*) AS found FROM dim_products "
        "WHERE product_id <> -1 AND (product_description LIKE %s OR product_code LIKE %s))"),
    "category": (
        "(SELECT 'category' AS kind, cat AS k, cat AS label, CONCAT(COUNT(*), ' items') AS sub, "
        "cat LIKE %s AS starts FROM (SELECT COALESCE(product_category, sap_segment, 'Not classified') AS cat "
        "FROM dim_products WHERE product_id <> -1) x WHERE cat LIKE %s GROUP BY cat "
        "ORDER BY starts DESC, cat LIMIT %s)",
        "(SELECT 'category' AS kind, COUNT(DISTINCT cat) AS found FROM (SELECT "
        "COALESCE(product_category, sap_segment, 'Not classified') AS cat FROM dim_products "
        "WHERE product_id <> -1) x WHERE cat LIKE %s)"),
    "sales_person": (
        "(SELECT 'sales_person' AS kind, sales_person_id AS k, sales_person_name AS label, "
        "COALESCE(designation, '') AS sub, sales_person_name LIKE %s AS starts FROM dim_sales_people "
        "WHERE sales_person_id <> -1 AND sales_person_name LIKE %s "
        "ORDER BY starts DESC, sales_person_name, sales_person_id LIMIT %s)",
        "(SELECT 'sales_person' AS kind, COUNT(*) AS found FROM dim_sales_people "
        "WHERE sales_person_id <> -1 AND sales_person_name LIKE %s)"),
    "state": (
        "(SELECT 'state' AS kind, st AS k, st AS label, CONCAT(COUNT(*), ' customers') AS sub, "
        "st LIKE %s AS starts FROM (SELECT COALESCE(state, country) AS st FROM dim_customers "
        "WHERE customer_id <> -1) x WHERE st LIKE %s GROUP BY st ORDER BY starts DESC, st LIMIT %s)",
        "(SELECT 'state' AS kind, COUNT(DISTINCT st) AS found FROM (SELECT COALESCE(state, country) AS st "
        "FROM dim_customers WHERE customer_id <> -1) x WHERE st LIKE %s)"),
}


def _name_search(text, wanted, offset=0, size=SEARCH_LIMIT):
    """([node], total): the nodes offset .. offset + size of those whose name (or product code) holds the text -
    a fair mix of the types, names that start with it first - and how many there are in all. Each type reads only
    its first offset + size rows (at most 50); only a type that fills them is counted with a COUNT query (the
    same LIKE parameter), so a small search costs no extra query. The text only ever goes in as a LIKE parameter."""
    like, start = f"%{escape_like(text)}%", f"{escape_like(text)}%"
    upto = offset + size
    sql_kinds = [kind for kind in NAME_SQL if kind in wanted]
    parts, args = [], []
    for kind in sql_kinds:
        parts.append(NAME_SQL[kind][0])
        args += ([start, start, like, like] if kind == "product" else [start, like]) + [upto]
    found = {kind: [] for kind in wanted}
    if parts:
        for kind, k, label, sub, _ in _rows(" UNION ALL ".join(parts), args):
            found[kind].append(_node(kind, k, label, sub))
    counts = {kind: len(found[kind]) for kind in sql_kinds}
    needle = text.lower()
    if "sale_type" in wanted:
        found["sale_type"] = [_node("sale_type", name, name, "Sale type") for name in SALE_TYPES if needle in name.lower()]
        counts["sale_type"] = len(found["sale_type"])
    if "document" in wanted:
        pages = [page for page in document_pages() if needle in page["title"].lower() or needle in page["source"].lower()]
        found["document"] = [_document_node(page) for page in pages[:upto]]
        counts["document"] = len(pages)
    full = [kind for kind in sql_kinds if counts[kind] >= upto]  # there may be more of these: count them
    if full:
        count_args = []
        for kind in full:
            count_args += [like, like] if kind == "product" else [like]
        for kind, number in _rows(" UNION ALL ".join(NAME_SQL[kind][1] for kind in full), count_args):
            counts[kind] = max(counts[kind], int(number or 0))
    # a fair mix: one of each type in turn. Each list is in a fixed order, so the first n of the mix are the
    # same whatever longer lists are read - the pages never repeat or skip a node
    mixed, queues = [], [list(found[kind]) for kind in wanted if found.get(kind)]
    while queues and len(mixed) < upto:
        for queue in list(queues):
            if len(mixed) < upto:
                mixed.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return mixed[offset:upto], sum(counts.values())


def node(kind, key, fy="", limit=DEFAULT_LIMIT):
    """{node, period, neighbours, edges, groups, notes}: one node with its totals in the period and its top
    `limit` neighbours of each edge type (by net sales), the edges carrying their numbers raw and as text."""
    kind = parse_type(kind)
    fy = parse_fy(fy)
    limit = parse_limit(limit)
    key = parse_key(kind, key)
    if kind == "document":
        return _document_reply(key, fy)
    label, sub = _info(kind, key)
    when = period(fy)
    totals = _totals(kind, key, fy)
    center = _node(kind, key, label, sub, totals["amount"])
    center.update(quantity=totals["quantity"], quantity_text=quantity_text(totals["quantity"]),
                  invoices=totals["invoices"], invoices_text=indian(totals["invoices"], 0), lines=totals["lines"],
                  data_from=totals["from"], data_to=totals["to"], ask=_ask(kind, label, when))
    links = _links(kind, key, fy, limit) if totals["lines"] else []
    amounts = _neighbour_amounts({(other, str(k)) for _, other, _, k, *_ in links}, fy) if links else {}
    neighbours, edges, seen = [], [], set()
    for edge, other, out, k, other_label, other_sub, amount, qty, invoices in links:
        neighbour = _node(other, k, other_label, other_sub, amounts.get((other, str(k)), amount))
        if neighbour["id"] not in seen:
            seen.add(neighbour["id"])
            neighbours.append(neighbour)
        source, target = (center["id"], neighbour["id"]) if out else (neighbour["id"], center["id"])
        edges.append(_edge(source, target, edge, amount, qty, invoices))
    groups = []
    for edge, other, _ in LINKS[kind]:
        shown = sum(1 for link in links if link[0] == edge and link[1] == other)
        groups.append({"edge": edge, "type": other, "shown": shown, "total": totals["found"][other]})
    notes = []
    if not totals["lines"]:
        notes.append(f"No sales lines in {when['text']}.")
    for other, amount in totals["unknown"].items():
        if amount:
            notes.append(f"{UNKNOWN[other][1]}: {indian(amount)} is in the total but not drawn.")
    _add_documents(kind, key, center, neighbours, edges, groups)
    return {"node": center, "period": when, "neighbours": neighbours, "edges": edges, "groups": groups,
            "notes": notes}


def _add_documents(kind, key, center, neighbours, edges, groups):
    """COVERED_BY edges to the PDF pages of a category, or of a product (its model code, else its category)."""
    if kind not in ("category", "product"):
        return
    links = document_links()
    pages = {page["id"]: page for page in document_pages()}
    found = []
    if kind == "category":
        found = [(doc, {"mentions": mentions}) for doc, mentions in links.get(key, [])]
    else:
        category = center["sub"].split(" · ")[-1] if center["sub"] else ""
        direct = _model_documents(center["label"] + " " + center["sub"])
        found = [(doc, {"model": model}) for doc, model in direct]
        if not found:
            found = [(doc, {"mentions": mentions, "through": category}) for doc, mentions in links.get(category, [])]
    for doc, extra in found:
        if doc in pages:
            neighbours.append(_document_node(pages[doc]))
            edges.append(_edge(center["id"], f"document:{doc}", "COVERED_BY", **extra))
    groups.append({"edge": "COVERED_BY", "type": "document", "shown": len(found), "total": len(found)})


def _document_reply(key, fy):
    """A PDF page: the categories (with their sales) that it names."""
    page = _page(key)
    when = period(fy)
    center = _document_node(page)
    center["ask"] = _ask("document", page["title"], when)
    categories = [(category, mentions) for category, docs in document_links().items()
                  for doc, mentions in docs if doc == key]
    amounts = _small_totals(fy) if categories else {}
    neighbours = [_node("category", name, name, "", amounts.get(("category", name), 0.0)) for name, _ in categories]
    edges = [_edge(f"category:{name}", center["id"], "COVERED_BY", mentions=mentions) for name, mentions in categories]
    notes = [] if categories else ["No product category is named on this page."]
    return {"node": center, "period": when, "neighbours": neighbours, "edges": edges,
            "groups": [{"edge": "COVERED_BY", "type": "category", "shown": len(edges), "total": len(edges)}],
            "notes": notes}


def similar(customer_id, fy="", limit=SIMILAR_LIMIT):
    """{customer, period, products, similar: [...], edges}: the customers who buy the most of the same products as
    this one in the period ("who buys like Aurora?"). shared = products both bought; score = shared / all the
    products either bought (1.0 = exactly the same products)."""
    fy = parse_fy(fy)
    limit = parse_limit(limit, SIMILAR_LIMIT, MAX_SIMILAR)
    key = parse_key("customer", customer_id)
    label, sub = _info("customer", key)
    when = period(fy)
    join, where, params = _period_sql(fy)
    mine = [row[0] for row in _rows(f"SELECT DISTINCT f.product_id FROM fact_invoice_lines f{join} "
                                    f"WHERE f.customer_id = %s AND f.product_id <> -1{where}", [key, *params])]
    center = _node("customer", key, label, sub)
    reply = {"customer": center, "period": when, "products": len(mine), "similar": [], "edges": []}
    if not mine:
        return reply
    marks = ", ".join(["%s"] * len(mine))
    candidates = _rows(
        f"SELECT f.customer_id, cu.customer_name, {STATE}, COUNT(DISTINCT f.product_id) AS shared, "
        f"SUM(f.net_taxable_value) AS amount FROM fact_invoice_lines f "
        f"JOIN dim_customers cu ON cu.customer_id = f.customer_id{join} "
        f"WHERE f.product_id IN ({marks}) AND f.customer_id <> %s AND f.customer_id <> -1{where} "
        f"GROUP BY f.customer_id, cu.customer_name, {STATE} ORDER BY shared DESC, amount DESC LIMIT %s",
        [*mine, key, *params, CANDIDATES])
    if not candidates:
        return reply
    ids = [row[0] for row in candidates]
    marks = ", ".join(["%s"] * len(ids))
    theirs = {row[0]: (int(row[1] or 0), _num(row[2])) for row in _rows(
        f"SELECT f.customer_id, COUNT(DISTINCT CASE WHEN f.product_id <> -1 THEN f.product_id END), "
        f"SUM(f.net_taxable_value) FROM fact_invoice_lines f{join} WHERE f.customer_id IN ({marks}){where} "
        f"GROUP BY f.customer_id", [*ids, *params])}
    found = []
    for other, name, place, shared, amount in candidates:
        products, total = theirs.get(other, (int(shared), 0.0))
        score = score_of(int(shared), len(mine), products)
        found.append((-int(shared), -score, name, other, place, int(shared), products, amount, total, score))
    found.sort()
    for *_, name, other, place, shared, products, amount, total, score in found[:limit]:
        friend = _node("customer", other, name, place, total)
        friend.update(shared_products=shared, products=products, score=round(score, 3),
                      score_text=f"{round(100 * score)}%",
                      shared_amount=round(_num(amount), 2), shared_amount_text=indian(amount))
        reply["similar"].append(friend)
        reply["edges"].append(_edge(center["id"], friend["id"], "BUYS_LIKE", shared_products=shared,
                                    score=friend["score"], score_text=friend["score_text"]))
    return reply


def score_of(shared, mine, theirs):
    """The overlap of two customers' products: shared / (all the products either bought)."""
    return shared / max(1, mine + theirs - shared)
