"""product_pairs.py - products bought together on the same sales order (market-basket analysis).

One order = SO number + financial year of the order date (the SO number restarts every financial year);
cancelled orders and the Unknown product (-1) are left out. For every pair of products A and B on the
same order:
  orders_together  orders that have both
  support_pct      orders_together / all orders x 100 - ALREADY a percent: 0.4816 = 0.48 % of all orders
                   (19-Nov: an answer multiplied it by 100 again)
  confidence_pct   orders_together / orders with A x 100 = 'of the orders with A, this % also had B' - ALREADY
                   a percent (27.92 = 27.92 %).
                   A is the product of the pair with FEWER orders, so this is the stronger direction.
  lift             orders_together x all orders / (orders with A x orders with B): how many times more often
                   the two are bought together than by chance (1 = chance, 2 = twice as often).
Kept: pairs bought together on at least N orders and with lift > 1. N is the smallest of 3, 5, 8, 10, 15,
20, 25, 30, 40, 50 that keeps at most 300 pairs, so the list stays readable.
"""
from collections import Counter
from itertools import combinations

import pandas as pd

from .db import MlTable, day_text

SCENARIO = "product_pairs"
MIN_ORDER_STEPS = [3, 5, 8, 10, 15, 20, 25, 30, 40, 50]
MAX_PAIRS = 300

TABLE = MlTable("ml_product_pairs", (
    "Products bought together (ML): pairs of products on the same sales order (SO number + financial year; "
    "cancelled orders left out), with support, confidence and lift. Only pairs bought together on at least "
    "min_orders orders and more often than by chance (lift > 1). product_a = the product of the pair with fewer "
    "orders. Made by ml/run_ml.py."), [
    ("product_a_id", "INT NOT NULL", "-> dim_products.product_id of product A (the one with fewer orders)."),
    ("product_a_code", "VARCHAR(30)", "SAP item code of product A."),
    ("product_a_description", "VARCHAR(255)", "Description of product A."),
    ("product_b_id", "INT NOT NULL", "-> dim_products.product_id of product B."),
    ("product_b_code", "VARCHAR(30)", "SAP item code of product B."),
    ("product_b_description", "VARCHAR(255)", "Description of product B."),
    ("orders_together", "INT", "Sales orders that had both products."),
    ("orders_a", "INT", "Sales orders that had product A."),
    ("orders_b", "INT", "Sales orders that had product B."),
    ("support_pct", "DECIMAL(9,4)", "orders_together / all sales orders x 100 (how common the pair is overall). "
                                    "ALREADY a percent: 0.4816 = 0.48 % of all orders - write it as 0.48 %, never "
                                    "multiply it by 100."),
    ("confidence_pct", "DECIMAL(9,2)", "orders_together / orders_a x 100: of the orders with product A, this % also "
                                       "had product B. ALREADY a percent: 27.92 = 27.92 % - never multiply it by 100."),
    ("lift", "DECIMAL(9,2)", "How many times more often A and B are on one order than by chance (1 = chance; 2 = twice as often). A plain ratio, not a percent."),
    ("min_orders", "INT", "The threshold of this run: pairs need at least this many orders together."),
    ("run_at", "DATETIME", "When ml/run_ml.py found the pairs."),
], primary_key=["product_a_id", "product_b_id"], indexes=["product_a_code", "product_b_code"])


def order_baskets(orders):
    """One row per (order, product): order_key = 'SO number/FY start year', product_id. No cancelled, no -1."""
    x = orders[(orders["product_id"] != -1) & (orders["status"] != "Canceled")].copy()
    day = pd.to_datetime(x["order_date"])
    fy = day.dt.year.where(day.dt.month >= 4, day.dt.year - 1)
    x["order_key"] = x["so_number"].astype(str) + "/" + fy.astype(str)
    return x[["order_key", "product_id"]].drop_duplicates().reset_index(drop=True)


