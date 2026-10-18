"""Generate the Power BI semantic model (TMDL) from the exported data and the DAX file.

Usage (from the repo root, after scripts/build_powerbi_data.py):
    python scripts/build_powerbi_tmdl.py

Writes powerbi/CommerceLens.SemanticModel/definition/:
    model.tmdl          model settings and table order
    expressions.tmdl    the DataFolder parameter (a placeholder; set the path in Desktop)
    relationships.tmdl  the six one-to-many, single-direction relationships
    tables/*.tmdl       one file per table: columns from the parquet schema, a
                        Parquet.Document partition, sort-by-column settings, the date
                        table marking, and every measure in powerbi/dax_measures.md

Measures are parsed from the ```dax blocks of powerbi/dax_measures.md, so the model
and the documented measures cannot drift apart. Before writing, the script checks
that every DAX reference resolves, relationship keys exist with matching types,
sort-by pairs are one-to-one in the data and the date table is contiguous.

STATUS: UNTESTED. Power BI Desktop is not available here, so these files have never
been opened. database.tmdl, definition.pbism, the .pbip file and the report folder
are not generated; powerbi/README.md explains how to take them from a blank project
saved by Desktop, so Desktop writes the version-specific files itself.
"""

import re
import sys
import uuid
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "powerbi" / "data"
DAX_MD = ROOT / "powerbi" / "dax_measures.md"
OUT = ROOT / "powerbi" / "CommerceLens.SemanticModel" / "definition"

# Tables loaded from parquet, in display order.
TABLES = ["fact_orders", "fact_order_items", "dim_customer", "dim_product", "dim_seller",
          "dim_state", "dim_date", "recon_sql", "recon_seller_state", "lane_lead_time", "model_metrics",
          "model_capture_curve", "shap_importance", "shap_state_effect", "model_curves",
          "model_target_comparison"]

# (many table, many column, one table, one column); filtering one -> many only.
RELATIONSHIPS = [
    ("fact_order_items", "order_id", "fact_orders", "order_id"),
    ("fact_order_items", "product_id", "dim_product", "product_id"),
    ("fact_order_items", "seller_id", "dim_seller", "seller_id"),
    ("fact_orders", "customer_unique_id", "dim_customer", "customer_unique_id"),
    ("fact_orders", "customer_state", "dim_state", "state_code"),
    ("fact_orders", "purchase_date", "dim_date", "date"),
]

SORT_BY = {  # (table, column) -> sort column
    ("fact_orders", "delay_bucket"): "delay_bucket_order",
    ("fact_orders", "freight_share_bucket"): "freight_bucket_order",
    ("dim_customer", "segment"): "segment_order",
    ("dim_date", "month_name"): "month_number",
    ("recon_sql", "metric"): "sort_order",
}

# Relationship keys on the many side, and sort helpers: hidden so report authors use
# the dimension columns and labels.
HIDDEN = {
    ("fact_orders", "customer_unique_id"), ("fact_orders", "customer_state"),
    ("fact_orders", "purchase_date"), ("fact_order_items", "order_id"),
    ("fact_order_items", "product_id"), ("fact_order_items", "seller_id"),
    ("fact_orders", "delay_bucket_order"), ("fact_orders", "freight_bucket_order"),
    ("dim_customer", "segment_order"), ("dim_date", "month_number"), ("recon_sql", "sort_order"),
}

# Fact and dimension numbers are only shown through measures; the Model page tables
# are pre-aggregated, so their numeric columns keep a default sum.
NO_IMPLICIT_SUM = {"fact_orders", "fact_order_items", "dim_customer", "dim_product",
                   "dim_seller", "dim_state", "dim_date", "recon_sql", "recon_seller_state",
                   "lane_lead_time"}

# Never a real path: the absolute path of powerbi/data/ differs per machine and would publish
# the local user name. It is set in Desktop (Transform data > Edit parameters > DataFolder).
DATA_FOLDER_PLACEHOLDER = "REPLACE_WITH_FULL_PATH_TO\\powerbi\\data\\"

ARROW_TO_TMDL = {"string": "string", "large_string": "string", "double": "double", "float": "double",
                 "int64": "int64", "int32": "int64", "bool": "boolean", "date32[day]": "dateTime"}

