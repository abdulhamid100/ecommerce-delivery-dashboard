# Build guide: Power BI dashboard

Everything the report needs is prepared: clean tables, DAX measures, a colour theme and expected numbers to check against. This guide walks through assembling it in **Power BI Desktop** (free, Windows). Plan for about 1.5 hours.

At the end you save the report as `powerbi/ecommerce_delivery_dashboard.pbix` and export page screenshots to `images/`.

---

## Step 1 — Load the data (10 min)

1. **Home → Get data → Text/CSV**, and load each file from `data/model/`:
   - `fact_orders.csv`
   - `fact_order_items.csv`
   - `dim_products.csv`
   - `dim_sellers.csv`
   - `dim_states.csv`
2. In **Transform data (Power Query)**, check the column types:

| Table | Column | Type |
|---|---|---|
| fact_orders | purchase_date, estimated_delivery_date, delivered_date | Date |
| fact_orders | purchase_datetime | Date/Time |
| fact_orders | is_late, seller_shipped_late, review_score, items, sellers, days_vs_estimate, delivery_bucket_sort | Whole number |
| fact_orders | delivery_days, order_value, freight_value | Decimal number |
| fact_order_items | price, freight_value | Decimal number |

   Empty `review_score` and `seller_shipped_late` cells must stay **null**, not 0. Power Query does this automatically for empty CSV cells.
3. **Close & Apply**.

## Step 2 — Date table and relationships (10 min)

1. **Modeling → New table**, then paste the `Date` definition from `measures.dax`.
2. Select the `Date` table, then **Table tools → Mark as date table** → `Date[Date]`.
3. Select `Date[Month]`, then **Column tools → Sort by column** → `Year Month`.
4. Select `fact_orders[delivery_bucket]`, then **Sort by column** → `delivery_bucket_sort`.
5. In **Model view**, create these relationships:

| From (many) | To (one) | Cross-filter |
|---|---|---|
| fact_orders[purchase_date] | Date[Date] | Single |
| fact_orders[customer_state] | dim_states[state_code] | Single |
| fact_order_items[order_id] | fact_orders[order_id] | **Both** |
| fact_order_items[product_id] | dim_products[product_id] | Single |
| fact_order_items[seller_id] | dim_sellers[seller_id] | Single |

   *Why "Both" on the items–orders relationship:* product category and seller live on the item level. Without "Both", a category slicer would not filter the order-level measures (late rate, review score).

## Step 3 — Measures and theme (15 min)

1. **Home → Enter data**, create an empty table named `_Measures`, then load it.
2. Add every measure from section 2 of `measures.dax` to `_Measures` (**New measure**, then paste). Set the formats:
   - Percentages (`… Rate`, `Late Rate vs Average`, `Late Rate MoM Change`): **Percentage, 1 decimal**
   - Scores (`Avg Score …`, `Score Gap …`): **Decimal, 2 places**
   - `Revenue`: **Currency, 0 decimals**
   - `Avg Delivery Days`, `Avg Days Early vs Estimate`: **Decimal, 1 place**
3. **View → Themes → Browse for themes** → `powerbi/theme.json`.
4. Hide the technical columns from report view (`delivery_bucket_sort`, `Year Month`, `Weekday Number`, the ID columns).

## Step 4 — Page 1: "Overview" (25 min)

