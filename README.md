# LoadLine technical specification

Model **2.1.0**. Shipped benchmark table **2026.10**.

LoadLine stores an organisation’s inventory, threat evidence, risk-scenario worksheets, and controls, then estimates annual loss. A saved scenario uses only the numbers on its worksheet. Suggest proposes numbers. Those proposals become the worksheet only when the form is saved. Controls scale a copy of the worksheet. They do not rewrite it.

A blank catalog quantity is stored as unknown. Formulas do not replace it with zero. The one display exception is a blank post-recovery downtime cost, which is shown as the before-recovery cost and is used that way in the productivity formula.

## 1. Runtime

Three containers.

| Service | Image | Port | Role |
|---|---|---|---|
| postgres | postgres:16 | internal 5432 | Three databases on one server |
| backend | FastAPI, NumPy | host 8000 | Catalogs, scan, simulation, reports |
| frontend | nginx | host 8080 | Static pages. Proxies the API paths below |

Environment:

| Variable | Value in Compose |
|---|---|
| `DATABASE_URL` | `postgresql://crq:crq@postgres:5432/crq` |
| `VULNERABILITY_DATABASE_URL` | `postgresql://crq:crq@postgres:5432/vulnerabilities` |
| `MITRE_DATABASE_URL` | `postgresql://crq:crq@postgres:5432/mitre_enterprise` |

Startup creates tables in `crq`, and creates the `vulnerabilities` and `mitre_enterprise` databases when they are absent. CORS allows every origin. `GET /health` returns `{ "status": "ok", "model_version": "2.1.0" }`.

The browser tab title is **LoadLine** on every page. The page heading is the screen name.

## 2. Persistence

| Database | Contents |
|---|---|
| `crq` | Inventory, actors, vectors, scenarios, controls, mappings, appetite, benchmarks, decision records |
| `vulnerabilities` | Findings from the last component scan |
| `mitre_enterprise` | Enterprise ATT&CK objects, plus ICS assets used to complete the asset collection |

Each catalog has a single meta row, `id = 1`, stamped `extracted_at` on upload and on every add, edit, or delete. Appetite and benchmarks are also a single row, `id = 1`.

A catalog upload replaces that catalog inside one transaction after every row has passed. A failed row writes nothing. Delete and identifier rename are refused while another table still stores the identifier.

| Identifier | Cannot be removed or renamed while referenced by |
|---|---|
| Organisational unit | A process, a system owner or custodian, a control owner, a scenario risk owner |
| System | A component, a process link, a scenario whose target is that system |
| Business process | A scenario whose target is that process |
| Actor, vector, scenario, control | A scenario, or a scenario-control mapping, that names it |

Replacing a file must keep every identifier that is still referenced. Missing identifiers reject the file.

## 3. Shared catalog rules

Uploads are `.csv` or `.xlsx`, at most 10 MiB. The active sheet is the first sheet. Column names may appear in any order. A missing required column rejects the file before row checks. These headers are accepted as aliases of the canonical name:

| Accepted header | Canonical name |
|---|---|
| OU ID | Organisational Unit ID |
| BP ID | Business Process ID |
| RTO (hours) | Recovery Time Objective (hours) |
| Downtime Cost per Hour before RTO | Downtime Cost per Hour before Recovery Time Objective |
| Downtime Cost per Hour post RTO | Downtime Cost per Hour post Recovery Time Objective |
| FTE Count | Full-Time Equivalent Count |
| Business Owner OU ID | Business Owner Organisational Unit ID |
| Technical Custodian OU ID | Technical Custodian Organisational Unit ID |
| Owner OU ID | Owner Organisational Unit ID |
| Risk Owner OU ID | Risk Owner Organisational Unit ID |
| Base TEF Min / Mode / Max | Base Threat Event Frequency Min / Mode / Max |
| TEF Min / Mode / Max | Threat Event Frequency Min / Mode / Max |
| TEF Basis | Threat Event Frequency Basis |
| PURL | Package URL |

A number is a finite float. A whole-number field rejects a fractional value. An empty cell is unknown when the field allows blank, and an error when it does not. Enumerations are exact strings. Duplicate identifiers in one file are rejected. A review response lists every invalid cell and saves nothing.

ATT&CK identifiers:

| Kind | Pattern | Empty list |
|---|---|---|
| Group | `G` and four digits | Allowed |
| Mitigation | `M` and four digits | Allowed |
| Technique | `T` and four digits, optional `.` and three digits | A technique chain is required |

Lists are comma-separated. Duplicates in one cell are rejected. A chain also accepts `->` and `→`, and is stored as `T1190 -> T1059 -> T1486`. Each cited identifier must exist in the loaded dataset, including revoked and deprecated objects. An unloaded dataset fails the lookup.

Client tables page 25 rows. A numeric catalog cell shows at most four fraction digits. Money on the risk screens is `¤` and a grouped integer. Edit boxes keep the raw stored number. Timestamps use the browser locale.

