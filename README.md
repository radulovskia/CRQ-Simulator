# LoadLine

LoadLine is a cyber risk quantification (CRQ) application built on the FAIR decomposition of risk. It keeps an inventory of an organisation's units, systems, business processes and software components, adds threat and vulnerability evidence, and turns three-point scenario estimates into distributions of annual loss. It then tests the portfolio against a recorded risk appetite, ranks and selects control investments inside a budget, and issues a sealed, hash-verified board report with an approval record.

| | |
|---|---|
| Model version | 2.1.0 |
| Benchmark table | 2026.10 (shipped default) |
| Backend | Python 3.12, FastAPI, NumPy, PostgreSQL 16 |
| Frontend | Static HTML and JavaScript behind nginx |

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)
- [How the model works](#how-the-model-works)
- [Catalogs and uploads](#catalogs-and-uploads)
- [HTTP interface](#http-interface)
- [External data sources](#external-data-sources)
- [Documentation](#documentation)

## Features

- **Inventory.** Organisational units, software systems, business processes and software components, each with CSV/XLSX upload, inline editing, export and referential protection.
- **Intelligence.** A local copy of the MITRE ATT&CK Enterprise dataset with search and category filters, a component vulnerability scan (OSV, NVD, FIRST EPSS, CISA KEV), threat actors and attack vectors with ATT&CK identifiers checked against the loaded dataset.
- **Risk scenarios.** One actor, one vector and one target per scenario, with a worksheet of three-point estimates and a benchmark-driven *Suggest* that explains every proposed value.
- **Controls.** A control catalog, scenario-specific mappings with percentage overrides and an *Eliminates Risk* switch, and three loss views: inherent, current and target.
- **Simulation.** Beta-PERT inputs, Poisson event counts, primary and secondary loss forms, VaR and TVaR, reproducible by seed. A standalone sandbox simulates a single frequency and magnitude pair.
- **Portfolio.** A three-view register, an appetite test (portfolio loss, VaR95, per-scenario tolerance) and an investment analysis with benefit-cost ratio, return on security investment and a budget-constrained recommendation.
- **Governance.** A board report (PDF), a decision log with SHA-256 verification, and a one-time approval.
- **Settings.** An editable, versioned benchmark table that drives Suggest.

## Quick start

Requirements: Docker with Compose. Outbound internet access is needed only for the MITRE download and the vulnerability scan.

```bash
docker compose up -d --build
```

| Address | Purpose |
|---|---|
| http://localhost:8080 | Web application |
| http://localhost:8000 | API (the web application also proxies it) |
| http://localhost:8080/health | Health check, returns `{"status":"ok","model_version":"2.1.0"}` |

Useful commands:

```bash
docker compose logs -f backend     # follow the API log
docker compose down                # stop, keep the data
docker compose down -v             # stop and delete the database volume
```

The `demo/` folder contains a small bank-style catalog (CSV and XLSX files plus a reference appetite file) that exercises every screen.

## Architecture

```mermaid
flowchart LR
  browser[Browser] -->|8080| nginx[frontend: nginx]
  nginx -->|static pages| browser
  nginx -->|API paths| api[backend: FastAPI + NumPy]
  api --> pg[(PostgreSQL 16)]
  api -->|download| mitre[MITRE ATT&CK on GitHub]
  api -->|scan| feeds[OSV, NVD, FIRST EPSS, CISA KEV]
```

| Service | Image | Port | Role |
|---|---|---|---|
| `postgres` | `postgres:16` | internal 5432 | Three databases on one server, volume `crq-postgres` |
| `backend` | Python 3.12 slim, multi-stage build | host 8000 | Catalogs, scan, simulation, treatment, reports |
| `frontend` | `nginx:1.27-alpine` | host 8080 | Static pages, API reverse proxy, `Cache-Control: no-cache` |

The backend runs as the non-root user `app` (uid 1000) and exposes a container health check on `/health`. Compose starts it after the database passes `pg_isready`. Startup creates the catalog tables and creates the `vulnerabilities` and `mitre_enterprise` databases when they are absent.

| Database | Contents |
|---|---|
| `crq` | Inventory, actors, vectors, scenarios, controls, mappings, appetite, benchmarks, decision records |
| `vulnerabilities` | Findings from the last component scan |
| `mitre_enterprise` | ATT&CK Enterprise objects, relationships and references, plus ICS assets for the asset collection |

Pinned runtime dependencies (`app/requirements.docker.txt`): FastAPI 0.115.6, Uvicorn 0.32.1, NumPy 2.2.1, Pydantic 2.10.4, python-multipart 0.0.20, packageurl-python 0.17.1, openpyxl 3.1.5, psycopg 3.2.9. The browser loads Apache ECharts 5.6.0 and jsPDF 2.5.2 from a CDN.

## Configuration

| Variable | Service | Compose value | Purpose |
|---|---|---|---|
| `DATABASE_URL` | backend | `postgresql://crq:crq@postgres:5432/crq` | Main database, also used to create the other two |
| `VULNERABILITY_DATABASE_URL` | backend | `postgresql://crq:crq@postgres:5432/vulnerabilities` | Scan findings |
| `MITRE_DATABASE_URL` | backend | `postgresql://crq:crq@postgres:5432/mitre_enterprise` | ATT&CK dataset |
| `NVD_API_KEY` | backend | not set | Optional. Without a key, NVD requests are paced between batches |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | postgres | `crq` | Database account |

The credentials in `docker-compose.yml` are local-development values. Change them, and restrict the published ports, for any shared environment. The API allows cross-origin requests from every origin.

To run the API outside Docker, provide a PostgreSQL server, export the three database URLs, install `app/requirements.docker.txt`, and run `uvicorn crq.main:app --port 8000` from the `app/` directory.

## Repository layout

```text
.
├── docker-compose.yml
├── app/                         Backend
│   ├── Dockerfile
│   ├── requirements.docker.txt
│   └── crq/
│       ├── main.py              Application, routes, start-up
│       ├── version.py           Model version
│       ├── catalog/             Units, systems, processes, components, upload engine
│       ├── intelligence/        Actors, vectors, MITRE, vulnerability scan
│       └── risk/                Scenarios, controls, mappings, benchmarks, appetite,
│                                risk engine, Monte Carlo, portfolio, treatment,
│                                report, decisions
├── frontend/                    Static pages, scripts, styles, nginx.conf
│   ├── index.html
│   ├── pages/{inventory,intelligence,risk,settings}/
│   ├── js/{shared,inventory,intelligence,risk,settings}/
│   └── css/styles.css
├── demo/                        Demonstration catalog
└── IaC/                         Deployment definitions (k3d and AWS)
```

## How the model works

**Scenario.** A scenario is one threat actor, one attack vector and one target (a system or a business process), owned by one organisational unit. Its worksheet holds the numbers of record: a threat-event frequency (TEF) triple, a susceptibility triple, a maximum number of loss events per year, six loss-form triples, a secondary-loss probability and two Beta-PERT confidence parameters. A blank catalog quantity is stored as unknown and is never replaced with zero.

**Loss event frequency.** `LEF = min(TEF × susceptibility, cap)`, evaluated on each bound of the triples.

**Loss magnitude.** Response, replacement and productivity (primary) occur on every event. Fines, reputation and competitive advantage (secondary) occur with the secondary-loss probability.

**Simulation.** For each iteration, a loss-event rate is drawn from a Beta-PERT distribution (`alpha = 1 + λ(mode − min)/(max − min)`, `beta = 1 + λ(max − mode)/(max − min)`), the event count is Poisson, and every event draws its loss forms. The analytic mean of a triple is `(min + λ·mode + max) / (λ + 2)`. Results include mean, median, standard deviation, 5th/50th/95th/99th percentiles, VaR95/99, TVaR95/99 and the probability of a loss year. A fixed seed reproduces a run. The default is 10,000 iterations.

**Controls.** A mapped control reduces frequency (scales susceptibility), magnitude (scales all six loss forms) or both. The effective percentage is the mapping override when filled, otherwise the catalog value. Controls combine multiplicatively in control-ID order. *Eliminates Risk* sets a view to zero. Three views are computed from the same draws:

| View | Controls applied |
|---|---|
| Inherent | None |
| Current | Status Implemented |
| Target | Status Implemented or Planned |

**Suggest.** Proposals combine the actor's sector targeting, vector base values, target attributes, vulnerability evidence (no findings, CVSS below 7, CVSS 7 or higher, unknown CVSS, or exploited by EPSS ≥ 0.1 or KEV) and the benchmark table. Productivity for one process and outage duration `h` with recovery time objective `R` is `min(h,R)·cost_before + max(h−R,0)·cost_after + h·FTE·hourly_cost`. A proposal whose inputs are unknown is withheld with the missing fields named. Money proposals are rounded to three significant figures.

**Register and appetite.** Every scenario is simulated in the three views with seed `run seed + position` (scenarios in ID order, same seed for the three views). Portfolio loss adds scenario losses per iteration, assuming independence. Draft scenarios are simulated and shown but excluded from the portfolio and the appetite test. The appetite record holds a statement, an annual loss limit, a VaR95 limit, a per-scenario tolerance, an annual treatment budget, an approval threshold and amortisation years (1 to 10).

**Treatment.** Candidates are mapped controls with status Planned or Not Implemented and known costs. `annualised cost = annual cost + implementation cost / amortisation years`. `BCR = reduction / annualised cost`, `ROSI = (reduction − annualised cost) / annualised cost`. The recommendation maximises analytic loss reduction within the budget: exhaustive search for 16 or fewer candidates, greedy by reduction per annualised cost above that. A second search finds the cheapest set that satisfies the portfolio limit and the scenario tolerance.

**Board report and decisions.** A report contains narrative, appetite, portfolio exposure (inherent, current, target, recommended), scenarios, treatments, decision lines (Invest, Accept, Escalate, Data gap, Defer), assumptions, data quality and input digests. Each stored record has an ID `DR-YYYYMMDD-NNN` and a SHA-256 digest of its canonical JSON. Verify recomputes the digest. A record is approved or rejected once, with a name and a note; a second decision returns HTTP 409. Invest, Accept and Escalate lines are marked *Committee* when the approval threshold is blank or the amount reaches it, otherwise *Management*.

**Settings.** The benchmark table is stored as one document. Each save stamps a UTC version `YYYY.MM.DD.HHMMSS`. A saved scenario keeps its own worksheet; the table influences only later proposals.

## Catalogs and uploads

| Catalog | Identifier | Notes |
|---|---|---|
| Organisational Units | OU ID | Headcount and loaded hourly cost feed productivity |
| Software Systems | System ID | Owner and custodian units, criticality, data classification, replacement cost, records held |
| Business Processes | Process ID | Linked systems, recovery time objective, downtime cost before and after it, FTE |
| Software Components | Component ID | Package URL (PURL); upload starts a scan |
| Threat Actors | Actor ID | Optional ATT&CK group IDs |
| Attack Vectors | Vector ID | Required ATT&CK technique chain, optional mitigations |
| Risk Scenarios | Scenario ID | Worksheet and status (Draft, Reviewed, Approved) |
| Control Catalog | Control ID | Reduction type, two percentages, status, two costs |
| Scenario-Control Mapping | Scenario ID + Control ID | Overrides, Eliminates Risk, rationale |

- Upload formats: `.csv` or `.xlsx` (first sheet), at most 10 MiB. Column order is free.
- A file is validated completely before anything is written. A rejected file changes nothing and returns every invalid cell.
- A successful upload replaces the catalog in one transaction.
- An identifier cannot be deleted or renamed while another catalog references it, and a replacement file must keep referenced identifiers.
- ATT&CK identifiers are checked for format (`G`, `M` or `T` plus digits, with an optional sub-technique suffix) and for existence in the loaded dataset.
- Catalog screens page at 25 rows, sort, filter and export the stored catalog to CSV.

## HTTP interface

Catalog collections share one shape: `GET` returns `{ items, extracted_at }`, `POST` with a file replaces the collection, and `POST`, `PUT`, `DELETE` on `…/entry` add, update and delete one row. Validation failures return 422, a missing row returns 404, and a second decision on a record returns 409.

| Area | Paths |
|---|---|
| Health | `GET /health` |
| Inventory | `/units`, `/systems`, `/processes` (each with `/entry`), `/inventory` |
| Intelligence | `/vulnerabilities`, `/mitre/status`, `/mitre/check`, `/mitre/{collection}`, `/mitre/objects/{id}`, `/actors`, `/vectors` (each with `/entry`) |
| Scenarios | `/scenarios` (with `/entry`), `/scenarios/suggest`, `/scenarios/{id}/inputs`, `/scenarios/{id}/simulate`, `/scenarios/{id}/compare` |
| Controls | `/controls`, `/scenario-controls` (each with `/entry`) |
| Configuration | `/benchmarks` (GET, PUT), `/appetite` (GET, PUT) |
| Portfolio | `/register`, `/treatments`, `/report` (query `iterations`, default 10000, and `seed`, default 1) |
| Decisions | `POST /decisions`, `GET /decisions`, `GET /decisions/{id}`, `GET /decisions/{id}/verify`, `POST /decisions/{id}/approval` |
| Sandbox | `/mc` (iterations 1,000 to 1,000,000; confidence parameters 1 to 10) |

The web pages are served at `/`, `/organisational-units`, `/software-systems`, `/software-components`, `/business-processes`, `/mitre-attack`, `/vulnerability-database`, `/threat-actors`, `/attack-vectors`, `/risk-scenarios`, `/control-catalog`, `/scenario-control-mapping`, `/risk-register`, `/decision-log`, `/risk-simulation`, `/result` and `/settings`.

## External data sources

| Source | Used for |
|---|---|
| MITRE ATT&CK (`mitre-attack/attack-stix-data` GitHub releases) | Enterprise objects, plus ICS assets |
| OSV | Vulnerabilities for each package URL |
| NVD CVE API 2.0 | CVSS scores |
| FIRST EPSS | Exploit prediction scores |
| CISA Known Exploited Vulnerabilities | KEV flag |

## Documentation

- `User-Guide.md` is the operating manual for the screens.
- `Documentation.tex` is the project description in IMRAD form, for Overleaf.
