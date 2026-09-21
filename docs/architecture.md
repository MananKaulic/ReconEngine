# Architecture & Process Diagrams

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