## 4. HTTP interface

Catalog collections follow one shape. `GET` returns `{ items, extracted_at }`. `POST` of a file replaces the collection. `POST /…/entry` adds a row. `PUT /…/entry` updates a row and carries the previous identifier. `DELETE /…/entry` deletes by query parameter. Validation failure is HTTP 422. A missing row on update or delete is HTTP 404. A second decision on one record is HTTP 409.

| Method | Path | Behaviour |
|---|---|---|
| GET | `/health` | Model version |
| GET, POST | `/units`, `/units/entry` | Organisational units. PUT and DELETE on `/units/entry` |
| GET, POST | `/systems`, `/systems/entry` | Software systems. PUT and DELETE on the entry path |
| GET, POST | `/processes`, `/processes/entry` | Business processes. PUT and DELETE on the entry path |
| GET, POST | `/inventory` | Software components. POST replaces the inventory and starts a scan |
| GET, POST | `/vulnerabilities` | Stored findings. POST scans the current inventory |
| GET | `/mitre/status` | Loaded ATT&CK version and time |
| POST | `/mitre/check` | Download the current Enterprise release |
| GET | `/mitre/{collection}` | Search one collection. Query `q` |
| GET | `/mitre/objects/{external_id}` | One object, description, and references |
| GET, POST | `/actors`, `/actors/entry` | Threat actors. PUT and DELETE on the entry path |
| GET, POST | `/vectors`, `/vectors/entry` | Attack vectors. PUT and DELETE on the entry path |
| GET, POST | `/controls`, `/controls/entry` | Control catalog. PUT and DELETE on the entry path |
| GET, POST | `/scenario-controls`, `/scenario-controls/entry` | Mappings. PUT and DELETE take scenario id and control id |
| GET, POST | `/scenarios`, `/scenarios/entry` | Worksheets. PUT and DELETE on the entry path |
| GET | `/scenarios/suggest` | Proposal for one actor, vector, and target |
| GET | `/scenarios/{id}/inputs` | Collapsed inputs for a control set |
| POST | `/scenarios/{id}/simulate` | One scenario simulation |
| GET | `/scenarios/{id}/compare` | Inherent, current, and target for one scenario |
| GET, PUT | `/benchmarks` | Settings |
| GET, PUT | `/appetite` | One appetite row |
| GET | `/register` | Three loss views, portfolio, appetite test. Query `iterations` (default 10000), `seed` (default 1) |
| GET | `/treatments` | Ranking, recommendation, decision lines. Same query |
| GET | `/report` | Board-report payload. Same query. Does not store a record |
| POST | `/decisions` | Build the report and store a record. Body includes title and prepared by |
| GET | `/decisions` | List. Omits the approval note |
| GET | `/decisions/{id}` | Full record, including the note |
| GET | `/decisions/{id}/verify` | Recompute the content digest |
| POST | `/decisions/{id}/approval` | Approve or reject once |
| POST, GET | `/mc` | Sandbox simulation. Iterations from 1,000 to 1,000,000. Lambdas from 1 to 10 |

The frontend proxies these paths to the backend. Page routes are static files: `/`, `/organisational-units`, `/software-systems`, `/software-components`, `/business-processes`, `/mitre-attack`, `/vulnerability-database`, `/threat-actors`, `/attack-vectors`, `/risk-scenarios`, `/control-catalog`, `/scenario-control-mapping`, `/risk-register`, `/decision-log`, `/risk-simulation`, `/result`, `/settings`.

## 5. Inventory

### Organisational units

Required text: OU ID, name, primary responsibilities, oversight. Headcount is a whole number ≥ 0 or blank. Loaded hourly cost is ≥ 0 or blank.

Loaded hourly cost is the labour rate in the productivity formula. Headcount is not a term in that formula. When headcount is known and greater than 0, a process full-time equivalent count must not exceed it. Unknown headcount is a data gap.

### Software systems

Required: system id, name, primary function, business-owner unit, technical-custodian unit. Both units must exist.

| Field | Values | Use |
|---|---|---|
| Criticality | Low, Medium, High | Stored. Process criticality is what the formulas read |
| Data classification | Public, Internal, Confidential | Highest classification on the affected systems wins, in that order |
| Deployment | Local, Cloud, Hybrid | Stored. Omitted from every loss formula |
| Internet facing | Yes, No, or blank | Blank is stored as Unknown |
| Replacement cost | ≥ 0 or blank | Summed in the replacement suggestion |
| Records held | Whole number ≥ 0 or blank | Summed in the fines suggestion |

### Business processes

Required text: process id, name, activity/scope, key information, one existing unit, and at least one existing system id. System ids are comma-separated, unique, and every id must exist. Criticality is Low, Medium, or High.

