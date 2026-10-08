# Aletheia architecture

```mermaid
flowchart LR
    subgraph Sources
        A1[Customer request form]
        A2[Spreadsheets and CSV files]
        A3[Existing databases - SQLite]
        A4[Scanned log sheets - PDF or photo]
        A5[Legacy register of past tests]
    end
    subgraph Collection["Data collection - importers.py, vision.py"]
        B1[Tabular reader: section, field, value]
        B2[Source store with SHA-256]
        B3[Optional Gemini reader -> proposal]
        B4[Engineer review and edit]
    end
    subgraph Core["app.py"]
        C1[(SQLite: jobs, imports, sources, reports, audit)]
        C2[Validation engine: 30 checks]
        C3[Report engine: PDF template]
        C4[Frozen versions + QR verification]
    end
    D[Dashboard, search, preview, export]
    A1 --> C1
    A2 --> B1
    A3 --> B1
    A5 --> B1
    A4 --> B2 --> B3 --> B4
    B1 --> C1
    B4 --> C1
    C1 --> C2 -->|no failures| C3 --> C4 --> D
    C2 -->|failures| B4
    C1 --> D
```

Data flow: every source ends up as the same per-section structure in the `jobs` table. Any change to that data resets
the job to "Data imported", so validation and the report are always derived from what is stored. Reports are built once
per version and stored with their hash; the verification page recomputes the hash on request.

| Module | Responsibility |
|---|---|
| `importers.py` | Detect file type, read CSV / Excel / SQLite / JSON, convert between table rows and nested data, read legacy registers, export templates |
| `vision.py` | Send one source document to Gemini on request, enforce the daily limit, return a proposal only |
| `app.py` | REST API, SQLite storage and audit trail, validation rules, PDF layout, report versions |
| `static/index.html` | Single-page UI: dashboard, workflow, records, preview, architecture, verification |
