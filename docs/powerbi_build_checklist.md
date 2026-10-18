# Power BI build checklist (manual steps in Power BI Desktop)

Everything up to the parquet files, the DAX text and the TMDL files has been generated and checked
in code. The steps below need Power BI Desktop and have **not** been run yet. Do them in order.
Tick each box as you go; the last section lists what to commit.

Before you start (PowerShell, repo root):

```powershell
.venv-powerbi\Scripts\python scripts/build_powerbi_data.py       # must end with "All checks passed."
.venv-powerbi\Scripts\python scripts/verify_powerbi_measures.py  # must end with "N/N checks match." (1912/1912 now)
```

**Shortcut:** `powerbi/README.md` describes opening the generated TMDL model (tables, relationships,
date table, sort-by, measures already defined). If that works, skip to step 6. If Desktop rejects
it, build by hand from step 1. Either way, steps 6 onward are the same.

## 1. Settings and data load

- [ ] **File > Options and settings > Options > Current File > Data Load**: untick *Autodetect new
      relationships after data is loaded* (otherwise Desktop links tables by column name, e.g.
      `shap_state_effect[customer_state]` to `fact_orders`). Same dialog, **Time intelligence**:
      untick *Auto date/time*. OK.
- [ ] **Home > Transform data** (opens Power Query). **Home > Manage Parameters > New Parameter**:
      Name `DataFolder`, Type *Text*, Current value the full path to the repo's `powerbi\data\`
      folder **with a trailing backslash**. OK.
- [ ] **Home > New Source > Blank Query**, then **Home > Advanced Editor**, paste and click Done:
      ```
      let
          Source = Parquet.Document(File.Contents(DataFolder & "fact_orders.parquet"))
      in
          Source
      ```
      In the Query Settings pane, rename the query `fact_orders`.
- [ ] Right-click `fact_orders` > **Duplicate**; in the Advanced Editor change the file name; rename.
      Repeat until there are 16 queries: `fact_orders`, `fact_order_items`, `dim_customer`,
      `dim_product`, `dim_seller`, `dim_state`, `dim_date`, `recon_sql`, `recon_seller_state`,
      `lane_lead_time` (optional page), `model_metrics`, `model_capture_curve`, `shap_importance`,
      `shap_state_effect`, `model_curves`, `model_target_comparison`.
- [ ] Spot-check types (icon in each column header): dates show the calendar icon
      (`purchase_date`, `dim_date[date]`), `price` / `items_value` show 1.2 (decimal), flags such as
      `is_delivered` show 123 (whole number). Parquet carries the types, so no change should be needed.
- [ ] **Home > Close & Apply**. Row counts in the Data pane / Table view must be: fact_orders 99,441;
      fact_order_items 112,650; dim_customer 96,096; dim_product 32,951; dim_seller 3,095; dim_state 27;
      dim_date 791.

## 2. Relationships

- [ ] **Model view > Home > Manage relationships**. Delete anything Desktop created on its own.
- [ ] **New...** six times. For each: pick the two tables and columns below, Cardinality
      *Many to one (\*:1)*, Cross filter direction *Single*, *Make this relationship active* ticked.

      | Table (many) | Column | Table (one) | Column |
      |---|---|---|---|
      | fact_order_items | order_id | fact_orders | order_id |
      | fact_order_items | product_id | dim_product | product_id |
      | fact_order_items | seller_id | dim_seller | seller_id |
      | fact_orders | customer_unique_id | dim_customer | customer_unique_id |
      | fact_orders | customer_state | dim_state | state_code |
      | fact_orders | purchase_date | dim_date | date |

- [ ] Confirm: no relationship touches `recon_sql`, `recon_seller_state`, `lane_lead_time` or the six
      model tables.

## 3. Date table

- [ ] In the Data pane select `dim_date` > **Table tools > Mark as date table** > Date column `date` >
      OK (Desktop validates that dates are unique and contiguous).

## 4. Sort-by-column, categories, hidden columns