Recovery time objective, both downtime costs, and full-time equivalent count are ≥ 0 or blank. Full-time equivalent count is a whole number. The effective post-recovery hourly cost is the stored post-recovery cost when that cell is filled, and the before-recovery cost when it is blank. A blank before-recovery cost, recovery objective, or full-time equivalent count stays unknown.

A system target’s affected processes are every process that lists that system. A process target’s affected systems are the systems on its link rows. The process itself is the affected process.

### Productivity formula

For each affected process and each of the three outage durations:

```text
hours before recovery = min(outage hours, recovery time objective)
hours after recovery  = max(outage hours − recovery time objective, 0)
labour per hour       = full-time equivalent count × loaded hourly cost of the process unit
process loss          = hours before recovery × before-recovery downtime cost
                      + hours after recovery × effective post-recovery downtime cost
                      + outage hours × labour per hour
```

The suggestion triple is the sum of `process loss` across affected processes, then money-rounded. It is withheld when any affected process lacks the before-recovery cost, the recovery objective, the full-time equivalent count, or the unit’s loaded hourly cost, and when a system target has no linked process.

### Software components

Required: component id, an existing system id, and a Package URL that parses as a PURL. Upload replaces every component row, deletes every finding, then scans. A system with no components is a data gap. If the vector requires an exploitable vulnerability, that gap withholds the susceptibility suggestion.

## 6. Intelligence

### MITRE ATT&CK

`POST /mitre/check` reads the latest GitHub release of `mitre-attack/attack-stix-data` and requires `enterprise-attack.json` and `ics-attack.json`. A concurrent check returns HTTP 409. If that Enterprise version is already loaded, the response says so and supplements any missing ICS assets. Otherwise both bundles replace the stored dataset. The status row stores the ATT&CK version, source URL, download time, and object count.

Collections: tactics, techniques, groups, software, mitigations, campaigns, assets, detection-strategies, analytics, data-components. Search matches id or name. Deprecated objects are hidden unless the client asks for them. These identifiers document the row. They do not scale frequency, susceptibility, or loss.

### Vulnerability database

The scan queries OSV by package URL (`https://api.osv.dev/v1/querybatch`, then `/v1/vulns/{id}`), CVSS from NVD 2.0, EPSS from FIRST, and the CISA Known Exploited Vulnerabilities catalog. An empty inventory returns HTTP 422. An OSV failure returns HTTP 502 and leaves the previous findings in place. A KEV failure stores the other scores and leaves `kev_checked_at` empty, so `known_exploited` is unknown.

Each stored finding is one component, one vulnerability id, CVE aliases, CVSS score and version, EPSS, the KEV flag, and the OSV modified time. The same package on two components produces two findings. The scan does not invent a local severity score.

For the affected systems together, Suggest reads the maximum EPSS ignoring blanks, the count of KEV flags, and the maximum CVSS ignoring blanks. The evidence factor is chosen in this order:

| Condition | Factor | Shipped value |
|---|---|---|
| The vector does not require an exploitable vulnerability | unchanged | 1 |
| The vector requires one, and an affected system has no components | withheld | no factor |
| No findings on the affected systems | No findings | 0.5 |
| Highest EPSS ≥ 0.1, or any finding is known-exploited | Exploited | 1.5 |
| Findings exist and every CVSS score is blank | Unknown score | 1 |
| Highest CVSS < 7 | Below 7 | 0.8 |
| Highest CVSS ≥ 7 | 7 or higher | 1 |

The exposure payload also counts findings, scores ≥ 7, and scores ≥ 9. Those counts are not multiplied into loss. Only the factor is. Findings with no KEV feed add the data gap “Known Exploited Vulnerability status unknown”. The factor still uses the scores that were stored.

### Threat actors

Required: actor id, name. Actor type is Cybercrime, Nation-State, Hacktivist, Insider, Supply Chain, or Opportunistic. Motivation is Financial, Espionage, Disruption, Ideological, or Grievance. Capability and sector targeting are Low, Medium, or High. Group ids are optional.

Sector targeting selects the threat-event frequency multiplier: shipped Low 0.5, Medium 1, High 1.5. Motivation Espionage, or actor type Insider, puts a confidentiality scenario in scope for the competitive-loss triple. Capability and group ids are omitted from the loss formulas.

### Attack vectors

Required: vector id, name, a non-empty technique chain, terminal tactic, loss event type, both requirement flags, and three triples.

| Field | Constraint | Later use |
|---|---|---|
| Terminal tactic | Impact, Exfiltration, Collection | Stored. Omitted from the loss formulas |
| Loss event type | Availability, Confidentiality, Integrity, Fraud | Selects the Settings row for cap, replacement, response, secondary-loss probability, fines, and reputation |
| Requires exploitable vulnerability | Yes or No | Gates the evidence factor |
| Requires internet facing | Yes or No | Gates threat-event frequency and the availability secondary-loss probability |
| Base threat-event frequency | Min ≤ mode ≤ max, max > min, each ≥ 0 | Scaled by targeting and reachability |
| Base susceptibility | Each bound in [0, 1], max > 0, min ≤ mode ≤ max | Scaled by the evidence factor |
| Typical outage hours | Min ≤ mode ≤ max, each ≥ 0 | Durations in the productivity formula |
| Mitigations | Optional | Stored. They do not apply a control |

