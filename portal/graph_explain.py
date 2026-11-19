"""The Knowledge graph's "Explain this" button: POST /api/graph/explain {type, id, fy} (api.graph_explain).

Only on a click (never by itself): ONE AI call writes 3-5 plain sentences about one node of the graph (a customer,
product, category, sales person, state, sale type or a PDF page), from facts the SERVER reads itself - nothing the
browser sends is used but the node's type, id and period:
- the node's own numbers in the period (knowledge_graph.node: net sales, quantity, invoices, the dates of its lines,
  how many links of each kind and the top ones with their share, the Unknown notes);
- its net sales per financial year (never after today; the running FY says "so far");
- ML results of the latest ml/run_ml.py run (read-only from the ss_gold ml_* tables), each with its date: a customer's
  risk (ml_customer_risk) and group (ml_customer_segments); a product's stock run-out (ml_stock_runout) and, for a
  top-10 product, its sales forecast (ml_sales_forecast). An ml_ table that cannot be read is left out.
The code writes no answer text: it gives the AI only TRUE facts (with their periods and dates) and the rules
(EXPLAIN_SYSTEM_PROMPT); the AI writes the sentences.

The AI call is the same as the AI chart's (charts.py): the model chain (agent._ask_models - Groq main, the second
Groq key with the per-minute switch, the Groq backup), the main model at low effort, at most MAX_TOKENS; a friendly
message when no model answers. A reply kept CACHE_SECONDS per (node, period, facts) - a second click on the same node
costs no tokens; new data (other facts) asks again. Not counted on History's usage box (that counts questions);
the tokens are logged (lc.calls) and sent back to be shown.
"""
import datetime
import hashlib
import logging
import re
import threading
import time

from langchain_core.prompts import ChatPromptTemplate

from . import knowledge_graph as kg
from .lc import calls
from .lc.calls import LcRequest
from .rag import agent, warehouse

log = logging.getLogger(__name__)

MAX_TOKENS = 500            # a short thinking + 3-5 sentences
EFFORT = "low"
TOP_LINKS = 5               # neighbours of each kind given to the AI
TEXT_CHARS = 400            # a PDF page's text given to the AI
CACHE_SECONDS = 600         # one explanation is kept 10 minutes ...
CACHE_MOST = 300            # ... and at most this many

DAILY_LIMIT = "The AI model's daily limit is used up - the explanation can be made again tomorrow. The numbers above are all there."
NO_TEXT = "The AI did not write an explanation this time. Please try again."

EXPLAIN_SYSTEM_PROMPT = (
    "You explain one node of the Knowledge graph of SS Manufacturing (a pump manufacturer) to a business user.\n"
    "Write 3 to 5 short sentences in plain English, as one paragraph.\n"
    "Rules:\n"
    "- Use only the facts given. Never invent numbers, names, dates, reasons or trends that are not in the facts.\n"
    "- Say the period the numbers are for (e.g. \"in FY 2026-27 so far\", \"from 21-Dec-2025 to 19-Nov-2026\").\n"
    "- Amounts are INR: write them as the facts give them in Crore or lakh (e.g. INR 2.91 Crore); never "
    "recompute a percent.\n"
    "- ML results (risk, customer group, stock run-out, forecast) are estimates: say so and give their date.\n"
    "- No lists, no tables, no headings, no markdown, no SQL, no code."
)
EXPLAIN_REQUEST = "Facts about this node (read from the SS Manufacturing data just now):\n{facts}"

# node facts -> 3-5 sentences
EXPLAIN_PROMPT = ChatPromptTemplate.from_messages([("system", EXPLAIN_SYSTEM_PROMPT), ("human", EXPLAIN_REQUEST)])


def explain_chain(llm):
    return EXPLAIN_PROMPT | llm


calls.CHAINS.setdefault("graph_explain", explain_chain)  # so calls.chat() runs it with the app's rate-limit rules


class ExplainError(Exception):
    """No explanation: str() is the friendly message, status the HTTP status for the API."""

    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ how the facts write numbers
def inr(amount):
    """12345678.9 -> 'INR 1.23 Crore (1,23,45,678.90)', 450000 -> 'INR 4.50 lakh (4,50,000.00)', 9500 ->
    'INR 9,500.00': the rounded amount the answer may use, and the exact one."""
    value = float(amount or 0)
    exact = kg.indian(value)
    if abs(value) >= 1e7:
        return f"INR {value / 1e7:.2f} Crore ({exact})"
    if abs(value) >= 1e5:
        return f"INR {value / 1e5:.2f} lakh ({exact})"
    return f"INR {exact}"


def _day(value):
    return value.strftime("%d-%b-%Y") if isinstance(value, datetime.date) else ""


