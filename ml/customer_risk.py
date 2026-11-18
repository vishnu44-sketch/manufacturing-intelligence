"""customer_risk.py - customers who are buying less or have stopped, with a 0-100 risk score.

Everything is measured 'as of' data_to (the newest invoice date), not today.

Features per customer (from the invoice lines; sales = SUM(net_taxable_value), credit notes subtract):
  recency            days since the last invoice
  typical gap        the median number of days between two of its invoice dates
  last 3 months      sales of the 91 days up to data_to
  previous 3 months  sales of the 91 days before those
  usual 3 months     the average 3-month sales of the 12 months before the last 3 months
  same 3 months a year ago   sales of the same 91 days one year earlier
  orders             sales orders (not cancelled; SO number + order date) of the last 3 months, and the
                     normal number per 3 months (counted the same way as the sales)

Risk score (a transparent points score, no black box), each part 0..1:
  sales drop  (40 %) = how far the last 3 months fell below the customer's normal level. The normal level is
                       the HIGHER of 'usual 3 months' and 'same 3 months a year ago', so a slow decline that
                       already pulled the last year down is still seen.
  fewer orders(40 %) = the same for the number of sales orders (less noisy than the amounts)
  overdue     (20 %) = how long it has been since the last invoice compared with its typical gap
                       (nothing at 1.5 x the gap, full at 6 x the gap)
  x evidence         = min(1, normal orders per 3 months / 3): a customer who normally orders about once a
                       month or more gets the full score; one who orders only now and then gets less, because
                       a quiet spell is normal for it.
score = 100 x evidence x the weighted sum. High >= 50, Medium >= 30, else Low.

Only customers with a real history are scored: at least 6 invoices, at least 6 months between the first and
the last invoice, and some sales in the last 15 months (a customer silent for longer is already lost: it is in
ml_customer_segments as 'Lapsed', not here). The Unknown customer (-1) is never scored.
"""
import numpy as np
import pandas as pd

from .db import MlTable, as_date, day_text, invoice_period, money

SCENARIO = "customer_risk"
MIN_INVOICES = 6
MIN_SPAN_DAYS = 182
ACTIVE_DAYS = 456            # some sales in the last 15 months
WEIGHTS = {"drop": 0.40, "orders": 0.40, "overdue": 0.20}
FULL_EVIDENCE_ORDERS = 3     # normal orders per 3 months for the full score
HIGH, MEDIUM = 50, 30

TABLE = MlTable("ml_customer_risk", (
    "Customers at risk (ML): one row per customer with a real buying history (>= 6 invoices over >= 6 months, "
    "some sales in the last 15 months) and a 0-100 risk score of buying less or stopping, as of the newest "
    "invoice date (data_to in ml_run_log). risk_level High / Medium / Low; reason says why in plain English. "
    "Sales = net sales before GST (SUM(net_taxable_value)). Made by ml/run_ml.py."), [
    ("customer_id", "INT NOT NULL", "-> dim_customers.customer_id."),
    ("customer_code", "VARCHAR(20)", "SAP customer code, e.g. 'C0001'."),
    ("customer_name", "VARCHAR(255)", "Customer name (dim_customers.customer_name)."),
    ("risk_score", "DECIMAL(9,2)", "Risk score 0-100: 40 % sales drop and 40 % fewer sales orders against the customer's normal level, 20 % days since the last invoice against its usual gap; lowered for customers who normally order less than about once a month. Higher = more likely to be lost."),
    ("risk_level", "VARCHAR(10)", "'High' (score >= 50), 'Medium' (30-49) or 'Low' (< 30)."),
    ("reason", "VARCHAR(500)", "Why, in plain English, e.g. 'Sales fell 82% (last 3 months vs its normal 3 months); no invoice for 140 days (usually every 20 days)'."),
    ("last_invoice_date", "DATE", "Date of the customer's last invoice (on or before data_to)."),
    ("days_since_last_invoice", "INT", "Days from the last invoice to data_to (the newest invoice date in ss_gold)."),
    ("typical_gap_days", "INT", "The customer's usual number of days between two invoice dates (median)."),
    ("sales_last_3m_inr", "DECIMAL(18,2)", "Net sales of the last 3 months (the 91 days up to data_to), INR before GST."),
    ("sales_prev_3m_inr", "DECIMAL(18,2)", "Net sales of the 3 months before those (days 92-182 before data_to), INR."),
    ("change_pct", "DECIMAL(9,2)", "Change of the last 3 months against the previous 3 months in % (-50 = half). NULL when the previous 3 months had no sales."),
    ("normal_3m_inr", "DECIMAL(18,2)", "The customer's normal 3-month sales the drop is measured against: the higher of the average 3 months of the 12 months before the last 3 months and the same 3 months a year ago, INR."),
    ("drop_pct", "DECIMAL(9,2)", "How far the last 3 months are below that normal level, in % (100 = no sales at all, 0 = at or above normal)."),
    ("orders_last_3m", "INT", "Sales orders (not cancelled; SO number + order date) of the last 3 months (91 days up to data_to)."),
    ("orders_normal_3m", "DECIMAL(9,2)", "The customer's normal number of sales orders per 3 months (the higher of the average of the 12 months before the last 3 months and the same 3 months a year ago)."),
    ("invoices_last_12m", "INT", "Invoices (distinct invoice numbers) of the last 12 months."),
    ("invoices_total", "INT", "Invoices of the customer in all the data."),
    ("lifetime_sales_inr", "DECIMAL(18,2)", "Net sales of the customer in all the data, INR before GST."),
    ("run_at", "DATETIME", "When ml/run_ml.py made this score."),
], primary_key=["customer_id"], indexes=["risk_level"])


