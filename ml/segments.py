"""segments.py - customer groups found by KMeans (scikit-learn) on recency, frequency, money and tenure.

Every customer with at least one invoice (not the Unknown customer -1) gets 4 numbers, as of data_to:
  recency_days  days since its last invoice
  invoices      how many invoices it had (frequency)
  sales_inr     its net sales in all the data (money; credit notes subtract)
  tenure_days   days since its first invoice (how long it has been a customer)
They are put on one scale (log for invoices and sales, which are very skewed; days as they are; then
StandardScaler) and KMeans makes 5 groups.
Each group gets a plain name from its centre, one name per group, in this order:
  'Lapsed'               the group with the longest time since the last invoice
  'New customers'        of the rest, the group with the shortest time as a customer
  'Big regular buyers'   of the rest, the group with the highest sales
  'Regular buyers'       of the rest, the group with the most invoices
  'Occasional buyers'    the group left over
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from .db import MlTable, as_date, invoice_period, money

SCENARIO = "customer_segments"
CLUSTERS = 5
FEATURES = ["recency_days", "invoices", "sales_inr", "tenure_days"]
LOG_FEATURES = {"invoices", "sales_inr"}

TABLE = MlTable("ml_customer_segments", (
    "Customer groups (ML): every customer with at least one invoice, put in one of 5 groups by KMeans on "
    "recency (days since the last invoice), frequency (invoices), money (net sales) and tenure (days since the "
    "first invoice), as of the newest invoice date (data_to in ml_run_log). segment_name is a plain name: "
    "'Big regular buyers', 'Regular buyers', 'Occasional buyers', 'New customers' or 'Lapsed'. Made by ml/run_ml.py."), [
    ("customer_id", "INT NOT NULL", "-> dim_customers.customer_id."),
    ("customer_code", "VARCHAR(20)", "SAP customer code, e.g. 'C0001'."),
    ("customer_name", "VARCHAR(255)", "Customer name (dim_customers.customer_name)."),
    ("segment_no", "TINYINT", "Group number 1-5 (1 = Big regular buyers, 2 = Regular buyers, 3 = Occasional buyers, 4 = New customers, 5 = Lapsed)."),
    ("segment_name", "VARCHAR(30)", "Group name: 'Big regular buyers', 'Regular buyers', 'Occasional buyers', 'New customers' or 'Lapsed'."),
    ("recency_days", "INT", "Days from the customer's last invoice to data_to (the newest invoice date)."),
    ("invoices", "INT", "Invoices of the customer in all the data (distinct invoice numbers)."),
    ("sales_inr", "DECIMAL(18,2)", "Net sales of the customer in all the data, INR before GST."),
    ("tenure_days", "INT", "Days from the customer's first invoice to data_to."),
    ("first_invoice_date", "DATE", "Date of the customer's first invoice."),
    ("last_invoice_date", "DATE", "Date of the customer's last invoice."),
    ("run_at", "DATETIME", "When ml/run_ml.py made the groups."),
], primary_key=["customer_id"], indexes=["segment_name"])

NAME_ORDER = ["Big regular buyers", "Regular buyers", "Occasional buyers", "New customers", "Lapsed"]


def rfm(lines, data_to):
    """One row per customer: customer_id + FEATURES + first / last invoice date."""
    end = pd.Timestamp(data_to)
    lines = lines[lines["customer_id"] != -1].copy()
    lines["invoice_date"] = pd.to_datetime(lines["invoice_date"])
    lines = lines[lines["invoice_date"] <= end]
    invoices = lines[lines["document_type"] == "INVOICE"]
    out = pd.DataFrame({
        "first_invoice_date": invoices.groupby("customer_id")["invoice_date"].min(),
        "last_invoice_date": invoices.groupby("customer_id")["invoice_date"].max(),
        "invoices": invoices.groupby("customer_id")["invoice_number"].nunique(),
        "sales_inr": lines.groupby("customer_id")["net_taxable_value"].sum().astype(float),
    }).dropna(subset=["last_invoice_date"])
    out["recency_days"] = (end - out["last_invoice_date"]).dt.days
    out["tenure_days"] = (end - out["first_invoice_date"]).dt.days
    out.index.name = "customer_id"
    return out.reset_index()


def name_clusters(centres):
    """{cluster label: name} from the cluster centres (a DataFrame in the original units, see the module text)."""
    left = list(centres.index)
    names = {}

    def take(label, name):
        names[label] = name
        left.remove(label)

    take(centres.loc[left, "recency_days"].idxmax(), "Lapsed")
    for name, column, pick in [("New customers", "tenure_days", "min"), ("Big regular buyers", "sales_inr", "max"),
                               ("Regular buyers", "invoices", "max")]:
        if left:
            values = centres.loc[left, column]
            take(values.idxmin() if pick == "min" else values.idxmax(), name)
    for label in list(left):
        take(label, "Occasional buyers")
    return names


def segment_customers(features, clusters=CLUSTERS, seed=42):
    """Add segment_no / segment_name to the RFM rows (KMeans on the scaled log features)."""
    f = features.copy()
    clusters = max(1, min(clusters, len(f)))
    x = np.column_stack([np.log1p(f[c].clip(lower=0).astype(float)) if c in LOG_FEATURES
                         else f[c].astype(float) for c in FEATURES])
    x = StandardScaler().fit_transform(x)
    model = KMeans(n_clusters=clusters, n_init=10, random_state=seed).fit(x)
    f["cluster"] = model.labels_
    centres = f.groupby("cluster")[FEATURES].median()
    names = name_clusters(centres)
    f["segment_name"] = f["cluster"].map(names)
    f["segment_no"] = f["segment_name"].map({n: i for i, n in enumerate(NAME_ORDER, start=1)})
    return f.drop(columns="cluster")


def trained_on(inputs, data_to, rows):
    """ml_run_log.trained_on: 'invoices 02-Apr-2024 - 31-Oct-2026' (every invoice of every customer)."""
    return invoice_period(inputs, data_to)


def run(inputs, data_to, run_at, save_csv):
    features = rfm(inputs["lines"], data_to)
    names = inputs["customers"].set_index("customer_id")
    features.insert(1, "customer_code", features["customer_id"].map(names["customer_code"]))
    save_csv(features, "customer_rfm.csv")
    grouped = segment_customers(features)
    rows = [{"customer_id": int(r.customer_id), "customer_code": r.customer_code,
             "customer_name": names["customer_name"].get(r.customer_id), "segment_no": int(r.segment_no),
             "segment_name": r.segment_name, "recency_days": int(r.recency_days), "invoices": int(r.invoices),
             "sales_inr": money(r.sales_inr), "tenure_days": int(r.tenure_days),
             "first_invoice_date": as_date(r.first_invoice_date), "last_invoice_date": as_date(r.last_invoice_date),
             "run_at": run_at} for r in grouped.itertuples()]
    sizes = grouped.groupby("segment_name").agg(customers=("customer_id", "size"), sales=("sales_inr", "sum"),
                                                recency=("recency_days", "median"), invoices=("invoices", "median"),
                                                tenure=("tenure_days", "median"))
    summary = [f"{name}: {int(s.customers)} customers, sales {s.sales:,.0f}, median recency {s.recency:.0f} d, "
               f"median invoices {s.invoices:.0f}, median tenure {s.tenure:.0f} d"
               for name, s in sizes.reindex([n for n in NAME_ORDER if n in sizes.index]).iterrows()]
    return rows, ("customer groups", len(sizes)), summary
