"""invoice_alerts.py - invoice lines and credit notes that look unusual (robust z-scores, no black box).

'Unusual price'     an invoice line whose unit price is far from that product's normal price. For each product
                    with at least 5 invoice lines: the median of log(unit price) and its spread (1.4826 x the
                    median absolute deviation, at least 5 %); z = distance from the median / spread. Flagged
                    when |z| >= 3.5 AND the price is at least 15 % above or below the median price.
'Unusual quantity'  an invoice line whose quantity is far ABOVE that product's normal quantity (same robust z on
                    log(quantity), spread at least 0.5), flagged when z >= 3.5 and the quantity is at least 5 x
                    the median quantity.
'Large credit note' a credit note (all its lines) much bigger than the usual credit note: robust z of
                    log(note value) over all credit notes >= 2, or the note takes back at least half of the
                    original invoice; at least 5 x the median credit note either way.
score = the z value (how many 'normal spreads' away from normal); higher = more unusual. Scores compare only
within one alert type (credit notes vary much more than prices, so their z values are lower). Only the strongest
alerts are kept (at most 100 price, 60 quantity and 40 credit-note alerts), so the list stays readable.
"""
import numpy as np
import pandas as pd

from .db import MlTable, as_date, invoice_period, money

SCENARIO = "invoice_alerts"
MIN_LINES = 5
LIMITS = {"Unusual price": 100, "Unusual quantity": 60, "Large credit note": 40}

TABLE = MlTable("ml_invoice_alerts", (
    "Unusual invoices (ML): invoice lines with a unit price or quantity far from that product's normal "
    "(robust z-score), and credit notes much larger than usual. One row per alert, ordered by alert_type "
    "(price, quantity, credit note) and the highest score first within each type; at most 100 price, 60 "
    "quantity and 40 credit-note alerts. Compare scores only within one alert_type. Amounts INR before GST. Made by ml/run_ml.py."), [
    ("alert_id", "INT NOT NULL", "Alert key: the price alerts first, then quantity, then credit notes; the highest score first within each type."),
    ("alert_type", "VARCHAR(20) NOT NULL", "'Unusual price' (unit price far from the product's median price), 'Unusual quantity' (quantity far above the product's usual quantity) or 'Large credit note' (a credit note much bigger than usual)."),
    ("invoice_number", "VARCHAR(30)", "Invoice number, e.g. 'SSMI/D/2526/169'. For a credit note: the ORIGINAL invoice it corrects (like fact_invoice_lines.invoice_number)."),
    ("note_number", "VARCHAR(30)", "Credit note number on 'Large credit note' rows, e.g. 'SSMI/CN/2627/1'; NULL on the other rows."),
    ("invoice_date", "DATE", "Invoice date; for a credit note the note date."),
    ("customer_id", "INT", "-> dim_customers.customer_id (-1 = Unknown customer)."),
    ("customer_name", "VARCHAR(255)", "Customer name (dim_customers.customer_name)."),
    ("product_code", "VARCHAR(30)", "SAP item code of the line (for a credit note: of its biggest line)."),
    ("product_description", "VARCHAR(255)", "Product description."),
    ("value_inr", "DECIMAL(18,2)", "The unusual value in INR: 'Unusual price' = the unit price; 'Unusual quantity' = the line's taxable value; 'Large credit note' = the note's taxable value (positive)."),
    ("typical_inr", "DECIMAL(18,2)", "The normal value to compare with, INR: the product's median unit price; the product's median quantity x median price; the median credit note."),
    ("quantity", "DECIMAL(15,3)", "Quantity of the line on 'Unusual quantity' / 'Unusual price' rows; NULL on credit notes."),
    ("typical_quantity", "DECIMAL(15,3)", "The product's median quantity per invoice line on 'Unusual quantity' rows; NULL on the others."),
    ("score", "DECIMAL(9,2)", "How unusual: the robust z-score (distance from normal in 'normal spreads'); higher = stronger. Compare scores only within one alert_type: price and quantity alerts start at 3.5, credit notes vary much more, so their scores are lower (a credit note is flagged from 2, or when it takes back half the invoice)."),
    ("reason", "VARCHAR(500)", "Why, in plain English, e.g. 'Unit price 41,000 is 31% below this product's usual 59,500 (seen on 48 lines)'."),
    ("run_at", "DATETIME", "When ml/run_ml.py found the alert."),
], primary_key=["alert_id"], indexes=["alert_type"])