def _number(value, places=1):
    """A plain number: 72.50 -> '72.5', 3.0 -> '3', None -> ''."""
    if value is None:
        return ""
    number = round(float(value), places)
    return f"{number:g}" if abs(number) < 1e15 else str(number)


def _share(part, whole):
    """', 4.3% of its net sales' ('' for a part of 0 or less, or no whole to compare with)."""
    if part is None or float(part) <= 0 or not whole or whole <= 0:
        return ""
    pct = round(100 * float(part) / whole, 1)
    return f", {pct:g}% of its net sales" if pct else ", under 0.1% of its net sales"


def today():
    """Today (a test sets its own day)."""
    return datetime.date.today()


def running_fy(day=None):
    """'2627' for a day in FY 2026-27 (Indian FY: April to March)."""
    day = day or today()
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


# ------------------------------------------------------------------ the facts of one node
# (edge, neighbour type) -> what the list of those neighbours is, said from the node's side
LINK_NAMES = {
    ("BOUGHT", "product"): "Products it bought",
    ("HANDLED_BY", "sales_person"): "Sales people on its invoices",
    ("IN_STATE", "state"): "Its bill-to state / country",
    ("BUYS_AS", "sale_type"): "Sale types it buys as",
    ("BOUGHT", "customer"): "Customers who bought it",
    ("IN_CATEGORY", "category"): "Its category",
    ("IN_CATEGORY", "product"): "Products in this category",
    ("HANDLED_BY", "customer"): "Customers on this sales person's invoices",
    ("IN_STATE", "customer"): "Customers billed here",
    ("BUYS_AS", "customer"): "Customers buying as this sale type",
    ("COVERED_BY", "document"): "Company PDF pages that cover it",
    ("COVERED_BY", "category"): "Product categories this page names",
}


def _link_lines(reply):
    """One line per kind of link: how many in all, and the top TOP_LINKS with their net sales and share."""
    center = reply["node"]
    whole = center.get("amount")
    by_id = {n["id"]: n for n in reply["neighbours"]}
    lines = []
    for group in reply["groups"]:
        if not group["total"]:
            continue
        edge, kind = group["edge"], group["type"]
        parts = []
        for link in reply["edges"]:
            if link["type"] != edge:
                continue
            other = by_id.get(link["target"] if link["source"] == center["id"] else link["source"])
            if not other or other["type"] != kind:
                continue
            if link.get("amount") is not None:
                parts.append(f"{other['label']} {inr(link['amount'])}{_share(link['amount'], whole)}")
            elif link.get("model"):
                parts.append(f"{other['label']} (lists model {link['model']})")
            elif link.get("mentions"):
                what = f" of its category {link['through']}" if link.get("through") else ""
                own = f", its net sales {inr(other['amount'])}" if other.get("amount") is not None else ""
                parts.append(f"{other['label']} ({link['mentions']} mentions{what}{own})")
            else:
                parts.append(other["label"])
            if len(parts) == TOP_LINKS:
                break
        name = LINK_NAMES.get((edge, kind), f"{edge} {kind}")
        top = f"top {len(parts)} by net sales" if len(parts) < group["total"] else "all"
        lines.append(f"- {name}: {kg.indian(group['total'], 0)} in all; {top}: " + "; ".join(parts))
    return lines


def _fy_lines(kind, key):
    """The node's net sales per financial year, never after today (the running FY: 'so far')."""
    rows = kg._rows(f"SELECT c.financial_year, SUM(f.net_taxable_value), {kg.INVOICES} FROM {kg.FACTS}{kg.CALENDAR} "
                    f"WHERE {kg.NODE_FILTER[kind]} AND f.invoice_date <= CURDATE() GROUP BY c.financial_year "
                    f"ORDER BY c.financial_year", [key])
    now = running_fy()
    lines = []
    for fy, amount, invoices in rows:
        code = str(fy or "")
        if not re.fullmatch(r"\d{4}", code):
            continue
        label = kg.fy_label(code) + (" so far (up to today)" if code == now else "")
        lines.append(f"- {label}: {inr(amount)}, {kg.indian(invoices or 0, 0)} invoices")
    return lines


# the date of the data each ML result was made from (the latest run of its scenario)
_RUN_DATE = "(SELECT l.data_to FROM ml_run_log l WHERE l.scenario = '{scenario}' ORDER BY l.run_id DESC LIMIT 1)"
RISK_SQL = ("SELECT r.risk_level, r.risk_score, r.reason, r.last_invoice_date, r.days_since_last_invoice, "
            "r.typical_gap_days, r.sales_last_3m_inr, r.normal_3m_inr, r.drop_pct, "
            + _RUN_DATE.format(scenario="customer_risk") + " FROM ml_customer_risk r WHERE r.customer_id = %s")