FOLDERS = [  # markdown heading keyword -> display folder
    ("Core measures", "1 Core"), ("Reconciliation measures", "2 Reconciliation"),
    ("Revenue page", "3 Revenue"), ("Satisfaction page", "4 Satisfaction"),
    ("Seller concentration", "4 Satisfaction"), ("Freight test", "5 Freight"),
    ("What-if", "6 What-if"), ("Formatting helpers", "9 Formatting"),
    ("Customers & RFM", "7 Customers"), ("Model page", "8 Model"),
]

COUNT_MEASURES = {"Total Orders", "Delivered Orders", "Customers", "Orders (delay scope)",
                  "Orders (review scope)", "Orders (seller/category)", "Reviewed Orders (seller/category)",
                  "Late Orders (review scope)", "Orders Rescued (what-if)",
                  "Low Reviews Avoided (upper bound)", "Checks Passed", "Checks Total", "Category Rank"}
DECIMAL_MEASURES = {"Revenue": "#,0.00", "AOV": "#,0.00", "Avg Review": "0.000",
                    "SQL Value": "#,0.000###", "DAX Value": "#,0.000###", "Diff": "#,0.000###",
                    "Tolerance": "#,0.000###", "Freight Gap On Time (pp)": "0.00",
                    "Lateness Gap (pp)": "0.00", "Lift at Flag %": "0.00", "Flag % Value": "0",
                    "ROC-AUC (LightGBM, test)": "0.000", "PR-AUC (LightGBM, test)": "0.000",
                    "ROC-AUC (LightGBM, out-of-time)": "0.000", "PR-AUC (LightGBM, out-of-time)": "0.000"}
TEXT_MEASURES = {"Status"}


def tag(*parts: str) -> str:
    """Deterministic lineageTag, so regenerating does not churn the files."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "commercelens/" + "/".join(parts)))


def q(name: str) -> str:
    """Quote a TMDL object name when it is not a plain identifier."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------- parse the DAX file
# A definition starts at column 0 with "Name =". VAR / RETURN lines and comments are
# part of an expression; a name never contains [ ] " or =.
DEF_START = re.compile(r"^(?!VAR\b|RETURN\b|--)([A-Za-z_%][^=\[\]\"]*?) =(?:\s(.*))?$")
COLUMN_REF = re.compile(r"(?:'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*))\[([^\]]+)\]")


def parse_dax(md: str) -> list[dict]:
    """Every definition in the ```dax blocks: name, expression, description, folder."""
    defs, folder = [], None
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            for key, name in FOLDERS:
                if key in line:
                    folder = name
        if line.strip() == "```dax":
            i += 1
            comments, cur = [], None
            while lines[i].strip() != "```":
                text = lines[i]
                m = DEF_START.match(text)
                if text.startswith("--"):
                    if cur:
                        defs.append(cur)
                        cur = None
                    comments.append(text[2:].strip())
                elif m:
                    if cur:
                        defs.append(cur)
                    cur = {"name": m.group(1).strip(), "lines": [m.group(2)] if m.group(2) else [],
                           "description": comments, "folder": folder}
                    comments = []
                elif cur is not None and text.strip():
                    cur["lines"].append(text)
                i += 1
            if cur:
                defs.append(cur)
        i += 1
    for d in defs:
        d["expression"] = "\n".join(d.pop("lines")).strip("\n")
        d["is_table"] = d["expression"].startswith("SELECTCOLUMNS ( GENERATESERIES")
    return defs