## 7. Risk scenarios

One scenario is one existing actor, one existing vector, one target, and one existing risk-owner unit. Target type is Software System or Business Process, and the target id must exist for that type. Status is Draft, Reviewed, or Approved. Description is required. Evidence and calibration notes may be blank. The risk-owner unit is stored and is omitted from the loss formulas.

Every numeric worksheet cell is required. A blank is rejected.

| Field | Constraint |
|---|---|
| Threat-event frequency | Min ≤ mode ≤ max, max > min, each ≥ 0 |
| Susceptibility | Each bound in [0, 1], max > 0, min ≤ mode ≤ max |
| Max loss events per year | > 0 and strictly greater than frequency minimum × susceptibility minimum |
| Frequency lambda, magnitude lambda | 1 to 10 inclusive |
| Six loss forms | Each triple has min ≤ mode ≤ max and each bound ≥ 0 |
| Secondary-loss probability | 0 to 1 inclusive |
| Three basis fields | External, Internal, Expert, or Mixed |
| Combined magnitude | Primary maximum + probability × secondary maximum must be strictly greater than the same expression on the minimums. Otherwise the response minimum is reported as degenerate |

Primary forms are response, replacement, and productivity. Secondary forms are fines, reputation, and competitive. `expert_only` is true when all three basis fields are Expert. It is returned on the data-quality object and is not a separate loss input.

Draft scenarios are simulated and listed. Portfolio sums, the appetite test, the recommended-portfolio simulation, and Accept lines exclude them. Reviewed and Approved are identical in the arithmetic: both are in the appetite test. Analytic treatment ranking includes drafts.

### Affected target and data gaps

A scenario is complete when its gap list is empty. Gaps, in list order:

- Each affected system: replacement cost unknown, records held unknown, internet facing Unknown, no components.
- Each affected process: before-recovery downtime cost, recovery time objective, full-time equivalent count.
- Once per owning unit of those processes: headcount, loaded hourly cost.
- A system target that no process lists.
- A process target with no primary systems.
- Findings present and `kev_checked_at` empty.

A blank post-recovery cost is not a gap.

The board-report bullet is:

```text
* {scenario id}: Data Gap identified in {id} - {name}, missing {field}.
```

A missing primary-process link names the system and says a business process that lists it is missing. The KEV gap names the vulnerability findings and Known Exploited Vulnerability status. The name is omitted when the catalog has no name for that id.

### Suggest

`GET /scenarios/suggest` reads the actor, the vector, the affected systems and processes, the findings, and the active benchmark table. It does not read controls. Each factor is `{ available, … }` or `{ available: false, missing, rationale }`. The client copies available numbers into the open form and leaves withheld cells as they are. Save writes the worksheet. A later Settings save does not rewrite stored worksheets.

**Threat-event frequency.** Withheld when the vector requires internet exposure and any affected system is Unknown. Otherwise:

```text
reachability = 1, when exposure is not required
             = 1, when any affected system is internet facing
             = Settings unexposed factor, when none is internet facing
frequency    = base frequency × sector-targeting multiplier × reachability
```

Each bound is scaled, then money-rounded. The shipped unexposed factor is 0.25.

**Susceptibility.** Withheld when the vector requires a vulnerability and any affected system has no components. Otherwise each bound is `base bound × evidence factor`, the mode and the maximum are capped at 1, and a mode above the capped maximum is set equal to that maximum. Rate rounding then caps every bound at 1.

**Annual event cap.** Stored as the benchmark number, without suggestion rounding.

| Loss type | Cap |
|---|---|
| Fraud | Settings Fraud cap. Shipped 52 |
| Confidentiality | Settings Confidentiality cap. Shipped 12 |
| Availability or Integrity, with a linked process | Settings value for that loss type and the highest process criticality. Shipped High 4, Medium 6, Low 12 |
| Availability or Integrity, with no linked process | Withheld |

**Response.** Availability, Integrity, and Fraud copy the Settings triple for that loss type. Confidentiality copies the triple for the highest data classification, and is withheld when there is no system. The copy is money-rounded.

**Replacement.** Withheld when there is no affected system or any replacement cost is unknown. Otherwise `(sum of replacement costs) × the Settings fraction triple for the loss type`, then money-rounded. Shipped fractions: Availability 0.05 / 0.20 / 0.60, Integrity 0.05 / 0.25 / 0.75, Confidentiality 0 / 0.02 / 0.10, Fraud 0 / 0.01 / 0.05.