- [ ] **Table view**, click the column, then **Column tools > Sort by column**:
      `fact_orders[delay_bucket]` → `delay_bucket_order`;
      `fact_orders[freight_share_bucket]` → `freight_bucket_order`;
      `dim_customer[segment]` → `segment_order`;
      `dim_date[month_name]` → `month_number`;
      `recon_sql[metric]` → `sort_order`.
- [ ] `dim_state[state_name]` > **Column tools > Data category** > *State or Province*.
- [ ] Right-click > **Hide in report view**: `fact_orders[customer_unique_id]`,
      `fact_orders[customer_state]`, `fact_orders[purchase_date]`, `fact_order_items[order_id]`,
      `[product_id]`, `[seller_id]`, and the four sort columns above (optional, keeps the field list clean).

## 5. `_Measures` table and the measures

- [ ] **Home > Enter data**. Name the table `_Measures`, leave one empty column, **Load**.
- [ ] **Modeling > New table** for each parameter table in `powerbi/dax_measures.md`:
      `Late Cut = ...` and `Flag % = ...`.
- [ ] Select `_Measures` in the Data pane. For every measure in `powerbi/dax_measures.md`, **in file
      order** (each measure only uses measures defined above it): **Home > New measure**, paste the
      definition, press Enter, then set **Measure tools > Format**: counts *Whole number* with
      thousands separator; Revenue / AOV *Decimal*, 2 places; every `%` measure *Percentage*,
      2 places; Avg Review 3 places; `(pp)` measures *Decimal*, 2 places; colour measures none.
- [ ] Hide the placeholder column in `_Measures`; the table moves to the top of the Data pane with
      the calculator icon.

## 6. Reconciliation page (do this before any report page)

- [ ] Rename the first page **Reconciliation**. Add a **Table** visual with, in this order:
      `recon_sql[metric]`, `[SQL Value]`, `[DAX Value]`, `[Diff]`, `[Tolerance]`, `[Status]`,
      `recon_sql[sql_source]`. Format > Totals: off.
- [ ] Two **Card** visuals: `[Checks Passed]` and `[Checks Total]`.
- [ ] Expected: **14 rows, every Status = "Match", Checks Passed = 14, Checks Total = 14**. The SQL
      values are listed in `powerbi/dax_measures.md` under "Values the SQL layer produced on the
      real dataset".
- [ ] If a row says "Mismatch": write down the metric, DAX Value and SQL Value, do not edit
      `recon_sql`, and check the measure text against `powerbi/dax_measures.md` and the relationship
      list in step 2. `scripts/verify_powerbi_measures.py` shows the value the logic should produce.
- [ ] Optional second check: a table with `dim_seller[seller_state]`, `[Orders (seller/category)]`,
      `[Late % (seller/category)]` next to a table of `recon_seller_state` (same values, 22 states).

## 7. Report pages