# ---------------------------------------------------------------- static checks
def static_checks(schemas: dict, defs: list[dict]) -> list[str]:
    """Return a list of problems (empty when everything resolves)."""
    problems = []
    measures = {d["name"] for d in defs if not d["is_table"]}
    calc_tables = {d["name"]: re.search(r'"([^"]+)", \[Value\]', d["expression"]).group(1)
                   for d in defs if d["is_table"]}
    columns = {t: set(s) for t, s in schemas.items()}
    columns.update({t: {c} for t, c in calc_tables.items()})
    names = [d["name"] for d in defs]
    for dup in {n for n in names if names.count(n) > 1}:
        problems.append(f"duplicate definition: {dup}")
    for d in defs:
        expr = d["expression"]
        if expr.count("(") != expr.count(")"):
            problems.append(f"{d['name']}: unbalanced parentheses")
        # table[column] and 'table name'[column]
        for quoted, plain, col in COLUMN_REF.findall(expr):
            table = quoted or plain
            if table not in columns:
                problems.append(f"{d['name']}: unknown table {table}")
            elif col not in columns[table]:
                problems.append(f"{d['name']}: unknown column {table}[{col}]")
        # bare [name]: a measure, a local @column, or GENERATESERIES' [Value]
        for ref in re.findall(r"(?<![A-Za-z0-9_'\]])\[([^\]]+)\]", expr):
            if ref not in measures and not ref.startswith("@") and ref != "Value":
                problems.append(f"{d['name']}: unknown measure [{ref}]")
    for many, mc, one, oc in RELATIONSHIPS:
        if schemas[many].get(mc) != schemas[one].get(oc):
            problems.append(f"relationship {many}.{mc} -> {one}.{oc}: type mismatch or missing column")
    for (table, col), sort_col in SORT_BY.items():
        df = pd.read_parquet(DATA / f"{table}.parquet", columns=[col, sort_col])
        per_value = df.drop_duplicates().groupby(col, dropna=False)[sort_col].nunique(dropna=False)
        if (per_value > 1).any():
            problems.append(f"sort-by {table}.{col} -> {sort_col}: not one-to-one")
    dates = pd.to_datetime(pd.read_parquet(DATA / "dim_date.parquet")["date"])
    if dates.duplicated().any() or dates.diff().dropna().dt.days.ne(1).any():
        problems.append("dim_date.date is not a unique contiguous daily range")
    return problems


# ---------------------------------------------------------------- writers
def format_string(name: str):
    if name in TEXT_MEASURES or name.endswith(("Color", "Color (state)", "Color (seller state)",
                                               "Color (category)")):
        return None
    if name in COUNT_MEASURES:
        return "#,0"
    if name in DECIMAL_MEASURES:
        return DECIMAL_MEASURES[name]
    return "0.00%" if "%" in name else "#,0.00"


def expression_block(expr: str, indent: int) -> str:
    """A TMDL value: inline when one line, else indented two levels below its owner."""
    lines = expr.splitlines()
    if len(lines) == 1:
        return " " + lines[0]
    pad = "\t" * (indent + 2)
    return "\n" + "\n".join(pad + ln for ln in lines)


def write_measure(d: dict) -> str:
    out = [f"\t/// {c}" for c in d["description"]]
    out.append(f"\tmeasure {q(d['name'])} ={expression_block(d['expression'], 1)}")
    fmt = format_string(d["name"])
    if fmt:
        out.append(f"\t\tformatString: {fmt}")
    out.append(f"\t\tdisplayFolder: {d['folder']}")
    out.append(f"\t\tlineageTag: {tag('measure', d['name'])}")
    return "\n".join(out)


def write_column(table: str, col: str, dtype: str) -> str:
    out = [f"\tcolumn {q(col)}", f"\t\tdataType: {dtype}"]
    if (table, col) == ("dim_date", "date"):
        out.append("\t\tisKey")
    if dtype == "dateTime":
        out.append("\t\tformatString: yyyy-mm-dd")
    if (table, col) in HIDDEN:
        out.append("\t\tisHidden")
    if (table, col) == ("dim_state", "state_name"):
        out.append("\t\tdataCategory: StateOrProvince")
    summarize = "none" if table in NO_IMPLICIT_SUM or dtype in ("string", "dateTime", "boolean") else "sum"
    out += [f"\t\tlineageTag: {tag('column', table, col)}", f"\t\tsummarizeBy: {summarize}",
            f"\t\tsourceColumn: {col}"]
    if (table, col) in SORT_BY:
        out.append(f"\t\tsortByColumn: {SORT_BY[(table, col)]}")
    return "\n".join(out)


def write_table(table: str, schema: dict) -> str:
    out = [f"table {q(table)}"]
    if table == "dim_date":
        out.append("\tdataCategory: Time")               # with isKey on [date]: marks the date table
    out.append(f"\tlineageTag: {tag('table', table)}")
    for col, dtype in schema.items():
        out += ["", write_column(table, col, dtype)]
    source = (f"let\n    Source = Parquet.Document(File.Contents(DataFolder & \"{table}.parquet\"))\n"
              "in\n    Source")
    out += ["", f"\tpartition {q(table)} = m", "\t\tmode: import",
            f"\t\tsource ={expression_block(source, 2)}", ""]
    return "\n".join(out) + "\n"


