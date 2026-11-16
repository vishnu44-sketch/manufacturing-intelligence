"""The SQL of an answer told in plain English, for business users ("how did you get this?").

describe_sql(sql) reads one MySQL SELECT on the ai_gold star schema with sqlglot and gives back
3-8 short sentences in the order the database does the work, e.g.
    "Took the invoice lines (sales, credit and debit notes)."
    "Matched each line to its date in the calendar."
    "Kept the NOP sales month Aug 2026."
    "Added up the net value before GST (net sales) for each customer."
    "Showed the top 5 customers by net sales."
No AI is used (0 tokens): the words come from the small tables below (docs/data_dictionary.md
and docs/business_rules.md say what the tables and columns mean). A SQL it cannot read gives []
- the caller then points to Show SQL. It never raises.
"""
import re

import sqlglot
from sqlglot import exp

MAX_SENTENCES = 10
SAFETY_LIMIT = 500  # the app adds LIMIT 500 to every SQL - not worth telling the user

# what each table holds (used in "Took ...")
TABLE_WORDS = {
    "fact_invoice_lines": "the invoice lines (sales, credit and debit notes)",
    "fact_sales_order_lines": "the sales order lines",
    "fact_stock_ledger": "the stock ledger (stock balances and movements)",
    "dim_calendar": "the calendar (one row per day)",
    "dim_customers": "the customer list",
    "dim_products": "the product list",
    "dim_sales_people": "the list of sales people",
    "dim_fx_rates": "the INR to JPY exchange rates",
    "dim_tax_codes": "the GST tax codes",
    "dim_stock_movement_types": "the kinds of stock ledger row",
    "load_log": "the data load history",
}
# the short name of the table (used in "a list made from ...")
TABLE_SHORT = {
    "fact_invoice_lines": "the invoice lines",
    "fact_sales_order_lines": "the sales order lines",
    "fact_stock_ledger": "the stock ledger",
    "dim_calendar": "the calendar",
    "dim_customers": "the customer list",
    "dim_products": "the product list",
    "dim_sales_people": "the sales people",
    "dim_fx_rates": "the exchange rates",
    "dim_tax_codes": "the GST tax codes",
    "dim_stock_movement_types": "the kinds of stock row",
    "load_log": "the load history",
}
# what one row of the table is called (used in "Matched each line ...", "Kept the lines ...")
TABLE_UNIT = {
    "fact_invoice_lines": "line",
    "fact_sales_order_lines": "order line",
    "fact_stock_ledger": "stock row",
    "dim_calendar": "day",
    "dim_customers": "customer",
    "dim_products": "product",
    "dim_sales_people": "sales person",
    "dim_fx_rates": "rate month",
    "dim_tax_codes": "tax code",
    "dim_stock_movement_types": "kind of stock row",
    "load_log": "load row",
}
# what a joined table adds to each row (used in "Matched each line to ...")
JOIN_WORDS = {
    "fact_invoice_lines": "its invoice lines",
    "fact_sales_order_lines": "its sales order lines",
    "fact_stock_ledger": "its stock rows",
    "dim_customers": "its customer",
    "dim_products": "its product",
    "dim_sales_people": "its sales person",
    "dim_fx_rates": "its INR to JPY exchange rate",
    "dim_tax_codes": "its GST tax code",
    "dim_stock_movement_types": "its kind of stock row",
}
# which date of the row the calendar is matched on
CALENDAR_JOIN_WORDS = {
    "invoice_date_id": "its date in the calendar",
    "note_date_id": "its note date in the calendar",
    "order_date_id": "its order date in the calendar",
    "delivery_date_id": "its delivery date in the calendar",
    "report_date_id": "its stock report date in the calendar",
    "posting_date_id": "its posting date in the calendar",
}