Canvas: 1280 × 720 (the default 16:9).

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title (dynamic: [Title Overview])                  [Month] [Region] [Cat]│
├───────────┬───────────┬───────────┬───────────┬──────────────────────────┤
│ Delivered │  On-Time  │ Avg score │ Avg score │  Negative review rate    │
│  Orders   │   Rate    │  on time  │   late    │   late vs on time        │
├───────────┴───────────┴───────────┼───────────┴──────────────────────────┤
│ Avg review score by delivery      │ Late delivery rate by month          │
│ timing (stacked column)           │ (line)                               │
│                                   │                                      │
└───────────────────────────────────┴──────────────────────────────────────┘
```

| Visual | Settings |
|---|---|
| **Title** | Text box, or a card visual with `Title Overview` |
| **Slicers** (top right) | `Date[Month]` (dropdown), `dim_states[region]` (dropdown), `dim_products[category]` (dropdown, with search on) |
| **4 KPI cards** | `Delivered Orders`, `On-Time Rate`, `Avg Score On Time`, `Avg Score Late` |
| **Clustered bar** (top right) | Y-axis: `delivery_status` · X-axis: `Negative Review Rate`. Title: "Share of 1–2 star reviews" |
| **Stacked column** | X-axis: `delivery_bucket` · Y-axis: `Avg Review Score` · Legend: `delivery_status`. Colours: On time = blue `#2a78d6`, Late = orange `#eb6834`. Data labels on. Title: "Ratings collapse as soon as an order is late" |
| **Line chart** | X-axis: `Date[Month]` · Y-axis: `Late Delivery Rate`. Line colour orange. Markers on. Title: "Late delivery rate by purchase month" |

A stacked column works for the bucket chart because each bucket is either all on-time or all late, so every column shows one colour.

## Step 5 — Page 2: "Where delays happen" (25 min)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title (dynamic: [Title Where])                     [Month] [Region] [Cat]│
├──────────────────────────────┬───────────────────────────────────────────┤
│ Late delivery rate by        │ State table (matrix)                      │
│ customer state (bar, sorted) │ state | orders | late rate | days | score │
│                              │                                           │
├──────────────────────────────┼─────────────────────┬─────────────────────┤
│ Late rate by region (bar)    │ Seller shipped late │ Late rate when      │
│                              │ rate (card)         │ seller late vs on   │
│                              │                     │ time (bar)          │
└──────────────────────────────┴─────────────────────┴─────────────────────┘
```

| Visual | Settings |
|---|---|
| **Clustered bar** | Y-axis: `dim_states[state_name]` · X-axis: `Late Delivery Rate`, sorted descending. Filter pane: `Delivered Orders` ≥ 300 (removes tiny states) |
| **Matrix** | Rows: `dim_states[state_name]` · Values: `Delivered Orders`, `Late Delivery Rate`, `Avg Delivery Days`, `Avg Review Score`, `State Rank by Late Rate`. Conditional formatting on `Late Delivery Rate`: data bars, orange |
| **Clustered bar** | Y-axis: `dim_states[region]` · X-axis: `Late Delivery Rate` |
| **Card** | `Seller Late Shipment Rate`, with the subtitle "of orders were handed to the carrier after the seller's deadline" |
| **Clustered bar** | Values: `Late Rate (Seller Shipped Late)` and `Late Rate (Seller Shipped On Time)` as two bars. Title: "Orders are late far more often when the seller ships late" |

Optional: a **Map** visual with `dim_states[state_name]` as location (set its data category to *State or Province*) and `Late Delivery Rate` as bubble size. This needs map visuals to be enabled in Options → Security.

## Step 6 — Check the numbers (10 min)

Clear all slicers and compare the report with `reference_numbers.md`. For example:

- `Delivered Orders` = 96,203
- `Late Delivery Rate` = 6.8%
- `Avg Score On Time` = 4.29, `Avg Score Late` = 2.27
- March 2018 late rate = 19.0%

If a number doesn't match, check the relationship directions in Step 2 first.

## Step 7 — Save and publish to the repo (5 min)

1. Save as `powerbi/ecommerce_delivery_dashboard.pbix`.
2. Export a screenshot of each page (**File → Export → Export to PDF**, or a screen capture) and save them as `images/dashboard_overview.png` and `images/dashboard_where.png`.
3. Add both screenshots to the top of the README (there is a marked spot for them) and push.
4. Optional: if you have Power BI Service access (for example through a university account), use **Publish to web** and add the public link to the README.
