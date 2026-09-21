"""
scripts/generate_diagrams.py
-----------------------------
Renders four Graphviz PNG diagrams into docs/diagrams/ and writes
docs/architecture.md containing the equivalent Mermaid sources (per the
project spec: "Graphviz PNG plus Mermaid in docs/architecture.md").
"""
from pathlib import Path

import graphviz

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "diagrams"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def render(g: graphviz.Digraph, name: str):
    g.render(filename=name, directory=str(OUT_DIR), format="png", cleanup=True)
    print(f"Rendered {OUT_DIR / (name + '.png')}")


# ---------------------------------------------------------------------------
# 1. End-to-end process flow
# ---------------------------------------------------------------------------
flow = graphviz.Digraph("process_flow", graph_attr={"rankdir": "LR", "fontsize": "10"})
flow.attr("node", shape="box", style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica")
steps = [
    "Custodian\npositions.csv", "Internal\npositions.csv", "Security\nmaster.csv",
    "1. Validate", "2. Standardise", "3. Match", "4. Compare",
    "5. Classify\n(root cause)", "6. Prioritise", "7. Suggest\naction", "8. KPIs",
    "Break blotter\n+ Excel report",
]
for s in steps:
    flow.node(s)
flow.edge("Custodian\npositions.csv", "1. Validate")
flow.edge("Internal\npositions.csv", "1. Validate")
flow.edge("Security\nmaster.csv", "1. Validate")
flow.edge("1. Validate", "2. Standardise")
flow.edge("2. Standardise", "3. Match")
flow.edge("3. Match", "4. Compare")
flow.edge("4. Compare", "5. Classify\n(root cause)")
flow.edge("5. Classify\n(root cause)", "6. Prioritise")
flow.edge("6. Prioritise", "7. Suggest\naction")
flow.edge("7. Suggest\naction", "8. KPIs")
flow.edge("8. KPIs", "Break blotter\n+ Excel report")
render(flow, "process_flow")

# ---------------------------------------------------------------------------
# 2. Architecture diagram
# ---------------------------------------------------------------------------
arch = graphviz.Digraph("architecture", graph_attr={"rankdir": "TB", "fontsize": "10"})
arch.attr("node", shape="box", style="rounded,filled", fontname="Helvetica")
with arch.subgraph(name="cluster_ui") as c:
    c.attr(label="UI (Streamlit) — thin, no business logic", style="dashed")
    c.node("app.py", fillcolor="#fdebd0")
with arch.subgraph(name="cluster_engine") as c:
    c.attr(label="recon_engine (pure Python, no Streamlit/network)", style="dashed")
    for m in ["config.py", "models.py", "validation.py", "security_master.py",
              "standardise.py", "matching.py", "classify.py", "prioritise.py",
              "kpis.py", "report.py"]:
        c.node(m, fillcolor="#eaf2e3")
arch.node("tolerances.yaml", shape="note", fillcolor="#fef9e7")
arch.node("CSV inputs", shape="folder", fillcolor="#f4ecf7")
arch.edge("CSV inputs", "app.py")
arch.edge("tolerances.yaml", "config.py")
arch.edge("app.py", "report.py", label="calls run_reconciliation()")
arch.edge("report.py", "validation.py")
arch.edge("report.py", "security_master.py")
arch.edge("report.py", "standardise.py")
arch.edge("report.py", "matching.py")
arch.edge("report.py", "classify.py")
arch.edge("report.py", "prioritise.py")
arch.edge("report.py", "kpis.py")
arch.edge("config.py", "report.py")
arch.edge("models.py", "report.py", style="dotted")
render(arch, "architecture")

# ---------------------------------------------------------------------------
# 3. Security master mapping flow
# ---------------------------------------------------------------------------
sm = graphviz.Digraph("security_master_mapping", graph_attr={"rankdir": "LR", "fontsize": "10"})
sm.attr("node", shape="box", style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica")
sm.node("Custodian\nsecurity code")
sm.node("Lookup in\nsecurity master")
sm.node("Found?", shape="diamond", fillcolor="#fdebd0")
sm.node("Ambiguous?\n(code -> 2+ IDs)", shape="diamond", fillcolor="#fdebd0")
sm.node("Active &\neffective?", shape="diamond", fillcolor="#fdebd0")
sm.node("internal_security_id\n(resolved)", fillcolor="#eafaf1")
sm.node("SETUP break\n(unmapped / ambiguous /\ninactive / not-yet-effective)", fillcolor="#fadbd8")
sm.node("Apply unit_multiplier\n+ asset-class tolerance")
sm.edge("Custodian\nsecurity code", "Lookup in\nsecurity master")
sm.edge("Lookup in\nsecurity master", "Found?")
sm.edge("Found?", "SETUP break\n(unmapped / ambiguous /\ninactive / not-yet-effective)", label="no")
sm.edge("Found?", "Ambiguous?\n(code -> 2+ IDs)", label="yes")
sm.edge("Ambiguous?\n(code -> 2+ IDs)", "SETUP break\n(unmapped / ambiguous /\ninactive / not-yet-effective)", label="yes")
sm.edge("Ambiguous?\n(code -> 2+ IDs)", "Active &\neffective?", label="no")
sm.edge("Active &\neffective?", "SETUP break\n(unmapped / ambiguous /\ninactive / not-yet-effective)", label="no")
sm.edge("Active &\neffective?", "internal_security_id\n(resolved)", label="yes")
sm.edge("internal_security_id\n(resolved)", "Apply unit_multiplier\n+ asset-class tolerance")
render(sm, "security_master_mapping")

# ---------------------------------------------------------------------------
# 4. Root-cause decision tree
# ---------------------------------------------------------------------------
dt = graphviz.Digraph("root_cause_decision_tree", graph_attr={"rankdir": "TB", "fontsize": "10"})
dt.attr("node", shape="box", style="rounded,filled", fontname="Helvetica")
dt.node("Break candidate\n(fails COMPARE)", fillcolor="#fdebd0")
dt.node("Setup issue?\n(unmapped/inactive/\nnot-yet-effective/ambiguous)", shape="diamond", fillcolor="#eef3fb")
dt.node("SETUP", fillcolor="#fadbd8")
dt.node("Currency\nmismatch?", shape="diamond", fillcolor="#eef3fb")
dt.node("CCY_MISMATCH", fillcolor="#fadbd8")
dt.node("Explained by an\nunsettled pending trade?", shape="diamond", fillcolor="#eef3fb")
dt.node("TIMING", fillcolor="#fadbd8")
dt.node("Explained by a corporate\naction processed 1 side only?", shape="diamond", fillcolor="#eef3fb")
dt.node("CORP", fillcolor="#fadbd8")
dt.node("Quantity OK,\nvalue differs on price?", shape="diamond", fillcolor="#eef3fb")
dt.node("PRICE", fillcolor="#fadbd8")
dt.node("Matches a recent\ntrade booking?", shape="diamond", fillcolor="#eef3fb")
dt.node("TRADE", fillcolor="#fadbd8")
dt.node("UNEXPLAINED\n(honest fallback)", fillcolor="#fadbd8")

dt.edge("Break candidate\n(fails COMPARE)", "Setup issue?\n(unmapped/inactive/\nnot-yet-effective/ambiguous)")
dt.edge("Setup issue?\n(unmapped/inactive/\nnot-yet-effective/ambiguous)", "SETUP", label="yes")
dt.edge("Setup issue?\n(unmapped/inactive/\nnot-yet-effective/ambiguous)", "Currency\nmismatch?", label="no")
dt.edge("Currency\nmismatch?", "CCY_MISMATCH", label="yes")
dt.edge("Currency\nmismatch?", "Explained by an\nunsettled pending trade?", label="no")
dt.edge("Explained by an\nunsettled pending trade?", "TIMING", label="yes")
dt.edge("Explained by an\nunsettled pending trade?", "Explained by a corporate\naction processed 1 side only?", label="no")
dt.edge("Explained by a corporate\naction processed 1 side only?", "CORP", label="yes")
dt.edge("Explained by a corporate\naction processed 1 side only?", "Quantity OK,\nvalue differs on price?", label="no")
dt.edge("Quantity OK,\nvalue differs on price?", "PRICE", label="yes")
dt.edge("Quantity OK,\nvalue differs on price?", "Matches a recent\ntrade booking?", label="no")
dt.edge("Matches a recent\ntrade booking?", "TRADE", label="yes")
dt.edge("Matches a recent\ntrade booking?", "UNEXPLAINED\n(honest fallback)", label="no")
render(dt, "root_cause_decision_tree")

# ---------------------------------------------------------------------------
# Mermaid sources (docs/architecture.md)
# ---------------------------------------------------------------------------
mermaid_md = """# Architecture & Process Diagrams

PNG renders of all four diagrams live in `docs/diagrams/`. Mermaid sources
(for quick viewing on GitHub / in any Mermaid-aware viewer) are below.

## 1. End-to-end process flow

```mermaid
flowchart LR
    A[Custodian positions.csv] --> V[1. Validate]
    B[Internal positions.csv] --> V
    C[Security master.csv] --> V
    V --> S[2. Standardise]
    S --> M[3. Match]
    M --> CMP[4. Compare]
    CMP --> CLS[5. Classify root cause]
    CLS --> P[6. Prioritise]
    P --> SUG[7. Suggest action]
    SUG --> K[8. KPIs]
    K --> OUT[Break blotter + Excel report]
```

## 2. Architecture

```mermaid
flowchart TB
    subgraph UI["UI (Streamlit) - thin, no business logic"]
        APP[app.py]
    end
    subgraph ENGINE["recon_engine (pure Python)"]
        CONFIG[config.py]
        MODELS[models.py]
        VALID[validation.py]
        SECM[security_master.py]
        STD[standardise.py]
        MATCH[matching.py]
        CLASSIFY[classify.py]
        PRIOR[prioritise.py]
        KPIS[kpis.py]
        REPORT[report.py]
    end
    YAML[tolerances.yaml] --> CONFIG
    CSVS[CSV inputs] --> APP
    APP -->|run_reconciliation| REPORT
    REPORT --> VALID
    REPORT --> SECM
    REPORT --> STD
    REPORT --> MATCH
    REPORT --> CLASSIFY
    REPORT --> PRIOR
    REPORT --> KPIS
    CONFIG --> REPORT
    MODELS -.-> REPORT
```

## 3. Security master mapping flow

```mermaid
flowchart LR
    CODE[Custodian security code] --> LOOKUP[Lookup in security master]
    LOOKUP --> FOUND{Found?}
    FOUND -- no --> SETUP1[SETUP break]
    FOUND -- yes --> AMBIG{Ambiguous? code maps to 2+ IDs}
    AMBIG -- yes --> SETUP1
    AMBIG -- no --> ACTIVE{Active and effective?}
    ACTIVE -- no --> SETUP1
    ACTIVE -- yes --> RESOLVED[internal_security_id resolved]
    RESOLVED --> MULT[Apply unit_multiplier + asset-class tolerance]
```

## 4. Root-cause decision tree

```mermaid
flowchart TB
    START[Break candidate: fails COMPARE] --> SETUPQ{Setup issue? unmapped/inactive/not-yet-effective/ambiguous}
    SETUPQ -- yes --> SETUP[SETUP]
    SETUPQ -- no --> CCYQ{Currency mismatch?}
    CCYQ -- yes --> CCY[CCY_MISMATCH]
    CCYQ -- no --> TIMEQ{Explained by unsettled pending trade?}
    TIMEQ -- yes --> TIMING[TIMING]
    TIMEQ -- no --> CORPQ{Explained by corporate action processed one side only?}
    CORPQ -- yes --> CORP[CORP]
    CORPQ -- no --> PRICEQ{Quantity OK, value differs on price?}
    PRICEQ -- yes --> PRICE[PRICE]
    PRICEQ -- no --> TRADEQ{Matches a recent trade booking?}
    TRADEQ -- yes --> TRADE[TRADE]
    TRADEQ -- no --> UNEXPLAINED[UNEXPLAINED - honest fallback]
```
"""

(ROOT / "docs" / "architecture.md").write_text(mermaid_md)
print("Wrote docs/architecture.md")
