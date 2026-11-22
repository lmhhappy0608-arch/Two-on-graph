# Two on Graph

Two on Graph is a curriculum-network prototype for exploring Duke Kunshan University course relationships, prerequisite logic, recorded course offerings, and major completion requirements.

The current repository contains the validated NetworkX data/service layer and an early Streamlit interface. It is a research prototype, not an official degree-audit or course-planning system.

## Current capabilities

- Search courses by canonical code, alias, or course name.
- Inspect course metadata and recorded class sections.
- Evaluate prerequisite, prerequisite-or-corequisite, and anti-requisite rules.
- Explore upstream prerequisite subgraphs and structural paths.
- Evaluate verified major-completion rules across 39 majors/tracks.
- Keep database access read-only and separate from the Streamlit presentation layer.

## Validated data snapshot

- 824 canonical course nodes.
- 532 graph edges.
- 495 strict prerequisite-related edges.
- 227 verified completion rules.
- 31 advisory rules.
- 1 blocked rule requiring manual review.
- 670 major-rule test cases passing.

The bundled SQLite database is a project research snapshot derived from curriculum materials. Recorded sections indicate only that a course appeared in the captured terms; they do not predict future offerings.

## Project structure

```text
app/                         Read-only repositories and business services
data/curriculum.sqlite       Current validated curriculum database
data/major_rule_engine.py    Major-requirement evaluation engine
data/*.md                    Data audit and implementation reports
tests/                       Automated service and integrity tests
demo.py                      Streamlit prototype
requirements.txt             Python dependencies
```

## Run locally

Python 3.11 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m streamlit run demo.py
```

Open <http://localhost:8501> in the same computer's browser.

To make the prototype available to another device on the same trusted Wi-Fi network:

```bash
python3 -m streamlit run demo.py --server.address 0.0.0.0 --server.port 8501
```

Use the Network URL printed by Streamlit. Do not expose this development server directly to the public internet.

## Tests

```bash
python3 -m pytest -q
python3 data/run_major_rule_tests.py
```

## Important limitations

- This is not an official DKU degree audit.
- A shortest graph path is a structural relationship, not a feasible semester-by-semester plan.
- Non-strict requirements and blocked rules require human interpretation.
- Future course availability is not inferred from historical section records.
- The Streamlit interface is an early functional prototype and has not completed user testing or production deployment.

## Data and privacy

Personal applications, invoices, budgets, internal reports containing personal details, copyrighted research PDFs, caches, and superseded database snapshots are intentionally excluded from this repository.