**Productivity.** The inventory formula above, money-rounded.

**Secondary-loss probability.** One number, stored as the benchmark value.

| Case | Value |
|---|---|
| Confidentiality with a system | Settings value for the highest classification. Shipped Confidential 0.70, Internal 0.30, Public 0.05 |
| Confidentiality with no system | Withheld |
| Availability, some system internet facing, some process High | Exposed-and-high. Shipped 0.40 |
| Availability, at least one system Yes or no system Unknown | Other. Shipped 0.15 |
| Availability, any system Unknown and none Yes | Withheld |
| Integrity | Shipped 0.50 |
| Fraud | Shipped 0.30 |

**Fines.** The per-record branch runs only when the highest classification is Confidential and the loss type is not Fraud. Unknown records withhold it. Otherwise, with `records` the sum of records held and `rate` each bound of the per-record triple:

```text
fine bound = min(records × rate, fine cap)
```

The result is money-rounded. Shipped rates: Confidentiality and Integrity 0 / 5 / 25, Availability 0 / 1 / 5, Fraud 0 / 0 / 0. Shipped cap 20,000,000. Fraud never enters this branch. Every other case, including no system and a classification that is not Confidential, is the zero triple.

**Reputation.** Withheld when there is no affected process. Otherwise the Settings triple for the highest process criticality. Integrity and Fraud use half of each bound. Money-rounded. Shipped: High 100,000 / 500,000 / 3,000,000, Medium 25,000 / 100,000 / 750,000, Low 5,000 / 25,000 / 150,000.

**Competitive.** Confidentiality, and motivation Espionage or actor type Insider, copies the Settings triple. Shipped 0 / 50,000 / 500,000. Every other case is the zero triple. Money-rounded.

**Lambdas.** Copied from Settings. Shipped frequency λ = 3, magnitude λ = 4.

### Suggestion rounding

Money values, and the suggested threat-event frequency, use three significant figures. Zero stays zero. The power is `2 − floor(log10(|value|))`. After rounding, the mode is pulled inside the minimum and maximum. If rounding collapses a triple that was not already a single number, the maximum is restored from the unrounded maximum, rounded the same way. If that is still not larger than the minimum, the maximum becomes `minimum + 1% of |minimum|`, or 1 when the minimum is 0.

Susceptibility bounds are rounded to three decimal places and capped at 1. The mode is pulled inside those bounds. The annual cap, both lambdas, and the secondary-loss probability are stored without this rounding.

## 8. Controls and mappings

### Control catalog

Required text: control id, name, description. Control type is Preventive, Detective, or Corrective. Reduces is Frequency, Magnitude, or Both. Status is Implemented, Planned, or Not Implemented. Both reduction percentages are required and lie in `[0, 100)`. Implementation cost and annual cost are ≥ 0 or blank. The owner unit must exist. Framework reference may be blank. Mitigation ids are optional and are checked against MITRE.

Control type, description, framework reference, owner, and mitigation ids do not change a loss. Status, reduction type, the effective percentages, Eliminates Risk, and the two costs do.

```text
Reduces Frequency  → the magnitude percentage used later is 0
Reduces Magnitude  → the frequency percentage used later is 0
Reduces Both       → both stored percentages can apply
```

The unused percentage remains stored.

### Scenario-control mapping

One row is one existing scenario and one existing control. The pair is unique. Each override is blank or in `[0, 100)`. Eliminates Risk is Yes or No. Rationale may be blank.

The effective percentage is the override when the cell is filled, including a filled 0, and the catalog percentage when the cell is blank. The Reduces rule then zeros the side the control does not reduce. The list columns Frequency % and Magnitude % are these effective values. Eliminates Risk is the only switch that zeros a control set. A percentage cannot stand in for it, because 100 is rejected.

### Control sets

| Set | Mappings included |
|---|---|
| Inherent | None |
| Current | Status Implemented |
| Target | Status Implemented or Planned |
| Custom | The requested mapped controls. Used by the treatment search and the recommended portfolio |

For the included mappings, in control-id order:

```text
frequency factor = product of (1 − effective frequency reduction / 100)
magnitude factor = product of (1 − effective magnitude reduction / 100)
```

The frequency factor scales the susceptibility triple only. Threat-event frequency and the annual cap stay as stored. The magnitude factor scales all six loss-form triples. Secondary-loss probability stays as stored. If any included mapping has Eliminates Risk = Yes, the set is eliminated.

### Loss-event frequency and analytic annual loss

```text
frequency minimum = threat-event frequency minimum × susceptibility minimum
frequency maximum = min(threat-event frequency maximum × susceptibility maximum, annual cap)
frequency mode    = min(threat-event frequency mode × susceptibility mode, frequency maximum)

primary bound   = response + replacement + productivity, on that bound
secondary bound = fines + reputation + competitive, on that bound
magnitude bound = primary bound + secondary-loss probability × secondary bound
```