# column names in plain words
COLUMN_WORDS = {
    "net_taxable_value": "net value before GST (net sales)",
    "taxable_value": "taxable value as printed",
    "net_quantity": "quantity",
    "quantity": "quantity",
    "unit_price": "unit price",
    "discount_pct": "discount %",
    "nop_sales_month": "NOP sales month",
    "nop_sales_month_name": "NOP sales month",
    "nop_sales_month_no": "NOP sales month",
    "nop_sales_period_no": "NOP sales month",
    "nop_sales_period_start": "start of the NOP sales month",
    "nop_sales_period_end": "end of the NOP sales month",
    "nop_sales_year": "NOP sales year",
    "financial_year": "financial year",
    "financial_year_label": "financial year",
    "fiscal_period": "month of the financial year",
    "fiscal_quarter": "quarter of the financial year",
    "month_year": "calendar month",
    "month_name": "calendar month",
    "month_short": "calendar month",
    "month_no": "calendar month",
    "calendar_year": "calendar year",
    "calendar_quarter": "calendar quarter",
    "full_date": "day",
    "date_id": "date",
    "day_name": "weekday",
    "customer_id": "customer",
    "customer_name": "customer",
    "customer_code": "customer code",
    "customer_group": "customer group",
    "customer_type": "customer type (OEM / after-market)",
    "country_segment": "country segment",
    "product_id": "product",
    "product_description": "product",
    "product_code": "product code",
    "product_category": "product category",
    "product_segment_name": "product segment",
    "item_group": "item group",
    "item_description": "item",
    "sales_person_id": "sales person",
    "sales_person_name": "sales person",
    "invoice_date": "invoice date",
    "order_date": "order date",
    "delivery_date": "delivery date",
    "report_date": "stock report date",
    "posting_date": "posting date",
    "note_date": "note date",
    "so_date": "sales order date",
    "invoice_number": "invoice",
    "so_number": "sales order",
    "note_number": "credit / debit note",
    "original_invoice_number": "original invoice",
    "document_type": "document type",
    "sale_type": "sale type",
    "status": "order status",
    "total_amount": "order value before GST",
    "tax_total": "GST",
    "freight_amount": "freight",
    "net_line_total_incl_gst": "value including GST",
    "line_total_incl_gst": "line total including GST",
    "igst_amount": "IGST",
    "cgst_amount": "CGST",
    "sgst_amount": "SGST",
    "cess_amount": "GST cess",
    "cumulative_value": "stock value",
    "cumulative_qty": "stock quantity",
    "transaction_value": "movement value",
    "unit_cost": "unit cost",
    "movement_type": "kind of stock row",
    "movement_type_id": "kind of stock row",
    "row_kind": "balance or movement",
    "exchange_rate": "exchange rate",
    "rate_month": "rate month",
    "fx_rate_id": "exchange rate",
    "tax_code_id": "tax code",
    "tax_code": "tax code",
    "sales_order_line_id": "line order",
    "invoice_line_id": "line order",
    "stock_ledger_id": "stock row",
    "run_id": "load run",
    "loaded_at": "load time",
}
# a shorter name for a measure (used in "the top 5 customers by net sales")
MEASURE_SHORT = {
    "net_taxable_value": "net sales",
    "total_amount": "order value",
    "cumulative_value": "stock value",
    "net_quantity": "quantity",
    "transaction_value": "movement value",
}
# what COUNT(DISTINCT column) counts
COUNT_WORDS = {
    "invoice_number": "invoices",
    "so_number": "sales orders",
    "note_number": "credit / debit notes",
    "customer_id": "customers",
    "customer_name": "customers",
    "product_id": "products",
    "product_code": "products",
    "sales_person_id": "sales people",
    "report_date": "stock reports",
    "nop_sales_month": "NOP sales months",
    "full_date": "days",
}
# the Unknown (-1) row of each key
UNKNOWN_WORDS = {
    "customer_id": "customer",
    "product_id": "product",
    "sales_person_id": "sales person",
    "fx_rate_id": "exchange rate",
    "tax_code_id": "tax code",
    "movement_type_id": "kind of stock row",
    "date_id": "date",
}
# columns that hold a time (sorted oldest / newest first)
TIME_COLUMNS = {
    "invoice_date", "order_date", "delivery_date", "report_date", "posting_date", "note_date",
    "so_date", "system_date", "full_date", "start_date", "end_date", "original_invoice_date",
    "nop_sales_month", "nop_sales_period_no", "nop_sales_period_start", "nop_sales_period_end",
    "nop_sales_year", "financial_year", "financial_year_label", "month_year", "month_no",
    "fiscal_period", "calendar_year", "date_id", "rate_month", "run_id", "loaded_at", "week_of_year",
}
DATE_COLUMNS = {
    "invoice_date", "order_date", "delivery_date", "report_date", "posting_date", "note_date",
    "so_date", "system_date", "full_date", "start_date", "end_date", "original_invoice_date",
    "nop_sales_period_start", "nop_sales_period_end", "loaded_at",
}
# how "Kept the lines ___ up to today" reads for each date column
DATE_VERBS = {
    "invoice_date": "dated",
    "full_date": "dated",
    "order_date": "ordered",
    "delivery_date": "due for delivery",
    "posting_date": "posted",
    "note_date": "with a note dated",
    "so_date": "with a sales order dated",
    "nop_sales_period_end": "whose NOP sales month ended",
    "nop_sales_period_start": "whose NOP sales month started",
}
# columns whose LIKE '%x%' means "names containing x"
LIKE_WORDS = {
    "customer_name": "customer names",
    "product_description": "product names",
    "item_description": "item names",
    "sales_person_name": "sales person names",
    "product_code": "product codes",
    "customer_code": "customer codes",
    "invoice_number": "invoice numbers",
    "product_category": "product categories",
}
# fixed meanings of some column = 'value' filters
VALUE_WORDS = {
    ("document_type", "INVOICE"): "invoices (not credit or debit notes)",
    ("document_type", "CREDIT_NOTE"): "credit notes",
    ("document_type", "DEBIT_NOTE"): "debit notes",
    ("movement_type", "Closing balance"): "closing balance rows (stock on hand)",
    ("movement_type", "Opening Balance"): "opening balance rows",
    ("movement_type", "COGS"): "COGS rows (goods sold)",
    ("movement_type", "Purchase"): "purchase rows",
    ("row_kind", "BALANCE"): "balance rows",
    ("row_kind", "MOVEMENT"): "stock movement rows",
    ("customer_type", "AFT"): "after-market (AFT) sales",
    ("customer_type", "OEM"): "OEM sales",
}
# the short form (used in "split into invoices, credit notes and debit notes")
VALUE_SHORT = {
    ("document_type", "INVOICE"): "invoices",
    ("document_type", "CREDIT_NOTE"): "credit notes",
    ("document_type", "DEBIT_NOTE"): "debit notes",
}
WORD_PARTS = {
    "inr": "(INR)", "jpy": "(JPY)", "pct": "%", "qty": "quantity", "no": "number", "gst": "GST",
    "igst": "IGST", "cgst": "CGST", "sgst": "SGST", "fy": "FY", "nop": "NOP", "sap": "SAP",
    "cogs": "COGS", "oem": "OEM", "aft": "AFT", "hsn": "HSN", "incl": "including",
    "id": "", "avg": "average", "num": "number", "cnt": "count", "amt": "amount",
}
# names given to ROW_NUMBER() / RANK() results
RANK_NAMES = {"rn", "rnk", "rank", "rank_no", "row_no", "row_num", "rownum", "position"}
# group columns that only describe the NOP sales month next to it
GROUP_EXTRAS = {"start of the NOP sales month", "end of the NOP sales month", "period from", "period to",
                "period start", "period end"}
# the order of the verbs in the "Added up ..., counted ... and found ..." sentence
VERB_ORDER = {"added up": 0, "counted": 1, "averaged": 2, "worked out": 3, "found": 4, "listed": 5,
              "ranked": 6}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def describe_sql(sql):
    """3-8 short plain-English sentences that tell what the SQL does; [] when it cannot be read."""
    try:
        return _describe(sql)
    except Exception:  # noqa: BLE001 - the words are a help, never a reason for an error page
        return []


def _describe(sql):
    if not isinstance(sql, str) or not sql.strip():
        return []
    tree = sqlglot.parse_one(sql, read="mysql")
    if isinstance(tree, exp.Subquery):
        tree = tree.this
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        return []
    sentences = []
    for sentence in _Describer().query(tree):
        sentence = _tidy(sentence)
        if sentence and sentence not in sentences:
            sentences.append(sentence)
    return sentences[:MAX_SENTENCES]


# ---------- small word helpers ----------

def _tidy(sentence):
    sentence = re.sub(r"\s+", " ", sentence or "").strip()
    sentence = re.sub(r"\s+([,.;:)])", r"\1", sentence)
    if not sentence:
        return ""
    sentence = sentence[0].upper() + sentence[1:]
    if sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def _lower_first(text):
    """'Kept the ...' -> 'kept the ...' (but 'NOP ...' stays)."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def _and(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _or(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _plural(words):
    if words.endswith(")"):  # "customer type (OEM / after-market)" -> pluralise the part before
        head, _, tail = words.partition(" (")
        return _plural(head) + " (" + tail
    if words.endswith("person"):
        return words[:-6] + "people"
    if words.endswith("y") and not words.endswith(("ay", "ey", "oy")):
        return words[:-1] + "ies"
    if words.endswith(("s", "x", "ch", "sh")):
        return words + "es"
    return words + "s"


def _name_words(name):
    """snake_case -> words: 'net_sales_inr' -> 'net sales (INR)'."""
    name = (name or "").strip().strip("`").lower()
    if name in COLUMN_WORDS:
        return COLUMN_WORDS[name]
    parts = [WORD_PARTS.get(p, p) for p in name.split("_") if p]
    return " ".join(p for p in parts if p) or name


def _list_words(name):
    """The name of a WITH list in words; a one-letter name ('v') says nothing, so 'values'."""
    name = (name or "").strip("`")
    if len(name) < 2 or (len(name) == 2 and name.lower() not in WORD_PARTS):
        return "values"
    return _name_words(name)


def _is_date_name(name):
    return name in DATE_COLUMNS or name.endswith("_date")


def _col_words(column):
    return _name_words(column.name if isinstance(column, exp.Column) else str(column))


def _fy(value):
    """'2627' -> 'FY 2026-27'."""
    if re.fullmatch(r"\d{4}", value or ""):
        return f"FY 20{value[:2]}-{value[2:]}"
    return value


def _date(value):
    """'2026-09-20' -> '20-Sep-2026'; anything else unchanged."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{MONTHS[int(m.group(2)) - 1]}-{m.group(1)}"
    return value