SEGMENT_SQL = ("SELECT s.segment_name, s.recency_days, s.invoices, s.sales_inr, s.first_invoice_date, "
               "s.last_invoice_date, " + _RUN_DATE.format(scenario="customer_segments")
               + " FROM ml_customer_segments s WHERE s.customer_id = %s")
RUNOUT_SQL = ("SELECT s.status, s.report_date, s.stock_qty, s.sold_qty_90d, s.avg_daily_sales_qty, s.days_left, "
              "s.runout_date, " + _RUN_DATE.format(scenario="stock_runout")
              + " FROM ml_stock_runout s WHERE s.product_id = %s ORDER BY s.product_code LIMIT 1")
FORECAST_SQL = ("SELECT f.sales_month, f.period_start, f.period_end, f.forecast_inr, f.low_inr, f.high_inr, f.data_to "
                "FROM ml_sales_forecast f WHERE f.level = 'PRODUCT' AND f.product_id = %s ORDER BY f.period_start")


def _as_of(data_to):
    return f" (made from the data up to {_day(data_to)})" if isinstance(data_to, datetime.date) else ""


def _customer_ml(key):
    lines = []
    risk = kg._rows(RISK_SQL, [key])
    if risk:
        level, score, reason, last, days, gap, last_3m, normal_3m, drop, data_to = risk[0]
        line = f"- Customer risk{_as_of(data_to)}: {level}, score {_number(score)} of 100"
        if reason:
            line += f"; reason: {reason}"
        if isinstance(last, datetime.date):
            line += f"; last invoice {_day(last)}"
            if days is not None:
                line += f", {days} days before {_day(data_to) or 'the data date'}"
        if gap is not None:
            line += f"; usually an invoice every {gap} days"
        if last_3m is not None:
            line += f"; net sales of the last 3 months {inr(last_3m)}"
        if normal_3m is not None:
            line += f" against its normal 3 months {inr(normal_3m)}"
        if drop is not None:
            line += f" ({_number(drop)}% below normal)"
        lines.append(line)
    else:
        lines.append("- Customer risk: not scored (only customers with 6+ invoices over 6+ months and some sales in "
                     "the last 15 months get a risk score)")
    group = kg._rows(SEGMENT_SQL, [key])
    if group:
        name, recency, invoices, sales, first, last, data_to = group[0]
        line = f"- Customer group{_as_of(data_to)}: {name}"
        details = []
        if invoices is not None:
            details.append(f"{kg.indian(invoices, 0)} invoices")
        if sales is not None:
            details.append(f"net sales {inr(sales)} in all the data")
        if isinstance(first, datetime.date) and isinstance(last, datetime.date):
            details.append(f"invoices from {_day(first)} to {_day(last)}")
        if recency is not None:
            details.append(f"{recency} days since the last invoice")
        lines.append(line + (f" ({'; '.join(details)})" if details else ""))
    return lines


def _product_ml(key):
    lines = []
    stock = kg._rows(RUNOUT_SQL, [key])
    if stock:
        status, report, qty, sold, daily, days, runout, data_to = stock[0]
        source = ", ".join(part for part in (f"stock report of {_day(report)}" if _day(report) else "",
                                             f"sales of the 90 days up to {_day(data_to)}" if _day(data_to) else "")
                           if part)
        line = f"- Stock run-out{f' ({source})' if source else ''}: {status}"
        if qty is not None:
            line += f"; stock {kg.quantity_text(qty)}"
        if sold is not None:
            line += f"; sold {kg.quantity_text(sold)} in the 90 days"
        if daily is not None:
            line += f" (about {_number(daily, 2)} a day)"
        if days is not None:
            line += f"; about {_number(days)} days of stock left"
        if isinstance(runout, datetime.date):
            line += f", runs out around {_day(runout)} at this speed"
        lines.append(line)
    forecast = kg._rows(FORECAST_SQL, [key])
    if forecast:
        months = "; ".join(f"{month} ({_day(start)} to {_day(end)}) {inr(value)}, range {inr(low)} to {inr(high)}"
                           for month, start, end, value, low, high, _ in forecast)
        lines.append(f"- Sales forecast{_as_of(forecast[0][6])}, net sales per sales month with an 80% range: {months}")
    else:
        lines.append("- Sales forecast: none for this product (only the top 10 products have one)")
    return lines


ML_FACTS = {"customer": _customer_ml, "product": _product_ml}