The analytic frequency mean uses the scenario’s frequency λ. The analytic magnitude mean uses the magnitude λ. Analytic annual loss is their product. An eliminated set has analytic annual loss 0, after the collapse check has passed.

Collapse requires frequency minimum < frequency maximum and magnitude minimum < magnitude maximum. Failure refuses the register row, including an eliminated row, and refuses simulation. The analytic magnitude weights secondary loss by the probability. The simulated year draws the secondary forms on each event with that probability.

## 9. Simulation

One year:

1. Draw a loss-event rate from the frequency triple with a Beta-PERT.
2. Draw the event count from Poisson at that rate.
3. For each event, draw every primary form and add them.
4. Draw `U` uniform on `[0, 1)`. If `U` is below the secondary-loss probability, draw every secondary form and add them.
5. The year’s loss is the sum of its events. A year with no events has loss 0.

Beta-PERT, when minimum and maximum differ:

```text
α = 1 + λ × (mode − minimum) / (maximum − minimum)
β = 1 + λ × (maximum − mode) / (maximum − minimum)
X = minimum + (maximum − minimum) × Beta(α, β)
```

When minimum equals maximum, every draw is that constant, and the recorded shape is α = 1, β = 1. The analytic mean is:

```text
mean = (minimum + λ × mode + maximum) / (λ + 2)
```

The run stops when the iterations together ask for more than 5,000,000 events. The same seed repeats the same draws. A missing seed draws one from `[0, 2^31)`.

| Summary | Definition |
|---|---|
| Mean | Arithmetic mean of the annual-loss samples |
| Median, 5th, 50th, 95th, 99th | Percentiles of those samples |
| Standard deviation | Population standard deviation |
| Value at Risk 95 and 99 | The 95th and 99th percentiles |
| Tail Value at Risk 95 and 99 | Mean of samples at or above that Value at Risk. If none qualify, the Value at Risk itself |
| Probability of a loss year | On one scenario, the share of years with at least one event. On a portfolio, the share of years whose summed loss is greater than 0 |

Expected annual loss of one form is the sum of that form’s event draws divided by the number of years. A secondary form’s draws are already zero when the secondary trial failed.

Charts use 40 histogram bins on annual loss. The frequency histogram is one bin per Poisson count. The magnitude summary is the per-event loss. With several forms it is labelled a compound sum. The exceedance curve has 100 thresholds from the smallest annual loss to the largest. At each threshold the probability is the share of years whose loss is strictly greater. The scatter plot keeps years that had at least one event, at most 2,000 of them, evenly spaced. Horizontal is the event count. Vertical is that year’s loss divided by the event count. A run with no events has a single zero magnitude and an empty scatter.

### Where a simulation is requested

| Caller | Iterations | Seed | Control set | Eliminated set |
|---|---|---|---|---|
| Register columns and portfolio | 10000 from the page | `1 + position` in scenario-id order. The same seed for inherent, current, and target | All three | Column of zeros after a successful collapse. No draw |
| Scenario **Simulate** | 10000, seed 1 | 1 | Current | HTTP 422. No chart |
| Recommended portfolio | Same as the register | `seed + position` | Implemented plus the selected controls | Zero samples after collapse |
| `POST /mc` and `GET /mc` | Request, default 10000, bounds 1000 to 1000000 | Request, or a drawn seed | None. One primary form named magnitude. Secondary probability 0. Form lambdas default to 4 | Not applicable |

Reduction against inherent, stored on the register and in the report:

```text
reduction % = 100 × (1 − this mean / inherent mean)
```

when the inherent mean is not zero. The inherent column’s own reduction is then 0. A zero inherent mean leaves the reduction empty.

Portfolio annual loss in one iteration is the sum of that iteration’s scenario losses. No correlation is applied. The stored note is: “Portfolio figures assume Risk Scenarios are independent: portfolio annual loss is the per-iteration sum of scenario losses; no correlation between scenarios is modelled.”

## 10. Register, appetite, and treatment

`GET /register` returns every scenario’s three simulated means, the reduction percentages, the above-tolerance flag, data quality, and the portfolio summaries for inherent, current, and target. Drafts stay in the scenario list and out of the portfolio sums.

### Appetite

One row. Statement and Updated By are required. The five money limits are ≥ 0 or blank. Amortisation years is a whole number from 1 to 10. Before any row is saved, the in-memory appetite is undefined, the money limits are unknown, and amortisation years is 3.

```text
headroom = limit − measured value
status   = Within, when the measured value ≤ the limit
         = Breached, when the measured value > the limit
         = Not defined, when the limit or the measured value is missing
```

Annual Loss Expectancy compares the current portfolio simulated mean with the portfolio annual-loss limit. Value at Risk 95 compares the current portfolio VaR95 with its limit. A non-draft scenario is above tolerance when its current simulated mean is greater than the scenario tolerance. A missing tolerance leaves that flag empty. The page shows Excluded for a draft and Not defined when the flag is empty.