def _robust(values, floor):
    """(median, spread) of a Series: spread = 1.4826 x median absolute deviation, at least `floor`."""
    median = values.median()
    spread = max(1.4826 * (values - median).abs().median(), floor)
    return median, spread


def _per_product(lines, column, floor):
    """median / spread / line count of log(column) per product, merged onto the lines."""
    lines = lines.copy()
    lines["log_value"] = np.log(lines[column].astype(float))
    stats = lines.groupby("product_id")["log_value"].agg(
        median="median", lines="size",
        mad=lambda v: (v - v.median()).abs().median())
    stats["spread"] = np.maximum(1.4826 * stats["mad"], floor)
    lines = lines.merge(stats[["median", "spread", "lines"]], left_on="product_id", right_index=True)
    lines = lines[lines["lines"] >= MIN_LINES]
    lines["z"] = (lines["log_value"] - lines["median"]) / lines["spread"]
    lines["typical"] = np.exp(lines["median"])
    return lines


def price_alerts(lines):
    """Invoice lines with an unusual unit price (see the module text). Returns a DataFrame with z, typical."""
    x = lines[(lines["document_type"] == "INVOICE") & (lines["product_id"] != -1)
              & (lines["unit_price"].astype(float) > 0)]
    x = _per_product(x, "unit_price", floor=0.05)
    change = x["unit_price"].astype(float) / x["typical"] - 1
    x = x.assign(change=change)
    return x[(x["z"].abs() >= 3.5) & (change.abs() >= 0.15)].assign(score=lambda d: d["z"].abs())


def quantity_alerts(lines):
    """Invoice lines with a quantity far above the product's usual quantity."""
    x = lines[(lines["document_type"] == "INVOICE") & (lines["product_id"] != -1)
              & (lines["quantity"].astype(float) > 0)]
    x = _per_product(x, "quantity", floor=0.5)
    ratio = x["quantity"].astype(float) / x["typical"]
    x = x.assign(ratio=ratio)
    return x[(x["z"] >= 3.5) & (ratio >= 5)].assign(score=lambda d: d["z"])


def credit_note_alerts(lines):
    """Credit notes (all lines of one note) that are much bigger than usual. One row per note."""
    notes = lines[lines["document_type"] == "CREDIT_NOTE"].copy()
    if notes.empty:
        return notes.assign(value=[], z=[], typical=[], share=[], score=[])
    notes["value_line"] = notes["taxable_value"].astype(float).abs()
    biggest = notes.sort_values("value_line", ascending=False).drop_duplicates("note_number")
    per_note = notes.groupby("note_number")["value_line"].sum().rename("value")
    x = biggest.set_index("note_number").join(per_note).reset_index()
    x = x[x["value"] > 0]
    median, spread = _robust(np.log(x["value"]), floor=0.25)
    x["z"] = (np.log(x["value"]) - median) / spread
    x["typical"] = float(np.exp(median))
    invoiced = (lines[lines["document_type"] == "INVOICE"].groupby("invoice_number")["taxable_value"]
                .sum().astype(float))
    x["invoice_value"] = x["invoice_number"].map(invoiced)
    x["share"] = x["value"] / x["invoice_value"]
    big = (x["value"] >= 5 * x["typical"]) & ((x["z"] >= 2) | (x["share"] >= 0.5))
    return x[big].assign(score=lambda d: d["z"])