def _ml_lines(kind, key):
    """The node's ML results, [] when it has none or the ml_ tables cannot be read (no ML run yet)."""
    if kind not in ML_FACTS:
        return []
    try:
        return ML_FACTS[kind](key)
    except warehouse.QueryError as exc:
        log.warning("Explain: the ML results of %s %s were left out: %s", kind, key, exc)
        return []


def node_facts(kind, key, fy=""):
    """(the node reply of knowledge_graph.node, the facts as text) - everything the AI is given about the node,
    read from the database now. BadRequest / NotFound / warehouse errors as for /api/graph/node."""
    reply = kg.node(kind, key, fy, TOP_LINKS)
    center, when = reply["node"], reply["period"]
    kind, key = center["type"], kg.parse_key(center["type"], center["key"])
    sub = f" ({center['sub']})" if center["sub"] else ""
    lines = [f"Node: {center['type_name']} \"{center['label']}\"{sub}", f"Today: {_day(today())}"]
    if kind == "document":
        lines.append(f"Text at the start of the page: {center.get('text', '')[:TEXT_CHARS]}")
        lines.append(f"Period of the net sales below: {when['text']}")
    else:
        lines.append(f"Period of the numbers: {when['text']} (net sales = before GST, credit notes subtracted, "
                     "never a line dated after today)")
        if center.get("lines"):
            lines.append(f"- Net sales: {inr(center['amount'])}")
            lines.append(f"- Quantity {center.get('quantity_text', '')}; {center.get('invoices_text', '0')} invoices; "
                         f"{kg.indian(center['lines'], 0)} invoice lines")
            lines.append(f"- Its lines in this period are dated {center.get('data_from')} to {center.get('data_to')}")
    lines += _link_lines(reply)
    lines += [f"- Note: {note}" for note in reply["notes"]]
    if kind in kg.NODE_FILTER:
        years = _fy_lines(kind, key)
        if years:
            lines.append("Net sales per financial year (April to March):")
            lines += years
    ml = _ml_lines(kind, key)
    if ml:
        lines.append("ML results of the app (estimates, not recorded sales):")
        lines += ml
    return reply, "\n".join(lines)


# ------------------------------------------------------------------ the kept explanations
_kept = {}
_kept_lock = threading.Lock()


def clear_cache():
    """Forget the kept explanations (tests)."""
    with _kept_lock:
        _kept.clear()


def _kept_reply(key):
    with _kept_lock:
        hit = _kept.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return dict(hit[1], cached=True)
    return None


def _keep(key, reply):
    now = time.monotonic()
    with _kept_lock:
        for old in [k for k, (at, _) in _kept.items() if now - at >= CACHE_SECONDS]:
            del _kept[old]
        while len(_kept) >= CACHE_MOST:
            del _kept[min(_kept, key=lambda k: _kept[k][0])]
        _kept[key] = (now, reply)


# ------------------------------------------------------------------ the AI call
def _whole_sentences(text):
    """A reply cut at max_tokens without its half sentence ('' when not one sentence is whole)."""
    end = max(text.rfind(". "), text.rfind(".\n"), len(text) - 1 if text.endswith(".") else -1)
    return text[:end + 1].strip() if end > 0 else ""


def explain(kind, key, fy=""):
    """{text, model, model_label, model_note, tokens, cached, node, period} for one node. ExplainError with a
    friendly message when no model answers; BadRequest / NotFound / warehouse errors as for /api/graph/node."""
    reply, facts = node_facts(kind, key, fy)
    center = reply["node"]
    kept_as = (center["id"], reply["period"]["fy"], hashlib.sha256(facts.encode("utf-8")).hexdigest())
    kept = _kept_reply(kept_as)
    if kept:
        return kept
    reasons = {}
    try:
        text, tokens, cut_off, entry = agent._ask_models(LcRequest("graph_explain", {"facts": facts}), MAX_TOKENS,
                                                         EFFORT, agent.models_in_order(), reasons)
    except agent.AIUnavailable as exc:
        if str(exc) == agent.AI_DAILY_LIMIT:  # every model's daily limit is used up
            raise ExplainError(DAILY_LIMIT, 503) from None
        raise ExplainError(str(exc) or agent.AI_ERROR, 503) from None
    text = agent.fy_labels(agent.plain_text(text or ""))
    if cut_off:
        log.warning("Explain: the reply of %s was cut at %s tokens", entry.model, MAX_TOKENS)
        text = _whole_sentences(text)
    if not text:
        raise ExplainError(NO_TEXT, 502)
    answer = {"text": text, "model": entry.model, "model_label": entry.label,
              "model_note": agent.model_note("", entry, reasons), "tokens": tokens, "cached": False,
              "node": center["id"], "period": reply["period"]["label"]}
    _keep(kept_as, answer)
    return dict(answer)