def _unwrap(node):
    """Take away what does not change the meaning: ROUND, COALESCE(x, 0), brackets, CAST, alias."""
    while True:
        if isinstance(node, (exp.Alias, exp.Paren, exp.Cast, exp.TryCast)):
            node = node.this
        elif isinstance(node, (exp.Round, exp.Coalesce, exp.Abs)) or (
                isinstance(node, exp.Anonymous) and node.name.upper() in {"IFNULL", "ROUND"}):
            node = node.this if not isinstance(node, exp.Anonymous) else node.expressions[0]
        elif isinstance(node, exp.Neg):
            node = node.this
        else:
            return node


def _first_column(node):
    if isinstance(node, exp.Column):
        return node
    return next(node.find_all(exp.Column), None) if node is not None else None


def _is_today(node):
    return isinstance(node, (exp.CurrentDate, exp.CurrentTimestamp, exp.CurrentDatetime)) or (
        isinstance(node, (exp.Anonymous, exp.Func)) and getattr(node, "name", "").upper()
        in {"CURDATE", "NOW", "CURRENT_DATE", "SYSDATE"})


def _has_agg(node):
    return any(isinstance(n, exp.AggFunc) and not n.find_ancestor(exp.Subquery, exp.Window)
               for n in node.walk()) if node is not None else False


# ---------- the describer ----------