See [Report pages](#report-pages-fields-measures-filters) below for every visual's fields,
measures and filters. Page order: Overview, Revenue, Customers & RFM, Satisfaction drivers,
Risk model, Findings, Reconciliation.

## 8. Theme and colour rules

- [ ] **View > Themes > Browse for themes** > `powerbi/CommerceLens-theme.json`. First series colour
      is blue `#2a78d6`; the other series colours are blues and greys, so orange never appears by
      default.
- [ ] Orange `#eb6834` only for late or above-average values, through **Format > Columns/Bars >
      Colors > fx > Format style: Field value** with the colour measures: `Delay Bucket Color`
      (delay-bucket chart), `Late % Color (state)`, `Late % Color (seller state)`,
      `Low Review Color (category)`.
- [ ] Reference lines grey (Analytics pane > Constant line, colour `#8a94a6`). No dual-axis charts;
      Pareto bars and the cumulative curve are two separate visuals.

## 9. Save, export, screenshots

- [ ] **File > Save as > Power BI project (\*.pbip)** as `powerbi\CommerceLens.pbip` (if you opened
      the generated project, just **File > Save**). From then on, Desktop owns
      `powerbi/CommerceLens.SemanticModel/`; `scripts/build_powerbi_tmdl.py` refuses to overwrite it
      unless run with `--force`.
- [ ] Optional: **File > Save as** `CommerceLens.pbix` for sharing. Keep it out of git: it embeds every
      row of the dataset (the repo does not redistribute the raw data) and is large. The `.pbip`
      folders hold the model and report as text without data.
- [ ] **File > Export > Export to PDF** > save as `docs\powerbi\CommerceLens.pdf`.
- [ ] One screenshot per page (canvas only, Win+Shift+S), saved as PNG in `docs\powerbi\screenshots\`:
      `01-overview.png`, `02-revenue.png`, `03-customers-rfm.png`, `04-satisfaction.png`,
      `05-risk-model.png`, `06-findings.png`, `07-reconciliation.png`. The reconciliation screenshot is
      the evidence that the DAX measures match SQL in Power BI.

## 10. Commit (locally; push when ready)

```powershell
git add powerbi/CommerceLens.pbip powerbi/CommerceLens.Report powerbi/CommerceLens.SemanticModel docs/powerbi
git status   # .pbi/cache.abf and .pbi/localSettings.json are gitignored; no *.pbix, no powerbi/data
git commit -m "Add Power BI report (PBIP), PDF export and screenshots"
```

After this, update the status labels in `README.md` and `powerbi/README.md`: DAX measures become
VERIFIED once the Reconciliation page shows 14/14 "Match"; the TMDL route becomes tested once it opens.

---

## Report pages: fields, measures, filters

Every measure is in the `_Measures` table. "Page filter" means the Filters pane, *Filters on this
page*. Card titles carry the label in quotes where one is required.

### 1. Overview

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| 7 cards | `Revenue`, `Delivered Orders`, `AOV`, `Customers`, `Repeat Customer %`, `Avg Review`, `Late %` | `Late %` card subtitle: "delivered orders with a delivery date" |
| Line: monthly revenue | X `dim_date[month_start]`, Y `Revenue` | Page filter `dim_date[is_partial_edge]` = False |
| Line: monthly late rate | X `dim_date[month_start]`, Y `Late %` | same page filter |
| Slicers | `dim_date[date]` (Between), `dim_state[state_code]` (dropdown) | — |

### 2. Revenue

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| Bar: top categories | Y `dim_product[category]`, X `Revenue Share` | Visual filter on `category`: Top N 15 by `Revenue`; sort by `Revenue Share` descending |
| Line: Pareto curve | X `dim_product[category]`, Y `Cumulative Revenue %` | Sort axis by `Revenue` descending; constant line 0.8 (grey); no Top N filter (the curve covers all 74 categories) |
| Line: monthly revenue | X `dim_date[month_start]`, Y `Revenue` | Page filter `dim_date[is_partial_edge]` = False |
| Column: MoM growth | X `dim_date[month_start]`, Y `Revenue MoM %` | same page filter; blank months are the sql/06 rule (previous month < 500 orders) |
| Table: monthly detail | `dim_date[year_month]`, `Delivered Orders`, `Revenue`, `AOV`, `Revenue MoM %` | same page filter |
| Bar (or filled map): revenue by state | `dim_state[state_code]` (map: `dim_state[state_name]`), `Revenue` | Sort descending. Bar is the safe default; map placement of Brazilian states is not verified |

### 3. Customers & RFM

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| Cards | `Customers`, `Repeat Customer %` | — |
| Clustered bar | Y `dim_customer[segment]`, X `% of Customers (segment)` and `% of Revenue (segment)` | Visual filter `segment` is not "No delivered order"; sorted by `segment_order` |
| Table | `dim_customer[segment]`, `Customers`, `Revenue`, `% of Revenue (segment)` | same filter |

### 4. Satisfaction drivers

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| Slicer: late cut | `'Late Cut'[Late Cut %]` | Single select; default 50 |
| What-if cards | `Orders Rescued (what-if)`, `Low Reviews Avoided (upper bound)`, `Low Reviews Avoided % (upper bound)` | Titles end with "(upper bound)". At 50% the logic gives 3,190.50 and 1,695.83 (Streamlit shows 3,190 / 1,696); note what the card displays |
| Cards: the gap | `Low Review % (Late)`, `Low Review % (On time)`, `Lateness Gap (pp)`, `Late % (reviewed)` | `Late % (reviewed)` subtitle: "reviewed orders" |
| Column: delay vs review | X `fact_orders[delay_bucket]`, Y `Low Review %`; tooltip `Orders (review scope)`, `% of Orders (delay bucket)` | Colour: fx > Field value > `Delay Bucket Color` |
| Scatter: states | Values `dim_state[state_code]`, X `Late %`, Y `Low Review %`, Size `Orders (delay scope)` | — |
| Bar: late % by customer state | Y `dim_state[state_code]`, X `Late %` | Colour fx `Late % Color (state)`; constant line = national `Late %` (grey) |
| Bar: late % by seller state | Y `dim_seller[seller_state]`, X `Late % (seller/category)` | Visual filter `Orders (seller/category)` >= 30; colour fx `Late % Color (seller state)` |
| Bar: categories | Y `dim_product[category]`, X `Low Review % (seller/category)` | Top N 15 by `Revenue`; colour fx `Low Review Color (category)`; constant line = overall `Low Review %` (grey) |
| Column: freight test | X `fact_orders[freight_share_bucket]`, Y `Low Review % (On time)`; tooltip `Orders (review scope)`, `Late % (reviewed)` | — |
| Cards: freight vs lateness | `Freight Gap On Time (pp)`, `Lateness Gap (pp)` | Side by side |
| Table: seller tiers | `dim_seller[seller_tier]`, `Revenue`, `% of Revenue (seller)`, `Late % (seller/category)` | Filter `seller_tier` is not "No delivered sales" |

### 5. Risk model

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| Cards | `ROC-AUC (LightGBM, test)`, `PR-AUC (LightGBM, test)`, `ROC-AUC (LightGBM, out-of-time)`, `PR-AUC (LightGBM, out-of-time)` | Label the out-of-time pair as the fair estimate |
| Slicer: flag % | `'Flag %'[Flag %]` | Single select; default 10 |
| Triage cards | `Recall at Flag %`, `Precision at Flag %`, `Lift at Flag %` | — |
| Line: gain curve | X `model_capture_curve[top_frac]` (continuous), Y `recall_at_top` | — |
| Bar: drivers | Y `shap_importance[feature]`, X `mean_abs_shap` | Top N 15 by `mean_abs_shap` |
| Bar: state effect | Y `shap_state_effect[customer_state]`, X `mean_shap` | Sort descending |
| Line: ROC | X `model_curves[x]` (continuous), Y `model_curves[y]`, Legend `model_curves[model]` | Visual filter `curve` = ROC |
| Line: PR | same fields | Visual filter `curve` = PR |
| Table | all columns of `model_target_comparison` | — |

### 6. Findings

One text box per README finding (problem → finding → so what → action). Insert numbers with the
text box's **+ Value** option (type the measure name, e.g. `Low Review % (Late)`), so no figure is
typed. The measures per finding are listed in `docs/powerbi_requirements_map.md`.

### 7. Reconciliation

As built in step 6.

### 8. Lead time (optional, exploratory; see `docs/lead_time_by_lane.md`)

| Visual | Fields / measures | Filters and settings |
|---|---|---|
| Table | all columns of `lane_lead_time` | Sort by `orders` descending |
| Bar: promise gap | Y `lane_lead_time[lane]`, X `gap_p95_vs_avg_promise_days` | Visual filter `orders` >= 200; sort descending; colour orange only where the gap is above 0 (fx > Rules: value > 0 → `#eb6834`, else `#2a78d6`) |
| Slicers | `lane_lead_time[seller_state]`, `lane_lead_time[customer_state]` | — |

Title the page "Lead time (exploratory)"; it is not part of the README findings yet.