def write_calc_table(name: str, column: str, expression: str, hidden: bool = False) -> str:
    out = [f"table {q(name)}", f"\tlineageTag: {tag('table', name)}", "",
           f"\tcolumn {q(column)}", "\t\tdataType: int64", "\t\tformatString: 0"]
    if hidden:
        out.append("\t\tisHidden")
    out += [f"\t\tlineageTag: {tag('column', name, column)}", "\t\tsummarizeBy: none",
            "\t\tisNameInferred", f"\t\tsourceColumn: [{column}]", "",
            f"\tpartition {q(name)} = calculated", "\t\tmode: import", f"\t\tsource = {expression}", ""]
    return "\n".join(out)


def main() -> int:
    if not (DATA / "fact_orders.parquet").exists():
        print("powerbi/data/ is missing. Run: python scripts/build_powerbi_data.py")
        return 1
    if (OUT / "database.tmdl").exists() and "--force" not in sys.argv:
        # database.tmdl is only written by Power BI Desktop: the model has been opened and
        # saved there, and regenerating would overwrite Desktop's (tested) files.
        print(f"{OUT.relative_to(ROOT)} has been saved by Power BI Desktop (database.tmdl present). "
              "Not overwriting it; rerun with --force to regenerate anyway.")
        return 1
    schemas = {}
    for t in TABLES:
        s = pq.read_schema(DATA / f"{t}.parquet")
        schemas[t] = {n: ARROW_TO_TMDL[str(ty)] for n, ty in zip(s.names, s.types)}
    defs = parse_dax(DAX_MD.read_text(encoding="utf-8"))
    measures = [d for d in defs if not d["is_table"]]
    calc_tables = [d for d in defs if d["is_table"]]

    problems = static_checks(schemas, defs)
    print(f"Parsed {len(measures)} measures and {len(calc_tables)} parameter tables from {DAX_MD.name}")
    if problems:
        print("Static checks FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Static checks passed: DAX references, parentheses, relationship keys and types, "
          "sort-by pairs, date table")

    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "tables").glob("*.tmdl"):
        old.unlink()
    for t in TABLES:
        (OUT / "tables" / f"{t}.tmdl").write_text(write_table(t, schemas[t]), encoding="utf-8")
    for d in calc_tables:
        column = re.search(r'"([^"]+)", \[Value\]', d["expression"]).group(1)
        (OUT / "tables" / f"{d['name']}.tmdl").write_text(
            write_calc_table(d["name"], column, d["expression"]), encoding="utf-8")
    measures_tmdl = write_calc_table("_Measures", "Placeholder", 'ROW ( "Placeholder", 0 )', hidden=True)
    head, partition = measures_tmdl.split("\n\tpartition ", 1)
    body = "\n\n".join(write_measure(d) for d in measures)
    (OUT / "tables" / "_Measures.tmdl").write_text(f"{head}\n{body}\n\n\tpartition {partition}", encoding="utf-8")

    rel = []
    for many, mc, one, oc in RELATIONSHIPS:
        rel += [f"relationship {tag('relationship', many, mc, one, oc)}",
                f"\tfromColumn: {many}.{mc}", f"\ttoColumn: {one}.{oc}", ""]
    (OUT / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")

    (OUT / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DATA_FOLDER_PLACEHOLDER}" meta [IsParameterQuery=true, Type="Text", '
        f'IsParameterQueryRequired=true]\n\tlineageTag: {tag("expression", "DataFolder")}\n\n'
        "\tannotation PBI_ResultType = Text\n", encoding="utf-8")

    table_order = ["_Measures"] + TABLES + [d["name"] for d in calc_tables]
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects",
             "\t\treturnErrorValuesAsNull", "",
             # Auto date/time off: dim_date is the marked date table.
             "annotation __PBI_TimeIntelligenceEnabled = 0", ""]
    model += [f"ref table {q(t)}" for t in table_order]
    (OUT / "model.tmdl").write_text("\n".join(model) + "\n", encoding="utf-8")

    print(f"Wrote {len(table_order)} tables, {len(RELATIONSHIPS)} relationships, {len(measures)} measures "
          f"to {OUT.relative_to(ROOT)}")
    print(f"DataFolder parameter = {DATA_FOLDER_PLACEHOLDER} (placeholder; set it in Desktop)")
    print("STATUS: UNTESTED (never opened in Power BI Desktop). See powerbi/README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