def pair_stats(baskets, min_orders=None):
    """The pairs with their counts, support, confidence and lift (see the module text).
    min_orders None = choose N from MIN_ORDER_STEPS. Returns (DataFrame, N)."""
    total = baskets["order_key"].nunique()
    per_product = baskets.groupby("product_id")["order_key"].nunique()
    together = Counter()
    for _, products in baskets.groupby("order_key")["product_id"]:
        together.update(combinations(sorted(set(products)), 2))
    columns = ["product_a_id", "product_b_id", "orders_together", "orders_a", "orders_b",
               "support_pct", "confidence_pct", "lift"]
    if not together or total == 0:
        return pd.DataFrame(columns=columns), min_orders or MIN_ORDER_STEPS[0]
    pairs = pd.DataFrame([(a, b, n) for (a, b), n in together.items()], columns=["p1", "p2", "orders_together"])
    pairs["n1"], pairs["n2"] = pairs["p1"].map(per_product), pairs["p2"].map(per_product)
    swap = pairs["n1"] > pairs["n2"]           # A = the product with fewer orders
    pairs["product_a_id"] = pairs["p1"].where(~swap, pairs["p2"])
    pairs["product_b_id"] = pairs["p2"].where(~swap, pairs["p1"])
    pairs["orders_a"] = pairs["n1"].where(~swap, pairs["n2"])
    pairs["orders_b"] = pairs["n2"].where(~swap, pairs["n1"])
    pairs["support_pct"] = pairs["orders_together"] / total * 100
    pairs["confidence_pct"] = pairs["orders_together"] / pairs["orders_a"] * 100
    pairs["lift"] = pairs["orders_together"] * total / (pairs["orders_a"] * pairs["orders_b"])
    pairs = pairs[pairs["lift"] > 1]
    if min_orders is None:
        min_orders = MIN_ORDER_STEPS[-1]
        for step in MIN_ORDER_STEPS:
            if (pairs["orders_together"] >= step).sum() <= MAX_PAIRS:
                min_orders = step
                break
    kept = pairs[pairs["orders_together"] >= min_orders][columns]
    return kept.sort_values(["lift", "orders_together"], ascending=False).reset_index(drop=True), min_orders


def trained_on(inputs, data_to, rows):
    """ml_run_log.trained_on: 'sales orders 02-Apr-2024 - 31-Oct-2026' (the order dates read; cancelled ones are
    left out of the baskets)."""
    dates = pd.to_datetime(inputs["orders"]["order_date"]).dropna()
    if dates.empty:
        return None
    return f"sales orders {day_text(dates.min())} - {day_text(dates.max())}"


def run(inputs, data_to, run_at, save_csv):
    baskets =order_baskets(inputs["orders"])
    save_csv(baskets, "order_baskets.csv")
    pairs, min_orders = pair_stats(baskets)
    products = inputs["products"].set_index("product_id")
    rows = [{"product_a_id": int(r.product_a_id), "product_a_code": products["product_code"].get(r.product_a_id),
             "product_a_description": products["product_description"].get(r.product_a_id),
             "product_b_id": int(r.product_b_id), "product_b_code": products["product_code"].get(r.product_b_id),
             "product_b_description": products["product_description"].get(r.product_b_id),
             "orders_together": int(r.orders_together), "orders_a": int(r.orders_a), "orders_b": int(r.orders_b),
             "support_pct": round(float(r.support_pct), 4), "confidence_pct": round(float(r.confidence_pct), 2),
             "lift": round(float(r.lift), 2), "min_orders": int(min_orders), "run_at": run_at}
            for r in pairs.itertuples()]
    summary = [f"{baskets['order_key'].nunique():,} orders, {baskets['product_id'].nunique():,} products; "
               f"kept {len(rows)} pairs bought together on >= {min_orders} orders with lift > 1"]
    if rows:
        top = rows[0]
        summary.append(f"strongest: {top['product_a_code']} + {top['product_b_code']} on {top['orders_together']} "
                       f"orders, confidence {top['confidence_pct']}%, lift {top['lift']}")
    return rows, ("pairs kept", len(rows)), summary