def customer_features(lines, orders, data_to):
    """One row per customer with the features above.

    lines : invoice lines with customer_id, invoice_date, document_type, invoice_number, net_taxable_value
    orders: sales order lines with customer_id, so_number, order_date, status"""
    end = pd.Timestamp(data_to)
    lines = lines[(lines["customer_id"] != -1)].copy()
    lines["invoice_date"] = pd.to_datetime(lines["invoice_date"])
    lines = lines[lines["invoice_date"] <= end]
    lines["sales"] = lines["net_taxable_value"].astype(float)
    age = (end - lines["invoice_date"]).dt.days

    def window_sum(lo, hi):     # sales with lo <= days before data_to < hi
        mask = (age >= lo) & (age < hi)
        return lines[mask].groupby("customer_id")["sales"].sum()

    invoices = lines[lines["document_type"] == "INVOICE"]
    inv_age = (end - invoices["invoice_date"]).dt.days
    out = pd.DataFrame({
        "first_invoice_date": invoices.groupby("customer_id")["invoice_date"].min(),
        "last_invoice_date": invoices.groupby("customer_id")["invoice_date"].max(),
        "invoices_total": invoices.groupby("customer_id")["invoice_number"].nunique(),
        "invoices_last_12m": invoices[inv_age < 365].groupby("customer_id")["invoice_number"].nunique(),
        "lifetime_sales_inr": lines.groupby("customer_id")["sales"].sum(),
        "sales_last_3m_inr": window_sum(0, 91),
        "sales_prev_3m_inr": window_sum(91, 182),
        "sales_12m_before_inr": window_sum(91, 456),
        "sales_year_ago_3m_inr": window_sum(365, 456),
    })
    out = out[out["last_invoice_date"].notna()]
    fill = ["invoices_last_12m", "sales_last_3m_inr", "sales_prev_3m_inr", "sales_12m_before_inr",
            "sales_year_ago_3m_inr", "lifetime_sales_inr"]
    out[fill] = out[fill].fillna(0.0)
    out["days_since_last_invoice"] = (end - out["last_invoice_date"]).dt.days
    out["span_days"] = (out["last_invoice_date"] - out["first_invoice_date"]).dt.days

    gaps = (invoices[["customer_id", "invoice_date"]].drop_duplicates().sort_values(["customer_id", "invoice_date"]))
    gaps["gap"] = gaps.groupby("customer_id")["invoice_date"].diff().dt.days
    out["typical_gap_days"] = gaps.groupby("customer_id")["gap"].median().reindex(out.index)

    orders = orders[(orders["customer_id"] != -1) & (orders["status"] != "Canceled")].copy()
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    orders = orders[orders["order_date"] <= end]
    one = orders[["customer_id", "so_number", "order_date"]].drop_duplicates()
    o_age = (end - one["order_date"]).dt.days
    def order_count(lo, hi):
        return one[(o_age >= lo) & (o_age < hi)].groupby("customer_id").size().reindex(out.index).fillna(0)

    out["orders_last_3m"] = order_count(0, 91)
    out["orders_12m_before"] = order_count(91, 456)
    out["orders_year_ago_3m"] = order_count(365, 456)
    out.index.name = "customer_id"
    return out.reset_index()


def eligible(features):
    """Customers with a real history that are not lost already (see the module text)."""
    return features[(features["invoices_total"] >= MIN_INVOICES)
                    & (features["span_days"] >= MIN_SPAN_DAYS)
                    & (features["days_since_last_invoice"] < ACTIVE_DAYS)].copy()


def _reason(row):
    parts = []
    if row["drop_part"] >= 0.25:
        if row["sales_last_3m_inr"] <= 0:
            parts.append("No sales in the last 3 months (normally about "
                         f"INR {row['normal_3m_inr']:,.0f} per 3 months)")
        else:
            parts.append(f"Sales fell {row['drop_pct']:.0f}% (last 3 months vs its normal 3 months)")
    if row["overdue_part"] > 0:
        parts.append(f"no invoice for {row['days_since_last_invoice']:.0f} days "
                     f"(usually every {row['typical_gap_days']:.0f} days)")
    if row["orders_part"] >= 0.25:
        word = "order" if row["orders_last_3m"] == 1 else "orders"
        parts.append(f"{row['orders_last_3m']:.0f} {word} in the last 3 months (normally about "
                     f"{row['orders_normal_3m']:.0f})")
    if not parts:
        return "Buying as usual"
    text = "; ".join(parts)
    if row["evidence"] < 1 and row["risk_score"] >= MEDIUM:
        text += " - score lowered: it orders only now and then"
    return text[0].upper() + text[1:]