class _Describer:
    def __init__(self):
        self.lists = set()   # names of the WITH lists (and FROM subqueries) seen so far
        self.list_count = 0

    # one query: its WITH lists first, then the query itself
    def query(self, node):
        sentences = []
        with_ = node.args.get("with_")
        if with_:
            ctes = list(with_.expressions)
            self.lists.update(c.alias.lower() for c in ctes)
            # many lists: keep room for the main query
            for number, cte in enumerate(ctes):
                if number >= 5:
                    rest = [_list_words(c.alias) for c in ctes[number:]]
                    more = "1 more list" if len(rest) == 1 else f"{len(rest)} more lists"
                    sentences.append(f"Then made {more} from those ({_and(rest)}).")
                    break
                sentences.append(self.list_sentence(cte.this, cte.alias))
        if isinstance(node, exp.SetOperation):
            sentences.extend(self.union(node))
        elif isinstance(node, exp.Select):
            sentences.extend(self.select(node))
        return sentences

    def list_sentence(self, node, name):
        """One sentence for a helper list (a WITH part or a subquery in FROM)."""
        first = self.list_count == 0
        self.list_count += 1
        words = _list_words(name)
        intro = "First made a list of" if first else "Then made a list of"
        if isinstance(node, exp.Subquery):
            node = node.this
        if isinstance(node, exp.SetOperation):
            parts = self.union_parts(node)
            return f"{intro} {words} by putting {len(parts)} parts together"
        if not isinstance(node, exp.Select):
            return f"{intro} {words}"
        parts = self.select_parts(node)
        source = parts["source_short"]
        # short: at most 2 filters, what was worked out, and the order (the columns only when
        # nothing else says what the list is)
        body = list(parts["kept"][:2])
        if parts["agg"]:
            body.append(parts["agg"])
            body.extend(parts["split"][:1])
        elif parts["shown"] and not (body and parts["order"]):
            body.append(parts["shown"])
        if parts["order"]:
            body.append(parts["order"])
        text = f"{intro} {words}" + (f" from {source}" if source else "")
        if body:
            text += ": " + "; ".join(_lower_first(b.rstrip(".")) for b in body[:4])
        return text

    def union_parts(self, node):
        parts = []
        for side in (node.left, node.right):
            if isinstance(side, exp.Subquery):
                side = side.this
            if isinstance(side, exp.SetOperation):
                parts.extend(self.union_parts(side))
            else:
                parts.append(side)
        return parts

    def union(self, node):
        parts = self.union_parts(node)
        sentences = [f"Put the results of {len(parts)} parts together, one below the other."]
        for number, part in enumerate(parts[:4], start=1):
            if not isinstance(part, exp.Select):
                continue
            p = self.select_parts(part)
            body = [p["took"]] + p["kept"] + ([p["agg"]] if p["agg"] else [p["shown"]] if p["shown"] else [])
            sentences.append(f"Part {number}: " + "; ".join(_lower_first(b.rstrip(".")) for b in body if b))
        if node.args.get("order"):
            sentences.append("Then sorted the result.")
        return sentences

    def select(self, node):
        p = self.select_parts(node)
        sentences = list(p["before"])
        sentences.append(p["took"])
        if p["joins"]:
            sentences.append(p["joins"])
        sentences.extend(p["kept"])
        if p["agg"]:
            sentences.append(p["agg"])
        if p["split"]:
            sentences.extend(p["split"])
        if p["shown"] and not p["agg"]:
            sentences.append(p["shown"])
        if p["lookups"]:
            sentences.append(p["lookups"])
        sentences.extend(p["having"])
        if p["order"]:
            sentences.append(p["order"])
        return [s for s in sentences if s]

    # ---- the parts of one SELECT ----
    def select_parts(self, node):
        ctx = {"alias": {}, "base": None, "unit": "row", "select_alias": {}}
        before = []
        source = node.args.get("from_") or node.args.get("from")
        took, source_short = "", ""
        if source is not None:
            src = source.this
            took, source_short = self.source_words(src, ctx, before, base=True)
        joins = self.joins(node.args.get("joins") or [], ctx, before)
        for e in node.expressions:
            if isinstance(e, exp.Alias):
                ctx["select_alias"][e.alias.lower()] = e.this

        kept = []
        for on_cond in ctx.pop("join_filters", []):
            kept.extend(self.condition(on_cond, ctx))
        where = node.args.get("where")
        if where is not None:
            kept.extend(self.condition(where.this, ctx))

        group = node.args.get("group")
        group_words = self.group_words(group.expressions if group else [], ctx)
        agg, split, shown, lookups = self.measures(node, ctx, group_words)
        if node.args.get("distinct") and not group_words:
            shown = shown.replace("Showed the", "Listed each different", 1) if shown else shown
            if shown:
                shown += ", once each"
        having = []
        if node.args.get("having") is not None:
            having_ctx = dict(ctx, unit="group", row_unit=ctx.get("unit"),
                              group=group_words[0] if len(group_words) == 1 else "group")
            for sentence in self.condition(node.args["having"].this, having_ctx):
                having.append(sentence.replace("Kept", "Then kept", 1).replace("Left out", "Then left out", 1))
        order = self.order(node, ctx, group_words)
        return {"before": before, "took": took, "source_short": source_short, "joins": joins,
                "kept": kept, "agg": agg, "split": split, "shown": shown, "lookups": lookups,
                "having": having, "order": order}

    def source_words(self, src, ctx, before, base=False):
        """'Took ...' for the FROM part; also fills the alias map."""
        if isinstance(src, exp.Subquery):
            alias = src.alias or ""
            before.append(self.list_sentence(src.this, alias))
            if alias:
                ctx["alias"][alias.lower()] = alias.lower()
                self.lists.add(alias.lower())
            if base:
                ctx["base"], ctx["unit"] = alias.lower(), "row"
            return "Took that list", "that list"
        if not isinstance(src, exp.Table):
            return "", ""
        name = src.name.lower()
        alias = (src.alias or src.name).lower()
        ctx["alias"][alias] = name
        ctx["alias"][name] = name
        if base:
            ctx["base"] = name
            ctx["unit"] = TABLE_UNIT.get(name, "row")
        if name in self.lists:
            return f"Took the list of {_list_words(name)}", f"the list of {_list_words(name)}"
        return (f"Took {TABLE_WORDS.get(name, 'the ' + _name_words(name) + ' table')}",
                TABLE_SHORT.get(name, "the " + _name_words(name)))

    def joins(self, joins, ctx, before):
        targets, left_kept = [], False
        ctx["join_filters"] = []
        for join in joins:
            src = join.this
            if isinstance(src, exp.Subquery):
                self.source_words(src, ctx, before)
                targets.append("that list")
                continue
            if not isinstance(src, exp.Table):
                continue
            name = src.name.lower()
            alias = (src.alias or src.name).lower()
            ctx["alias"][alias] = name
            ctx["alias"][name] = name
            on = join.args.get("on")
            keys = []
            for cond in self._and_parts(on):
                if (isinstance(cond, exp.EQ) and isinstance(cond.this, exp.Column)
                        and isinstance(cond.expression, exp.Column)):
                    keys.append(cond)
                else:
                    ctx["join_filters"].append(cond)
            if name in self.lists:
                if join.args.get("kind", "").upper() == "CROSS" or not on:
                    targets.append(f"the {_list_words(name)} values")
                else:
                    targets.append(f"the {_list_words(name)} list")
            elif name == "dim_calendar":
                word = "its date in the calendar"
                for key in keys:
                    for col in (key.this, key.expression):
                        if col.name.lower() in CALENDAR_JOIN_WORDS:
                            word = CALENDAR_JOIN_WORDS[col.name.lower()]
                targets.append(word)
            else:
                targets.append(JOIN_WORDS.get(name, TABLE_SHORT.get(name, "the " + _name_words(name))))
            if join.args.get("side", "").upper() == "LEFT":
                left_kept = True
        if not targets:
            return ""
        unit = ctx["unit"]
        sentence = f"Matched each {unit} to {_and(targets)}"
        if left_kept:
            sentence += f" (also keeping {_plural(unit)} with none)"
        return sentence

    @staticmethod
    def _and_parts(cond):
        if cond is None:
            return []
        if isinstance(cond, exp.Paren):
            return _Describer._and_parts(cond.this)
        if isinstance(cond, exp.And):
            return _Describer._and_parts(cond.this) + _Describer._and_parts(cond.expression)
        return [cond]

    # ---- WHERE / HAVING conditions ----
    def condition(self, cond, ctx):
        sentences = []
        for part in self._and_parts(cond):
            phrase = self.phrase(part, ctx)
            if phrase:
                sentences.append(phrase)
        return sentences

    def phrase(self, cond, ctx):
        """One condition -> 'Kept ...' / 'Left out ...' (None when it says nothing useful)."""
        unit = _plural(ctx.get("unit") or "row")
        if isinstance(cond, exp.Paren):
            return self.phrase(cond.this, ctx)
        if isinstance(cond, exp.Or):
            pieces = []
            for side in self._or_parts(cond):
                sub = self.phrase(side, ctx)
                if not sub or not sub.startswith("Kept "):
                    return f"Kept the {unit} that meet one of {len(self._or_parts(cond))} conditions"
                piece = sub[5:]
                if pieces and piece.startswith("only "):  # "only the export sales or the domestic sales"
                    piece = piece[5:]
                pieces.append(piece)
            return "Kept " + _or(pieces)
        if isinstance(cond, exp.And):
            pieces = [self.phrase(p, ctx) for p in self._and_parts(cond)]
            return "; ".join(_lower_first(p) for p in pieces if p)
        if isinstance(cond, exp.Not):
            inner = cond.this
            if isinstance(inner, exp.Paren):
                inner = inner.this
            if isinstance(inner, exp.Is):
                return f"Kept the {unit} that have a {_col_words(_first_column(inner.this) or inner.this)}"
            sub = self.phrase(inner, ctx)
            if sub and sub.startswith("Kept "):
                return "Left out " + sub[5:]
            return f"Left out some {unit}"
        if isinstance(cond, exp.Is):
            col = _first_column(cond.this)
            return f"Kept the {unit} with no {_col_words(col) if col else 'value'}"
        if isinstance(cond, exp.Like):
            return self.like(cond, ctx)
        if isinstance(cond, exp.In):
            return self.in_list(cond, ctx)
        if isinstance(cond, exp.Between):
            col = _first_column(cond.this)
            if col is None:
                return None
            low, high = self.value(cond.args.get("low")), self.value(cond.args.get("high"))
            name = col.name.lower()
            if _is_date_name(name):
                verb = DATE_VERBS.get(name, f"with {_col_words(col)}")
                return f"Kept the {unit} {verb} from {low} to {high}"
            return f"Kept the {unit} with {_col_words(col)} from {low} to {high}"
        if isinstance(cond, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
            return self.compare(cond, ctx)
        if isinstance(cond, exp.Exists):
            return f"Kept the {unit} that also appear in another list"
        cols = sorted({_col_words(c) for c in cond.find_all(exp.Column)})
        if cols:
            return f"Kept only some {unit} (a check on {_and(cols)})"
        return None

    @staticmethod
    def _or_parts(cond):
        if isinstance(cond, exp.Paren):
            return _Describer._or_parts(cond.this)
        if isinstance(cond, exp.Or):
            return _Describer._or_parts(cond.this) + _Describer._or_parts(cond.expression)
        return [cond]

    def value(self, node):
        """A value in plain words: a date, today, the latest ..., a number or a text."""
        if node is None:
            return "a value"
        if isinstance(node, exp.Paren):
            node = node.this
        if isinstance(node, exp.Literal):
            return _date(node.this) if node.is_string else node.this
        if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
            return "-" + node.this.this
        if _is_today(node):
            return "today"
        if isinstance(node, (exp.Subquery, exp.Select)):
            inner = node.this if isinstance(node, exp.Subquery) else node
            if isinstance(inner, exp.Select) and inner.expressions:
                e = _unwrap(inner.expressions[0])
                col = _first_column(e)
                if isinstance(e, exp.Max) and col is not None:
                    return f"the latest {_col_words(col)}"
                if isinstance(e, exp.Min) and col is not None:
                    return f"the first {_col_words(col)}"
            return "a value looked up in the data"
        if isinstance(node, exp.Column):
            return f"the {_col_words(node)}"
        if isinstance(node, (exp.Sub, exp.Add)) and isinstance(node.expression, exp.Interval):
            return f"{self.value(node.this)} {'minus' if isinstance(node, exp.Sub) else 'plus'} " \
                   f"{node.expression.this.name if node.expression.this else ''} " \
                   f"{(node.expression.unit.name if node.expression.unit else '').lower()}".strip()
        return "a worked-out value"

    def compare(self, cond, ctx):
        unit = _plural(ctx.get("unit") or "row")
        left, right = cond.this, cond.expression
        # keep the column on the left: '2026-01-01' <= invoice_date -> invoice_date >= ...
        flip = {exp.GT: exp.LT, exp.LT: exp.GT, exp.GTE: exp.LTE, exp.LTE: exp.GTE}
        if not isinstance(_unwrap(left), exp.Column) and isinstance(_unwrap(right), exp.Column):
            left, right = right, left
            kind = flip.get(type(cond), type(cond))
        else:
            kind = type(cond)
        col = _unwrap(left)
        if isinstance(col, exp.AggFunc):  # HAVING COUNT(*) > 10
            return self.compare_total(col, kind, right, ctx)
        if not isinstance(col, exp.Column):
            return None
        name = col.name.lower()
        # a column matched to a column of another table: a link, not a filter
        if isinstance(_unwrap(right), exp.Column) and kind is exp.EQ:
            return None
        raw = right.this if isinstance(right, exp.Literal) else None
        if isinstance(right, exp.Neg) and isinstance(right.this, exp.Literal):
            raw = "-" + right.this.this
        val = self.value(right)
        # rn <= 5 after ROW_NUMBER(): the top 5 of each group
        if name in RANK_NAMES and raw is not None and kind in (exp.LTE, exp.LT, exp.EQ):
            n = int(raw) - (1 if kind is exp.LT else 0) if raw.isdigit() else raw
            return "Kept only the first one of each group" if n in (1, "1") else \
                f"Kept only the top {n} of each group"
        # customer_id = (SELECT customer_id FROM top_customer): the value of another list
        if kind is exp.EQ and isinstance(right, exp.Subquery) and val == "a value looked up in the data":
            return f"Kept only the {_col_words(col)} found in {self.source_name(right.this)}"
        # Unknown (-1) rows
        if raw == "-1" and name.endswith("_id"):
            entity = UNKNOWN_WORDS.get(name, _name_words(name))
            if kind is exp.NEQ:
                return f"Left out the Unknown {entity}"
            if kind is exp.EQ:
                return f"Kept only the Unknown {entity}"
        if kind is exp.EQ:
            return self.equals(name, col, raw, val, unit)
        if kind is exp.NEQ:
            sentence = self.equals(name, col, raw, val, unit)
            if sentence.startswith("Kept only the "):
                return "Left out the " + sentence[len("Kept only the "):]
            if sentence.startswith("Kept the "):
                return "Left out the " + sentence[len("Kept the "):]
            return f"Left out the {unit} with {_col_words(col)} {val}"
        words = {exp.LTE: "up to", exp.LT: "before", exp.GTE: "from", exp.GT: "after"}[kind]
        if name == "report_date":
            return f"Kept the stock reports dated {words} {val}"
        if _is_date_name(name):
            verb = DATE_VERBS.get(name, f"with {_col_words(col)}")
            return f"Kept the {unit} {verb} {words} {val}"
        words = {exp.LTE: "at most", exp.LT: "below", exp.GTE: "at least", exp.GT: "above"}[kind]
        if raw == "0" and kind is exp.GT:
            return f"Kept the {unit} with {_col_words(col)} above 0"
        return f"Kept the {unit} with {_col_words(col)} {words} {val}"

    def compare_total(self, agg, kind, right, ctx):
        """HAVING COUNT(*) > 10 -> 'Kept the sales people with more than 10 order lines'."""
        groups = _plural(ctx.get("group") or "group")
        phrase = self.agg_phrase(agg, ctx.get("row_unit") or "row")
        val = self.value(right)
        if not phrase or phrase[0] == "split":
            return f"Kept only the {groups} whose total passes a check"
        verb, obj = phrase
        obj = obj[4:] if obj.startswith("the ") else obj
        if verb == "counted":
            how = {exp.GT: "more than", exp.GTE: "at least", exp.LT: "fewer than", exp.LTE: "at most",
                   exp.EQ: "exactly", exp.NEQ: "other than"}[kind]
            return f"Kept only the {groups} with {how} {val} {obj}"
        how = {exp.GT: "above", exp.GTE: "at least", exp.LT: "below", exp.LTE: "at most",
               exp.EQ: "of", exp.NEQ: "other than"}[kind]
        return f"Kept only the {groups} with {obj} {how} {val}"

    def equals(self, name, col, raw, val, unit):
        """col = value -> 'Kept the NOP sales month Aug 2026' and friends."""
        if raw is not None and (name, raw) in VALUE_WORDS:
            return f"Kept only the {VALUE_WORDS[(name, raw)]}"
        if name == "full_date" and val == "today":
            return "Kept today's row of the calendar"
        if name != "report_date" and (val.startswith("the latest ") or val.startswith("the first ")):
            return f"Kept only {val}"
        if name == "nop_sales_month":
            return f"Kept the NOP sales month {val}"
        if name == "month_year":
            return f"Kept the calendar month {val}"
        if name == "financial_year":
            return f"Kept the financial year {_fy(val)}"
        if name == "nop_sales_year":
            return f"Kept the NOP sales months of {_fy(val)}"
        if name == "financial_year_label":
            return f"Kept the financial year {val}"
        if name == "calendar_year":
            return f"Kept the calendar year {val}"
        if name == "report_date":
            return f"Kept the stock report of {val}" if not val.startswith("the latest") else \
                "Kept the latest stock report"
        if _is_date_name(name):
            verb = DATE_VERBS.get(name, f"with {_col_words(col)}")
            return f"Kept the {unit} {verb} {val}" if "latest" not in val else f"Kept the {unit} of {val}"
        if name == "status":
            word = "cancelled" if (raw or "").lower() in {"canceled", "cancelled"} else (raw or val).lower()
            return f"Kept only the {word} orders"
        if name == "sale_type":
            return f"Kept only the {(raw or val).lower()} sales"
        if name in {"so_number", "invoice_number", "note_number"}:
            return f"Kept {COLUMN_WORDS[name]} {val}"
        if name.endswith("_id") and raw is not None:
            return f"Kept only {_col_words(col)} number {val}"
        return f"Kept only the {unit} with {_col_words(col)} {val}"

    def source_name(self, select):
        """'the top customer list' / 'the product list' - where a small subquery takes its value from."""
        if isinstance(select, exp.Subquery):
            select = select.this
        source = select.args.get("from_") or select.args.get("from") if isinstance(select, exp.Select) else None
        if source is not None and isinstance(source.this, exp.Table):
            name = source.this.name.lower()
            if name in self.lists:
                return f"the {_list_words(name)} list"
            return TABLE_SHORT.get(name, "another list")
        return "another list"

    def like(self, cond, ctx):
        col = _first_column(cond.this)
        pattern = cond.expression.this if isinstance(cond.expression, exp.Literal) else None
        if col is None or pattern is None:
            return f"Kept the {_plural(ctx.get('unit') or 'row')} that match a name"
        subject = LIKE_WORDS.get(col.name.lower(), _plural(_col_words(col)))
        text = pattern.strip("%")
        if pattern.startswith("%") and pattern.endswith("%"):
            how = "containing"
        elif pattern.endswith("%"):
            how = "starting with"
        elif pattern.startswith("%"):
            how = "ending with"
        else:
            how = "equal to"
        verb = "Left out" if cond.args.get("negate") else "Kept"  # NOT LIKE
        return f'{verb} the {subject} {how} "{text}"'

    def in_list(self, cond, ctx):
        unit = _plural(ctx.get("unit") or "row")
        col = _first_column(cond.this)
        if col is None:
            return None
        name = col.name.lower()
        query = cond.args.get("query")
        if query is not None:
            inner = query.this if isinstance(query, exp.Subquery) else query
            if isinstance(inner, exp.Select):
                where = inner.args.get("where")
                if where is not None:
                    inner_from = inner.args.get("from_") or inner.args.get("from")
                    inner_name = inner_from.this.name.lower() if inner_from is not None and \
                        isinstance(inner_from.this, exp.Table) else ""
                    inner_ctx = {"unit": TABLE_UNIT.get(inner_name, "row"), "alias": {}}
                    pieces = self.condition(where.this, inner_ctx)
                    if pieces:
                        return "; ".join(_lower_first(p) for p in pieces)
                return f"Kept the {unit} whose {_col_words(col)} is in {self.source_name(inner)}"
            return f"Kept the {unit} whose {_col_words(col)} is in a looked-up list"
        values = [self.value(v) for v in cond.expressions]
        raws = [v.this for v in cond.expressions if isinstance(v, exp.Literal)]
        if name == "nop_sales_month":
            return f"Kept the NOP sales months {_and(values)}"
        if name == "month_year":
            return f"Kept the calendar months {_and(values)}"
        if name in {"financial_year", "nop_sales_year"}:
            word = "financial years" if name == "financial_year" else "NOP sales months of"
            return f"Kept the {word} {_and([_fy(v) for v in values])}"
        if name == "sale_type":
            return f"Kept only the {_and([v.lower() for v in values])} sales"
        if name == "report_date":
            return f"Kept the stock reports of {_and(values)}"
        if name == "status":
            return f"Kept only the {_and([v.lower() for v in values])} orders"
        if len(raws) == len(values) and all((name, r) in VALUE_SHORT for r in raws):
            return f"Kept only the {_and([VALUE_SHORT[(name, r)] for r in raws])}"
        return f"Kept the {unit} with {_col_words(col)} {_or(values)}"

    # ---- GROUP BY ----
    def group_words(self, exprs, ctx):
        words = []
        for e in exprs:
            col = _first_column(_unwrap(e))
            if col is None:
                continue
            # GROUP BY 1 / an alias of the select list
            if not col.table and col.name.lower() in ctx["select_alias"]:
                inner = _first_column(_unwrap(ctx["select_alias"][col.name.lower()]))
                col = inner or col
            word = _col_words(col)
            if word not in words:
                words.append(word)
        # the start / end dates of a NOP sales month are not groups of their own
        if "NOP sales month" in words:
            words = [w for w in words if w not in GROUP_EXTRAS]
        return words

    # ---- SELECT list: added up / counted / shown ----
    def measures(self, node, ctx, group_words):
        verbs = {}  # verb -> objects, in first-seen order
        splits = {}  # column words -> labels of SUM(CASE WHEN ...)
        shown, lookups, case_sentences = [], [], []
        windows = []  # (verb, object) of the OVER (...) columns - told on their own
        unit = ctx.get("unit") or "row"

        def add(verb, obj):
            verbs.setdefault(verb, [])
            if obj and obj not in verbs[verb]:
                verbs[verb].append(obj)

        for item in node.expressions:
            alias = item.alias if isinstance(item, exp.Alias) else ""
            e = _unwrap(item)
            if isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)):
                shown.append("all the columns")
                continue
            if isinstance(e, (exp.Subquery, exp.Select)):
                inner = e.this if isinstance(e, exp.Subquery) else e
                if isinstance(inner, exp.Select) and inner.expressions:
                    phrase = self.agg_phrase(_unwrap(inner.expressions[0]), unit, alias)
                    if phrase and (phrase[0] == "found" or not alias):
                        lookups.append(phrase[1])
                    elif alias:
                        lookups.append(f"the {_name_words(alias)}")
                continue
            if isinstance(e, exp.Window):
                phrase = self.window_phrase(e, unit)
                if phrase and phrase not in windows:
                    windows.append(phrase)
                continue
            if isinstance(e, exp.AggFunc):
                phrase = self.agg_phrase(e, unit, alias)
                if phrase and phrase[0] == "split":
                    splits.setdefault(phrase[1], [])
                    if phrase[2] not in splits[phrase[1]]:
                        splits[phrase[1]].append(phrase[2])
                elif phrase:
                    add(*phrase)
                continue
            if _has_agg(e):
                add("worked out", f"the {_name_words(alias)}" if alias else "a total from these")
                continue
            if isinstance(e, exp.Case):
                labels = [_unwrap(i.args.get("true")) for i in e.args.get("ifs") or []]
                texts = [f'"{lab.this}"' for lab in labels if isinstance(lab, exp.Literal) and lab.is_string]
                if texts and len(texts) == len(labels):
                    case_sentences.append(
                        f"Split them into {_name_words(alias) if alias else 'groups'}: {_or(texts[:4])}"
                        + (" or others" if len(texts) > 4 else ""))
                else:
                    case_sentences.append(f"Worked out the {_name_words(alias) if alias else 'value'} "
                                          "with a few rules")
                continue
            if isinstance(e, exp.Column):
                words = _col_words(e)
                if words not in shown:
                    shown.append(words)
                continue
            if isinstance(e, exp.Literal) or _is_today(e):
                continue
            if alias:
                shown.append(_name_words(alias))

        for words, labels in splits.items():
            add("added up", f"the {words} split into {_and(labels)}")
        ranks = [w for w in windows if w[0] == "ranked"]
        if len(ranks) > 1:  # several rankings: one short phrase
            windows = [w for w in windows if w[0] != "ranked"] + [("ranked", f"the rows in {len(ranks)} ways")]
        # OVER (...) columns: part of the main sentence when nothing else is worked out,
        # else a sentence of their own (they are worked out after the grouping)
        if windows and not verbs and not group_words:
            for verb, obj in windows:
                add(verb, obj)
        elif windows:
            done = {}
            for verb, obj in windows:
                done.setdefault(verb, []).append(obj)
            case_sentences.append("Also " + _and([f"{v} {_and(o)}" for v, o in done.items()]))

        agg = ""
        if verbs:
            clauses = []
            for verb, objects in sorted(verbs.items(), key=lambda kv: VERB_ORDER.get(kv[0], 9)):
                objects = self.merge_first_last(objects)
                if len(objects) > 3:
                    objects = objects[:3] + ["more"]
                clauses.append(f"{verb} {_and(objects)}")
            agg = _and(clauses)
            if group_words:
                agg += f" for each {_and(group_words[:3])}"
            agg = agg[0].upper() + agg[1:]
        elif group_words:
            agg = f"Listed each {_and(group_words[:3])} once"

        shown_sentence = ""
        if shown and not verbs and not group_words:
            more = len(shown) - 6
            shown_sentence = f"Showed the {_and(shown[:6] + ([f'{more} more columns'] if more > 0 else []))}"
            if shown == ["all the columns"]:
                shown_sentence = "Showed all the columns"
        lookup_sentence = ""
        if lookups:
            lookup_sentence = f"Also looked up {_and(self.merge_first_last(lookups))} in the data"
        return agg, case_sentences, shown_sentence, lookup_sentence

    @staticmethod
    def merge_first_last(objects):
        """['the first invoice date', 'the last invoice date'] -> ['the first and last invoice date']."""
        out = list(objects)
        for obj in list(out):
            if obj.startswith("the first "):
                rest = obj[len("the first "):]
                if f"the last {rest}" in out:
                    out[out.index(obj)] = f"the first and last {rest}"
                    out.remove(f"the last {rest}")
        return out

    def agg_phrase(self, e, unit, alias=""):
        """SUM / COUNT / AVG / MIN / MAX -> (verb, object)."""
        e = _unwrap(e)
        if isinstance(e, exp.Sum):
            inner = _unwrap(e.this)
            if isinstance(inner, exp.Column):
                return "added up", f"the {_col_words(inner)}"
            if isinstance(inner, exp.Case):
                ifs = inner.args.get("ifs") or []
                if len(ifs) == 1:
                    value = _first_column(_unwrap(ifs[0].args.get("true")))
                    if value is not None:
                        return "split", _measure_short(value), self.short_condition(ifs[0].this)
            if isinstance(inner, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.Is)):
                return "counted", f"the {_plural(unit)} with {self.short_condition(inner)}"
            if isinstance(inner, exp.Mul) and any(c.name.lower() == "exchange_rate"
                                                  for c in inner.find_all(exp.Column)):
                others = [c for c in inner.find_all(exp.Column) if c.name.lower() != "exchange_rate"]
                what = _measure_short(others[0]) if others else "value"
                return "added up", f"the {what} in Japanese yen (at the exchange rate of each month)"
            if isinstance(inner, exp.Add):
                cols = [_unwrap(x) for x in (inner.this, inner.expression)]
                if all(isinstance(c, exp.Column) for c in cols):
                    return "added up", " plus ".join(f"the {_col_words(c)}" for c in cols)
            return "worked out", f"the {_name_words(alias)}" if alias else "a total"
        if isinstance(e, exp.Count):
            inner = e.this
            if isinstance(inner, exp.Star) or inner is None:
                return "counted", f"the {_plural(unit)}"
            if isinstance(inner, exp.Distinct):
                first = _unwrap(inner.expressions[0]) if inner.expressions else None
                if isinstance(first, exp.Case):
                    ifs = first.args.get("ifs") or []
                    first = _unwrap(ifs[0].args.get("true")) if ifs else None
                col = _first_column(first) if first is not None else None
                if col is None:
                    return "counted", "the different values"
                words = COUNT_WORDS.get(col.name.lower(), _plural(_col_words(col)))
                return "counted", f"the different {words}"
            col = _first_column(inner)
            if col is not None and col.name.lower().endswith("_id"):
                return "counted", f"the {_plural(unit)}"
            return "counted", f"the {_plural(unit)} with a {_col_words(col)}" if col is not None else \
                f"the {_plural(unit)}"
        if isinstance(e, exp.Avg):
            col = _first_column(e.this)
            return "averaged", f"the {_col_words(col)}" if col is not None else "the values"
        if isinstance(e, (exp.Min, exp.Max)):
            inner = _unwrap(e.this)
            if isinstance(inner, exp.Case):
                ifs = inner.args.get("ifs") or []
                inner = _unwrap(ifs[0].args.get("true")) if ifs else inner
            col = _first_column(inner)
            if col is None:
                return None
            name = col.name.lower()
            if name in {"nop_sales_period_start", "nop_sales_period_end"}:
                return "found", "the start and end dates of the NOP sales month"
            if name in TIME_COLUMNS:
                word = "first" if isinstance(e, exp.Min) else "last"
            else:
                word = "smallest" if isinstance(e, exp.Min) else "largest"
            return "found", f"the {word} {_col_words(col)}"
        if isinstance(e, exp.GroupConcat):
            col = _first_column(e.this)
            return "listed", f"the {_plural(_col_words(col))}" if col is not None else "the values"
        if isinstance(e, exp.AggFunc):
            return "worked out", f"the {_name_words(alias)}" if alias else "a total"
        return None

    def window_phrase(self, e, unit):
        func = e.this
        if isinstance(func, exp.Count) and not e.args.get("partition_by"):
            return "counted", "how many rows matched in all"
        if isinstance(func, (exp.RowNumber, exp.Anonymous)) or func.key in {"rank", "denserank"}:
            order = e.args.get("order")
            first = order.expressions[0] if order and order.expressions else None
            col = _first_column(first) if first is not None else None
            how = "highest" if first is not None and first.args.get("desc") else "lowest"
            obj = f"the rows, {how} {_measure_short(col)} first" if col is not None else "the rows"
            parts = [_col_words(c) for c in (e.args.get("partition_by") or []) if isinstance(c, exp.Column)]
            if parts:
                obj += f", within each {_and(parts)}"
            return "ranked", obj
        phrase = self.agg_phrase(func, unit)
        if phrase and phrase[0] != "split":
            return phrase
        return None

    def short_condition(self, cond):
        """A condition in a few words: 'invoices', 'an Unknown customer', 'dated before 01-Apr-2026'."""
        cond = cond.this if isinstance(cond, exp.Paren) else cond
        if isinstance(cond, exp.And):
            return _and([self.short_condition(p) for p in self._and_parts(cond)])
        if isinstance(cond, exp.NEQ) and isinstance(_unwrap(cond.this), exp.Column):
            col = _unwrap(cond.this)
            if col.name.lower().endswith("_id") and cond.expression.sql() in {"-1", "- 1"}:
                return f"a known {UNKNOWN_WORDS.get(col.name.lower(), _col_words(col))}"
        if isinstance(cond, exp.EQ):
            col, val = _unwrap(cond.this), cond.expression
            if isinstance(col, exp.Column):
                raw = val.this if isinstance(val, exp.Literal) else None
                if isinstance(val, exp.Neg) and isinstance(val.this, exp.Literal):
                    raw = "-" + val.this.this
                if raw is not None and (col.name.lower(), raw) in VALUE_SHORT:
                    return VALUE_SHORT[(col.name.lower(), raw)]
                if raw == "-1" and col.name.lower().endswith("_id"):
                    return f"an Unknown {UNKNOWN_WORDS.get(col.name.lower(), _col_words(col))}"
                if raw is not None:
                    return f"{_col_words(col)} {_date(raw)}"
        phrase = self.phrase(cond, {"unit": "row"})
        if phrase:
            for start in ("Kept only the rows with ", "Kept the rows with ", "Kept only the ",
                          "Kept the rows ", "Kept the ", "Kept "):
                if phrase.startswith(start):
                    return phrase[len(start):]
            if phrase.startswith("Left out the "):
                return "not the " + phrase[len("Left out the "):]
            return _lower_first(phrase)
        return "a condition"

    # ---- ORDER BY and LIMIT ----
    def order(self, node, ctx, group_words):
        limit_node = node.args.get("limit")
        limit = None
        if limit_node is not None:
            value = limit_node.expression if limit_node.expression is not None else limit_node.this
            if isinstance(value, exp.Literal) and value.this.isdigit():
                limit = int(value.this)
        small = limit is not None and limit < SAFETY_LIMIT
        order = node.args.get("order")
        if order is None or not order.expressions:
            if small:
                return f"Showed at most {limit} rows" if limit != 1 else "Showed only the first row"
            return ""
        first = order.expressions[0]
        desc = bool(first.args.get("desc"))
        target = first.this
        words = ""
        # ORDER BY 2 = the 2nd column of the select list
        if isinstance(target, exp.Literal) and not target.is_string and target.this.isdigit():
            position = int(target.this) - 1
            if 0 <= position < len(node.expressions):
                item = node.expressions[position]
                words = _name_words(item.alias) if isinstance(item, exp.Alias) else ""
                target = item.this if isinstance(item, exp.Alias) else item
        if isinstance(target, exp.Column) and not target.table and \
                target.name.lower() in ctx["select_alias"]:
            words = _name_words(target.name)
            target = ctx["select_alias"][target.name.lower()]
        target = _unwrap(target)
        at_most = f", at most {limit}" if small else ""
        # "the top 5 customers" only when one thing is grouped; else "the top 5" alone
        subject = _plural(group_words[0]) if len(group_words) == 1 else ""
        if isinstance(target, exp.Case):
            return "Sorted them in a set order" + at_most
        # oldest / newest first
        time_col = None
        if isinstance(target, exp.Column) and target.name.lower() in TIME_COLUMNS:
            time_col = target
        elif isinstance(target, (exp.Min, exp.Max)):
            col = _first_column(target)
            if col is not None and col.name.lower() in TIME_COLUMNS:
                time_col = col
        if time_col is not None:
            how = "newest first" if desc else "oldest first"
            if group_words and _col_words(time_col) == group_words[0] or (
                    group_words and time_col.name.lower().startswith("nop_sales_period")
                    and group_words[0] == "NOP sales month"):
                return f"Showed the {_plural(group_words[0])} {how}{at_most}"
            if limit == 1:
                return f"Took only the {'newest' if desc else 'oldest'} one"
            return f"Sorted by {_col_words(time_col)}, {how}{at_most}"
        # a measure: top n
        if _has_agg(target) or isinstance(target, exp.AggFunc) or (
                isinstance(target, exp.Column) and target.name.lower() in MEASURE_SHORT):
            measure = words or "the value"
            col = _first_column(target)
            if isinstance(target, exp.Sum) and col is not None or isinstance(target, exp.Column):
                measure = _measure_short(col)
            if limit == 1:
                one = group_words[0] if group_words else "row"
                return f"Showed only the {one} with the {'highest' if desc else 'lowest'} {measure}"
            if small:
                if desc:
                    return f"Showed the top {limit} {subject} by {measure}"
                return f"Showed the {limit} {subject or 'rows'} with the lowest {measure}"
            return f"Showed the {subject or 'rows'} with the {'highest' if desc else 'lowest'} {measure} first"
        if isinstance(target, exp.Column):
            name = target.name.lower()
            if name.endswith("_line_id") or name == "stock_ledger_id":
                return "Showed the lines in the order of the document" + at_most
            if name.endswith(("_name", "_description", "_code", "category", "segment", "type", "status")) \
                    or name in LIKE_WORDS:
                return f"Sorted by {_col_words(target)} ({'Z to A' if desc else 'A to Z'}){at_most}"
            word = words or _col_words(target)
            if limit == 1:
                return f"Showed only the row with the {'highest' if desc else 'lowest'} {word}"
            if small and desc:
                return f"Showed the top {limit} {subject} by {word}"
            return f"Sorted by {word}, {'highest' if desc else 'lowest'} first{at_most}"
        if words:  # an alias of a worked-out value, e.g. increase_inr
            if small and desc:
                return f"Showed the top {limit} {subject} by {words}"
            return f"Sorted by {words}, {'highest' if desc else 'lowest'} first{at_most}"
        return "Sorted the result" + at_most


def _measure_short(col):
    if col is None:
        return "value"
    name = col.name.lower() if isinstance(col, exp.Column) else str(col)
    return MEASURE_SHORT.get(name, _name_words(name))