The approval threshold and the treatment budget are not loss formulas.

### Annualised cost

```text
annualised cost = annual cost + implementation cost / amortisation years
```

Unknown if either cost is null. Unknown is not free. The divisor is the saved appetite value, or 3 when appetite has not been saved.

### Candidates

A candidate is Planned or Not Implemented and appears on at least one mapping. Implemented controls are already in the current loss and are not candidates.

Standalone reduction, summed over every scenario that maps the control, including drafts:

```text
analytic annual loss with current implemented controls
− analytic annual loss with those controls plus this candidate
```

```text
net benefit                  = standalone reduction − annualised cost
benefit-cost ratio           = standalone reduction / annualised cost
return on security investment = net benefit / annualised cost
```

A known zero annualised cost leaves both ratios empty and still produces a net benefit. An unknown cost leaves all three empty. The control is listed as unranked with reason `cost unknown`.

### Budget recommendation

The search maximises analytic annual-loss reduction inside the annual treatment budget. The reduction sum includes drafts. Ties prefer the cheaper set, then the set whose identifiers sort first.

| Condition | Method |
|---|---|
| Budget blank | No selection. Reason: annual treatment budget is not defined |
| No costed candidates | No selection |
| 16 or fewer costed candidates | Every subset. A subset over the budget is skipped. Key `(-reduction, cost, sorted ids)` |
| More than 16 | Greedy. Repeatedly add the control with the best extra reduction per annualised cost. Skip a control that adds no reduction or that would exceed the budget. A zero annualised cost with positive extra reduction ranks as an infinite ratio. Ties break on lower cost, then control id |

The recommended portfolio is simulated with the selected controls added to the implemented controls. Drafts are omitted from that simulation. Appetite is evaluated again on that simulated mean and VaR95.

### Reach search

This search does not replace the budget recommendation. It runs when a portfolio annual-loss limit or a scenario tolerance exists. It considers only non-draft scenarios. With 16 or fewer costed candidates it returns the cheapest set whose analytic losses sit at or under both limits, and whether that cost is inside the budget. A blank budget leaves the within-budget flag empty. With more than 16 costed candidates it does not enumerate and reports the set as not achievable.

Residual analytic annual loss of the portfolio is the sum of current analytic annual losses, including drafts, minus the recommended reduction.

## 11. Board report and decision log

`POST /decisions` requires a title and a prepared-by name. It builds the treatment result and the report at the requested iterations and seed, assigns a record id, and stores the report, an input snapshot, and the assumptions. The client asks for the title and the prepared-by name before it opens a tab. A cancelled or blank prompt stores nothing and opens no tab. The PDF is drawn in that tab from the stored report. A blocked pop-up surfaces the message “Allow pop-ups to open the PDF in a new tab.”

The record id is `DR-` plus the UTC date `YYYYMMDD` plus a three-digit count of records already created that UTC day, plus one.

The content digest is the SHA-256 hex digest of the report after its stored digest field is cleared. Canonical JSON sorts object keys, uses no extra whitespace, folds whole-number floats to integers, and folds non-finite floats to null. Verify computes that digest again. PDF reprints the stored report. Opening the log does not recalculate.

Stored status before a decision is `Proposed`. The client label is Pending. Approval requires status Approved or Rejected, a non-empty name, and a non-empty note. A record that is already Approved or Rejected returns HTTP 409. The list omits the note. The single-record read includes status, approved by, approved at, and the note. The client shows that read-only view, with Close only, for a decided record.

The report contains narrative, appetite, portfolio exposure for inherent, current, target, and recommended, scenarios, treatments, decision lines, assumptions, data quality, and input digests. Each catalog snapshot digest is the SHA-256 of its canonical rows and the row count. Assumptions stored with the pack:

1. The independence note.
2. Controls combine multiplicatively. Frequency reductions act on susceptibility. Magnitude reductions act on all loss forms.
3. Treatment selection maximises analytic annual-loss reduction. Tail metrics are simulated.
4. Benchmark constants of the active version drive suggestions only. Stored scenario values are analyst estimates.
5. Beta-PERT inputs use per-scenario lambdas. Loss events are compound Poisson. Secondary loss is conditional on the secondary-loss probability.

Narrative amounts at or above 1,000,000 are shown as millions to two decimals, amounts at or above 1,000 as thousands to one decimal, and smaller amounts as integers.

### Decision lines

These amounts are stored in the report. They are not a second loss model.