def score_risk(features):
    """Add drop_pct, the three parts, risk_score, risk_level and reason to the eligible customers."""
    f = eligible(features)
    if f.empty:
        return f.assign(risk_score=[], risk_level=[], reason=[], drop_pct=[], normal_3m_inr=[], change_pct=[],
                        orders_normal_3m=[])
    f["normal_3m_inr"] = np.maximum(f["sales_12m_before_inr"] / 4.0, f["sales_year_ago_3m_inr"])
    normal = f["normal_3m_inr"].where(f["normal_3m_inr"] > 0)
    f["drop_part"] = (1 - f["sales_last_3m_inr"] / normal).clip(0, 1).fillna(0.0)
    f["drop_pct"] = (f["drop_part"] * 100).round(2)
    gap = f["typical_gap_days"].fillna(f["span_days"]).clip(lower=7)
    f["overdue_part"] = ((f["days_since_last_invoice"] / gap - 1.5) / 4.5).clip(0, 1)
    f["orders_normal_3m"] = np.maximum(f["orders_12m_before"] / 4.0, f["orders_year_ago_3m"])
    usual = f["orders_normal_3m"].where(f["orders_normal_3m"] > 0)
    f["orders_part"] = (1 - f["orders_last_3m"] / usual).clip(0, 1).fillna(0.0)
    f["evidence"] = (f["orders_normal_3m"] / FULL_EVIDENCE_ORDERS).clip(upper=1.0)
    f["risk_score"] = (100 * f["evidence"] * (WEIGHTS["drop"] * f["drop_part"] + WEIGHTS["orders"] * f["orders_part"]
                                              + WEIGHTS["overdue"] * f["overdue_part"])).round(2)
    f["risk_level"] = np.where(f["risk_score"] >= HIGH, "High", np.where(f["risk_score"] >= MEDIUM, "Medium", "Low"))
    prev = f["sales_prev_3m_inr"].where(f["sales_prev_3m_inr"] > 0)
    f["change_pct"] = ((f["sales_last_3m_inr"] - prev) / prev * 100).round(2)
    f["typical_gap_days"] = gap
    f["reason"] = f.apply(_reason, axis=1)
    return f.sort_values("risk_score", ascending=False).reset_index(drop=True)


def trained_on(inputs, data_to, rows):
    """ml_run_log.trained_on: 'invoices 02-Apr-2024 - 31-Oct-2026 + sales orders up to 31-Oct-2026'."""
    return f"{invoice_period(inputs, data_to)} + sales orders up to {day_text(data_to)}"


def run(inputs, data_to, run_at, save_csv):
    features = customer_features(inputs["lines"], inputs["orders"], data_to)
    names = inputs["customers"].set_index("customer_id")
    features.insert(1, "customer_code", features["customer_id"].map(names["customer_code"]))
    save_csv(features, "customer_features.csv")
    scored = score_risk(features)
    rows = []
    for r in scored.itertuples():
        rows.append({
            "customer_id": int(r.customer_id), "customer_code": r.customer_code,
            "customer_name": names["customer_name"].get(r.customer_id),
            "risk_score": float(r.risk_score), "risk_level": r.risk_level, "reason": r.reason[:500],
            "last_invoice_date": as_date(r.last_invoice_date),
            "days_since_last_invoice": int(r.days_since_last_invoice),
            "typical_gap_days": int(round(r.typical_gap_days)),
            "sales_last_3m_inr": money(r.sales_last_3m_inr), "sales_prev_3m_inr": money(r.sales_prev_3m_inr),
            "change_pct": None if pd.isna(r.change_pct) else float(r.change_pct),
            "normal_3m_inr": money(r.normal_3m_inr), "drop_pct": float(r.drop_pct),
            "orders_last_3m": int(r.orders_last_3m), "orders_normal_3m": round(float(r.orders_normal_3m), 2),
            "invoices_last_12m": int(r.invoices_last_12m), "invoices_total": int(r.invoices_total),
            "lifetime_sales_inr": money(r.lifetime_sales_inr), "run_at": run_at})
    counts = scored["risk_level"].value_counts().to_dict()
    summary = [f"{len(features)} customers with invoices, {len(scored)} scored (real history, active in 15 months)",
               f"High {counts.get('High', 0)}, Medium {counts.get('Medium', 0)}, Low {counts.get('Low', 0)}"]
    return rows, ("customers High risk", counts.get("High", 0)), summary