def find_alerts(lines):
    """All three kinds, strongest first within each kind, cut to LIMITS: a list of dicts (without names)."""
    out = []
    for row in price_alerts(lines).sort_values("score", ascending=False).head(LIMITS["Unusual price"]).itertuples():
        price = float(row.unit_price)
        direction = "above" if row.change > 0 else "below"
        out.append({"alert_type": "Unusual price", "row": row, "value_inr": price, "typical_inr": row.typical,
                    "quantity": float(row.quantity) if pd.notna(row.quantity) else None, "score": abs(row.z),
                    "reason": f"Unit price {price:,.0f} is {abs(row.change) * 100:.0f}% {direction} this product's "
                              f"usual {row.typical:,.0f} (seen on {int(row.lines)} invoice lines)"})
    for row in quantity_alerts(lines).sort_values("score", ascending=False).head(LIMITS["Unusual quantity"]).itertuples():
        qty, price = float(row.quantity), float(row.unit_price) if pd.notna(row.unit_price) else None
        typical_price = price if price is not None else 0.0
        out.append({"alert_type": "Unusual quantity", "row": row,
                    "value_inr": float(row.taxable_value) if pd.notna(row.taxable_value) else None,
                    "typical_inr": row.typical * typical_price, "quantity": qty, "typical_quantity": row.typical,
                    "score": row.z,
                    "reason": f"Quantity {qty:,.0f} is {row.ratio:.0f} x this product's usual {row.typical:,.0f} "
                              f"per invoice line (seen on {int(row.lines)} lines)"})
    for row in credit_note_alerts(lines).sort_values("score", ascending=False).head(LIMITS["Large credit note"]).itertuples():
        share = (f"; it takes back {row.share * 100:.0f}% of invoice {row.invoice_number}"
                 if pd.notna(row.share) else "")
        why = f" ({row.issue_reason})" if isinstance(row.issue_reason, str) and row.issue_reason else ""
        out.append({"alert_type": "Large credit note", "row": row, "value_inr": row.value,
                    "typical_inr": row.typical, "score": row.z, "note_number": row.note_number,
                    "reason": f"Credit note {row.note_number} of {row.value:,.0f} is {row.value / row.typical:.0f} x "
                              f"the usual credit note ({row.typical:,.0f}){share}{why}"})
    return out


def trained_on(inputs, data_to, rows):
    """ml_run_log.trained_on: 'invoices 02-Apr-2024 - 31-Oct-2026' (every invoice line and credit note)."""
    return invoice_period(inputs, data_to)


def run(inputs, data_to, run_at, save_csv):
    lines = inputs["lines"]
    save_csv(lines[["invoice_line_id", "document_type", "invoice_number", "note_number", "invoice_date",
                    "customer_id", "product_id", "quantity", "unit_price", "taxable_value", "net_taxable_value",
                    "issue_reason"]], "invoice_lines_for_alerts.csv")
    customers = inputs["customers"].set_index("customer_id")["customer_name"]
    products = inputs["products"].set_index("product_id")
    rows = []
    order = list(LIMITS)       # price, quantity, credit note; the strongest first within each type
    alerts = sorted(find_alerts(lines), key=lambda a: (order.index(a["alert_type"]), -float(a["score"])))
    for i, alert in enumerate(alerts, start=1):
        r = alert.pop("row")
        rows.append({"alert_id": i, "alert_type": alert["alert_type"], "invoice_number": r.invoice_number,
                     "note_number": alert.get("note_number"), "invoice_date": as_date(r.invoice_date),
                     "customer_id": int(r.customer_id), "customer_name": customers.get(r.customer_id),
                     "product_code": products["product_code"].get(r.product_id),
                     "product_description": products["product_description"].get(r.product_id),
                     "value_inr": money(alert["value_inr"]), "typical_inr": money(alert["typical_inr"]),
                     "quantity": alert.get("quantity"), "typical_quantity":
                     None if alert.get("typical_quantity") is None else round(float(alert["typical_quantity"]), 3),
                     "score": round(float(alert["score"]), 2), "reason": alert["reason"][:500], "run_at": run_at})
    counts = pd.Series([r["alert_type"] for r in rows], dtype=object).value_counts().to_dict()
    summary = [", ".join(f"{k}: {counts.get(k, 0)}" for k in LIMITS)]
    return rows, ("alerts", len(rows)), summary