| Line | When | Amount | Approval level |
|---|---|---|---|
| `INVEST-{control id}` | Each selected control, in control-id order | Implementation cost plus annual cost. A null is 0 in this sum | Committee when the threshold is null, or the amount is not null and the amount ≥ the threshold. Otherwise Management |
| `ACCEPT-{scenario id}` | A non-draft scenario whose residual analytic loss is above tolerance, or that is already above tolerance when the plan selects nothing | That residual analytic annual loss | The same threshold rule |
| `ESCALATE-PORTFOLIO` | Recommended portfolio still Breached on annual loss or on VaR95 | The larger excess | The same threshold rule |
| `DATA-GAPS` | Any scenario gap list is non-empty | Empty | Management. Set directly, not by the threshold rule |
| `DEFER-{control id}` | Each costed candidate that was not selected | Implementation cost plus annual cost, null as 0 | Empty. A deferral is not a committee decision |

Invest rationale states the standalone reduction, the benefit-cost ratio or `N/A`, and the mapped scenario ids. Accept states that residual expected annual loss remains above tolerance. Escalate states that portfolio exposure remains above appetite. Data-gap rationale is the bullet list joined by newlines. Defer rationale is “Not selected under the current treatment budget.”

The PDF sections, in order, are Narrative, Risk appetite, Portfolio exposure, Scenarios, Treatments, Decisions requiring approval, Assumptions, Data quality, and Input digest. Data quality prints the KEV check time, or “unknown”, and one row per incomplete scenario with its gap strings. Decisions print id, type, approval level, and amount, then the rationale. A newline in the rationale remains a separate line.

## 12. Settings

`benchmark_settings` stores one JSON document, who saved it, and when. Until the first save, `active_benchmarks()` returns the shipped table and the version is `2026.10`. Each save requires a non-empty updated-by name, validates every number, stamps the version as UTC `YYYY.MM.DD.HHMMSS`, and records that person. A saved scenario keeps its worksheet. The version string is copied onto new register views, reports, and decision records. It is not an input to a formula.

| Setting | Constraint | Shipped value |
|---|---|---|
| Sector targeting Low / Medium / High | Each ≥ 0 | 0.5 / 1 / 1.5 |
| Reachability, not internet exposed | 0 to 1 | 0.25 |
| Evidence: none, CVSS below 7, CVSS ≥ 7, unknown CVSS, exploited | Each ≥ 0 | 0.5 / 0.8 / 1 / 1 / 1.5 |
| Cap, Fraud and Confidentiality | Each ≥ 0 | 52 and 12 |
| Cap, Availability and Integrity, by High / Medium / Low | Each ≥ 0 | 4 / 6 / 12 |
| Frequency λ, magnitude λ | 1 to 10 | 3 and 4 |
| Replacement fraction | Triple per loss type. Each bound in [0, 1]. Min ≤ mode ≤ max | Listed under Suggest |
| Response | Triple per loss type, each bound ≥ 0. Confidentiality has one triple per classification | Availability 25,000 / 75,000 / 250,000. Integrity 30,000 / 90,000 / 300,000. Fraud 10,000 / 40,000 / 150,000. Confidentiality Confidential 50,000 / 150,000 / 500,000, Internal 20,000 / 60,000 / 200,000, Public 5,000 / 15,000 / 50,000 |
| Secondary-loss probability | Each value in [0, 1] | Listed under Suggest |
| Fine per record | Triple per loss type, each bound ≥ 0 | Listed under Suggest |
| Fine cap | ≥ 0 | 20,000,000 |
| Reputation | Triple per criticality, each bound ≥ 0 | Listed under Suggest |
| Competitive | Triple, each bound ≥ 0 | 0 / 50,000 / 500,000 |

The Settings screen shows each group with the formula it feeds and the rule Suggest applies. Save shows the list of changed fields and writes only after confirmation.

## 13. Client behaviour that changes a result

The scenario list loads `GET /register?iterations=10000&seed=1` for the Inherent, Current, and Target columns. Suggest fills the form from `GET /scenarios/suggest` and shows Factor, Proposal, and Why. A withheld row names the missing fields. Simulate posts the saved scenario id with control set `current`, 10000 iterations, and seed 1, then stores the response and opens `/result`.

The sandbox form posts `/mc` with the typed triples and lambdas. It does not send catalogs, controls, or appetite. Export PDF on the result page draws that chart pack. An empty result states that there is nothing to export.

The register loads `/register` and `/treatments` together at 10000 iterations and seed 1. Define Appetite puts `/appetite`. Generate Board report prompts, then posts `/decisions`, then draws the PDF. The investment table sorts costed candidates by benefit-cost ratio descending, with empty ratios last, then by control id. Unranked controls are listed with their reason. A `cost unknown` reason links to the Control Catalog.

The decision log loads `GET /decisions`. PDF redraws the stored report. Verify calls the verify endpoint. Decision on Pending posts the approval. Decision on Approved or Rejected reads the record and shows the stored decision, note, name, and time.

A component upload’s scan result is the vulnerability table. Scan for Vulnerabilities posts `/vulnerabilities` again. MITRE Check for Updates posts `/mitre/check`.
