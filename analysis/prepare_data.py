"""Clean the Olist e-commerce data and build the star-schema CSVs used by the Power BI report.

Input : the public Olist dataset (downloaded automatically into data/raw/ if missing)
Output: data/model/*.csv  - one fact table per grain, three dimensions
        data/model/data_quality_log.csv - what was removed or changed, and why

Run:  python analysis/prepare_data.py
"""
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, MODEL = ROOT / "data" / "raw", ROOT / "data" / "model"
SOURCE = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/{}"
FILES = [
    "olist_orders_dataset.csv", "olist_order_items_dataset.csv", "olist_order_reviews_dataset.csv",
    "olist_customers_dataset.csv", "olist_products_dataset.csv", "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]
PERIOD = ("2017-01-01", "2018-09-01")  # purchase dates; months before/after this are near-empty

# Brazilian states: code -> (name, region). Regions follow IBGE.
STATES = {
    "AC": ("Acre", "North"), "AL": ("Alagoas", "Northeast"), "AM": ("Amazonas", "North"),
    "AP": ("Amapá", "North"), "BA": ("Bahia", "Northeast"), "CE": ("Ceará", "Northeast"),
    "DF": ("Distrito Federal", "Central-West"), "ES": ("Espírito Santo", "Southeast"),
    "GO": ("Goiás", "Central-West"), "MA": ("Maranhão", "Northeast"), "MG": ("Minas Gerais", "Southeast"),
    "MS": ("Mato Grosso do Sul", "Central-West"), "MT": ("Mato Grosso", "Central-West"),
    "PA": ("Pará", "North"), "PB": ("Paraíba", "Northeast"), "PE": ("Pernambuco", "Northeast"),
    "PI": ("Piauí", "Northeast"), "PR": ("Paraná", "South"), "RJ": ("Rio de Janeiro", "Southeast"),
    "RN": ("Rio Grande do Norte", "Northeast"), "RO": ("Rondônia", "North"), "RR": ("Roraima", "North"),
    "RS": ("Rio Grande do Sul", "South"), "SC": ("Santa Catarina", "South"), "SE": ("Sergipe", "Northeast"),
    "SP": ("São Paulo", "Southeast"), "TO": ("Tocantins", "North"),
}
# (label, lower bound of days_vs_estimate, sort order). days_vs_estimate > 0 means late.
DELIVERY_BUCKETS = [
    ("8+ days early", -10_000, 1), ("1-7 days early", -7, 2), ("On the day", 0, 3),
    ("1-3 days late", 1, 4), ("4-7 days late", 4, 5), ("8-14 days late", 8, 6), ("15+ days late", 15, 7),
]

log = []
def note(step, rows, reason):
    log.append({"step": step, "rows_affected": int(rows), "reason": reason})


def download_if_missing():
    RAW.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        if not (RAW / f).exists():
            print(f"downloading {f}")
            urllib.request.urlretrieve(SOURCE.format(f), RAW / f)


def build():
    dates = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
             "order_delivered_customer_date", "order_estimated_delivery_date"]
    orders = pd.read_csv(RAW / FILES[0], parse_dates=dates)
    items = pd.read_csv(RAW / FILES[1], parse_dates=["shipping_limit_date"])
    reviews = pd.read_csv(RAW / FILES[2], parse_dates=["review_answer_timestamp"])
    customers = pd.read_csv(RAW / FILES[3])
    products = pd.read_csv(RAW / FILES[4])
    sellers = pd.read_csv(RAW / FILES[5])
    translation = pd.read_csv(RAW / FILES[6])

    # --- Orders: keep delivered orders inside the analysis period -------------------------
    note("raw orders", len(orders), "")
    not_delivered = orders.order_status != "delivered"
    note("removed: not delivered", not_delivered.sum(), "canceled, unavailable, still in transit - no delivery to measure")
    orders = orders[~not_delivered]
    no_date = orders.order_delivered_customer_date.isna()
    note("removed: delivered but no delivery date", no_date.sum(), "status says delivered, timestamp missing")
    orders = orders[~no_date]
    outside = ~orders.order_purchase_timestamp.between(*PERIOD, inclusive="left")
    note("removed: outside Jan 2017 - Aug 2018", outside.sum(), "2016 and Sep/Oct 2018 have only a handful of orders per month")
    orders = orders[~outside].copy()

    # --- Delivery performance ------------------------------------------------------------
    delivered_day = orders.order_delivered_customer_date.dt.normalize()
    orders["days_vs_estimate"] = (delivered_day - orders.order_estimated_delivery_date).dt.days
    orders["is_late"] = (orders.days_vs_estimate > 0).astype(int)
    orders["delivery_days"] = (
        (orders.order_delivered_customer_date - orders.order_purchase_timestamp).dt.total_seconds() / 86400
    ).round(2)
    bounds = [b for _, b, _ in DELIVERY_BUCKETS] + [10_000]
    orders["delivery_bucket"] = pd.cut(orders.days_vs_estimate, bins=[b - 0.5 for b in bounds],
                                       labels=[l for l, _, _ in DELIVERY_BUCKETS]).astype(str)
    orders["delivery_bucket_sort"] = orders.delivery_bucket.map({l: s for l, _, s in DELIVERY_BUCKETS})

    # --- Reviews: one per order ------------------------------------------------------------
    dup = reviews.order_id.duplicated(keep=False)
    note("reviews: orders with more than one review", reviews[dup].order_id.nunique(),
         "kept the most recent answer per order")
    latest = reviews.sort_values("review_answer_timestamp").drop_duplicates("order_id", keep="last")
    orders = orders.merge(latest[["order_id", "review_score"]], on="order_id", how="left")
    note("orders without a review", orders.review_score.isna().sum(), "kept; review score left blank")

    # --- Seller handover: did the seller ship after its deadline? -------------------------
    it = items.merge(orders[["order_id", "order_delivered_carrier_date"]], on="order_id")
    it["seller_late"] = (it.order_delivered_carrier_date > it.shipping_limit_date).astype(float)
    it.loc[it.order_delivered_carrier_date.isna(), "seller_late"] = float("nan")
    seller_late = it.groupby("order_id").seller_late.max()
    orders["seller_shipped_late"] = orders.order_id.map(seller_late).round().astype("Int64")

    inconsistent = orders.order_delivered_carrier_date < orders.order_approved_at
    note("carrier pickup before payment approval", inconsistent.sum(),
         "timestamp inconsistency in source; kept, not used in any measure")

    # --- Order value and basket ------------------------------------------------------------
    basket = items.groupby("order_id").agg(items=("order_item_id", "size"), sellers=("seller_id", "nunique"),
                                           order_value=("price", "sum"), freight_value=("freight_value", "sum"))
    orders = orders.join(basket, on="order_id")
    orders = orders.merge(customers[["customer_id", "customer_unique_id", "customer_city", "customer_state"]],
                          on="customer_id", how="left")

    fact_orders = pd.DataFrame({
        "order_id": orders.order_id,
        "customer_unique_id": orders.customer_unique_id,
        "customer_state": orders.customer_state,
        "customer_city": orders.customer_city.str.title(),
        "purchase_date": orders.order_purchase_timestamp.dt.date,
        "purchase_datetime": orders.order_purchase_timestamp,
        "estimated_delivery_date": orders.order_estimated_delivery_date.dt.date,
        "delivered_date": orders.order_delivered_customer_date.dt.date,
        "delivery_days": orders.delivery_days,
        "days_vs_estimate": orders.days_vs_estimate,
        "is_late": orders.is_late,
        "delivery_status": orders.is_late.map({0: "On time", 1: "Late"}),
        "delivery_bucket": orders.delivery_bucket,
        "delivery_bucket_sort": orders.delivery_bucket_sort,
        "seller_shipped_late": orders.seller_shipped_late,
        "review_score": orders.review_score.astype("Int64"),
        "items": orders["items"].astype("Int64"),
        "sellers": orders.sellers.astype("Int64"),
        "order_value": orders.order_value.round(2),
        "freight_value": orders.freight_value.round(2),
    }).sort_values("purchase_datetime")

    # --- Order items -------------------------------------------------------------------------
    fact_items = items[items.order_id.isin(fact_orders.order_id)][
        ["order_id", "order_item_id", "product_id", "seller_id", "price", "freight_value"]
    ]

    # --- Dimensions --------------------------------------------------------------------------
    extra = pd.DataFrame({"product_category_name": ["portateis_cozinha_e_preparadores_de_alimentos", "pc_gamer"],
                          "product_category_name_english": ["kitchen_portables_and_food_preparers", "pc_gamer"]})
    translation = pd.concat([translation, extra], ignore_index=True)
    missing_cat = products.product_category_name.isna().sum()
    note("products without a category", missing_cat, "labelled 'Unknown'")
    note("categories missing an English translation", 2, "translated manually")
    dim_products = products[["product_id", "product_category_name"]].merge(translation, how="left")
    dim_products["category"] = (dim_products.product_category_name_english.fillna("unknown")
                                .str.replace("_", " ").str.replace(r"\s+", " ", regex=True).str.strip().str.capitalize())
    dim_products = dim_products[["product_id", "category"]]

    dim_sellers = sellers.assign(seller_city=sellers.seller_city.str.title())[["seller_id", "seller_city", "seller_state"]]

    dim_states = pd.DataFrame([(k, *v) for k, v in STATES.items()],
                              columns=["state_code", "state_name", "region"])
    dim_states["country"] = "Brazil"

    MODEL.mkdir(parents=True, exist_ok=True)
    fact_orders.to_csv(MODEL / "fact_orders.csv", index=False)
    fact_items.to_csv(MODEL / "fact_order_items.csv", index=False)
    dim_products.to_csv(MODEL / "dim_products.csv", index=False)
    dim_sellers.to_csv(MODEL / "dim_sellers.csv", index=False)
    dim_states.to_csv(MODEL / "dim_states.csv", index=False)
    note("final: delivered orders in model", len(fact_orders), "")
    pd.DataFrame(log).to_csv(MODEL / "data_quality_log.csv", index=False)

    print(pd.DataFrame(log).to_string(index=False))
    for f in sorted(MODEL.glob("*.csv")):
        print(f"{f.name:28s} {len(pd.read_csv(f)):>8,} rows")


if __name__ == "__main__":
    download_if_missing()
    build()
