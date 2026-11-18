"""stock_runout.py - how many days the stock of each item lasts at its current sales speed.

For every item in the NEWEST stock report (the 'Closing balance' rows of the latest report_date, e.g.
31-Oct-2026):
  stock_qty            the closing stock quantity (cumulative_qty)
  avg_daily_sales_qty  quantity sold per day over the last 90 days of invoices up to data_to
                       (SUM(net_quantity) / 90 - credit notes subtract)
  days_left            stock_qty / avg_daily_sales_qty
  runout_date          report_date + days_left
  status               'Out of stock' (stock 0 or less), 'Under 30 days', 'Under 90 days', 'OK', or
                       'No recent sales' (nothing sold in the 90 days: days_left and runout_date are NULL)
Only finished goods are sold, so raw materials, consumables and capital items are always 'No recent sales'
(item_group says which).
"""
import numpy as np
import pandas as pd

from .db import MlTable, as_date, day_text

SCENARIO = "stock_runout"
SALES_DAYS = 90
STATUS_ORDER = ["Out of stock", "Under 30 days", "Under 90 days", "OK", "No recent sales"]

TABLE = MlTable("ml_stock_runout", (
    "Stock running out (ML): every item of the newest stock report ('Closing balance' rows of the latest "
    "fact_stock_ledger.report_date) with its stock, its average daily sales quantity over the last 90 days of "
    "invoices, the days the stock lasts at that speed and the date it runs out. status = 'Out of stock', "
    "'Under 30 days', 'Under 90 days', 'OK' or 'No recent sales'. Made by ml/run_ml.py."), [
    ("product_id", "INT NOT NULL", "-> dim_products.product_id (-1 = an item of the report not in the item master)."),
    ("product_code", "VARCHAR(30) NOT NULL", "SAP item code, e.g. 'FG00123'."),
    ("product_description", "VARCHAR(255)", "Product description."),
    ("item_group", "VARCHAR(50)", "Item group from dim_products: 'Finished goods' are sold; raw materials, consumables and capital items never are (always 'No recent sales')."),
    ("report_date", "DATE", "Date of the stock report used (the newest fact_stock_ledger.report_date)."),
    ("stock_qty", "DECIMAL(15,3)", "Stock quantity on report_date (the 'Closing balance' cumulative_qty)."),
    ("sold_qty_90d", "DECIMAL(15,3)", "Quantity sold in the last 90 days of invoices up to data_to (SUM(net_quantity), credit notes subtract)."),
    ("avg_daily_sales_qty", "DECIMAL(15,3)", "Average quantity sold per day = sold_qty_90d / 90."),
    ("days_left", "DECIMAL(9,1)", "Days the stock lasts at that speed = stock_qty / avg_daily_sales_qty. NULL when nothing was sold in the 90 days."),
    ("runout_date", "DATE", "report_date + days_left: the day the stock runs out at the current speed. NULL when nothing was sold."),
    ("status", "VARCHAR(20)", "'Out of stock' (stock 0 or less), 'Under 30 days', 'Under 90 days', 'OK' (90 days or more) or 'No recent sales'."),
    ("run_at", "DATETIME", "When ml/run_ml.py made this row."),
], primary_key=["product_code"], indexes=["status", "product_id"])


def stock_speed(stock, lines, data_to, days=SALES_DAYS):
    """Join the stock report with the sales quantity of the last `days` days: one row per item with
    stock_qty, sold_qty_90d, avg_daily_sales_qty."""
    end = pd.Timestamp(data_to)
    sold = lines[(lines["product_id"] != -1)].copy()
    sold["invoice_date"] = pd.to_datetime(sold["invoice_date"])
    sold = sold[(sold["invoice_date"] > end - pd.Timedelta(days=days)) & (sold["invoice_date"] <= end)]
    per_product = sold.groupby("product_id")["net_quantity"].sum().astype(float)
    out = stock.copy()
    out["stock_qty"] = out["stock_qty"].astype(float)
    out["sold_qty_90d"] = out["product_id"].map(per_product).fillna(0.0)
    out.loc[out["product_id"] == -1, "sold_qty_90d"] = 0.0
    out["avg_daily_sales_qty"] = out["sold_qty_90d"] / days
    return out


def runout(frame):
    """Add days_left, runout_date and status (see the module text)."""
    f = frame.copy()
    speed = f["avg_daily_sales_qty"].where(f["avg_daily_sales_qty"] > 0)
    f["days_left"] = (f["stock_qty"].clip(lower=0) / speed).round(1)
    f["runout_date"] = pd.to_datetime(f["report_date"]) + pd.to_timedelta(np.floor(f["days_left"]), unit="D")
    f["status"] = np.select(
        [f["stock_qty"] <= 0, speed.isna(), f["days_left"] < 30, f["days_left"] < 90],
        ["Out of stock", "No recent sales", "Under 30 days", "Under 90 days"], default="OK")
    f.loc[speed.isna(), ["days_left", "runout_date"]] = np.nan
    return f


def trained_on(inputs, data_to, rows):
    """ml_run_log.trained_on: 'stock report 31-Oct-2026 + invoices 03-Aug-2026 - 31-Oct-2026 (the last 90 days)'
    (stock_speed counts the invoices dated after data_to - 90 days, up to data_to)."""
    if not rows:
        return None
    first_day = pd.Timestamp(data_to) - pd.Timedelta(days=SALES_DAYS - 1)
    return (f"stock report {day_text(rows[0]['report_date'])} + invoices {day_text(first_day)} - "
            f"{day_text(data_to)} (the last {SALES_DAYS} days)")


def run(inputs, data_to, run_at, save_csv):
    stock = inputs["stock"]
    if stock.empty:
        return [], ("items", 0), ["no stock report found"]
    speed = stock_speed(stock, inputs["lines"], data_to)
    products = inputs["products"].set_index("product_id")
    speed["product_code"] = speed["product_id"].map(products["product_code"])
    speed.loc[speed["product_id"] == -1, "product_code"] = speed["src_product_code"]
    speed["product_code"] = speed["product_code"].fillna(speed["src_product_code"])
    save_csv(speed[["report_date", "product_id", "product_code", "stock_qty", "sold_qty_90d", "avg_daily_sales_qty"]],
             "stock_speed.csv")
    result = runout(speed).drop_duplicates("product_code")
    rows = []
    for r in result.itertuples():
        known = r.product_id != -1
        rows.append({"product_id": int(r.product_id), "product_code": r.product_code,
                     "product_description": products["product_description"].get(r.product_id) if known
                     else r.item_description,
                     "item_group": products["item_group"].get(r.product_id) if known else None,
                     "report_date": as_date(r.report_date), "stock_qty": round(float(r.stock_qty), 3),
                     "sold_qty_90d": round(float(r.sold_qty_90d), 3),
                     "avg_daily_sales_qty": round(float(r.avg_daily_sales_qty), 3),
                     "days_left": None if pd.isna(r.days_left) else float(r.days_left),
                     "runout_date": as_date(r.runout_date), "status": r.status, "run_at": run_at})
    counts = result["status"].value_counts().to_dict()
    report = as_date(result["report_date"].iloc[0])
    summary = [f"stock report {report:%d-%b-%Y}, {len(rows)} items; "
               + ", ".join(f"{k}: {counts.get(k, 0)}" for k in STATUS_ORDER)]
    return rows, ("items under 30 days", counts.get("Under 30 days", 0)), summary
