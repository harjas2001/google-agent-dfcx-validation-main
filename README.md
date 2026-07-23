# google-agent-dfcx-validation

Static validation pipeline for exported Dialogflow CX agent packages — catches misconfigured rich media payloads, invalid queue names, broken page parameter contracts, dead routes and colliding NLU training data before they reach production.

It also extracts **journey context**: for every `sys-head` intent, what that customer journey is configured to do — the pages it visits, what the bot says at each step, what it asks for, which live-agent queues it can escalate to, and where it ends.

---

## Background

Built to validate a multi-flow Dialogflow CX agent serving enterprise contact centre traffic across multiple brands. The agent export contained hundreds of page files spread across dozens of flows — manual spot-checking was not a viable QA process.

The validator runs against the exported agent folder and produces a self-contained HTML report plus a journey context CSV. Issues that historically made it to staging are now caught locally in seconds.

> **TODO:** Add timeline (month/year → month/year), approximate file count, and one-line impact metric before publishing.

---

## What it checks

Seven check families across the whole export — flows, pages, intents, entity types, route groups, test cases and agent settings.

### Payload and parameter contracts

| Check | Scope | Rule |
|---|---|---|
| **Rich media — title/actions** | All page files | `title` and `actions` must be present and non-empty in every carousel card |
| **Rich media — Link action fields** | All page files | All three of `type`, `text`, `url` must be populated; `type` must be `"Link"` |
| **Rich media — Postback action fields** | All page files | If any of `payload`, `text`, `type` is set, all three must be populated; `type` must be `"Postback"` |
| **Rich media — URL routing** | All page files | Every URL must have a `?link_type=` param; `https://vfau…` URLs must be `internal`, all others `external` |
| **Rich media — defaultAction** | All page files | All values in `defaultAction` must be empty strings |
| **Queue name (category)** | Flow files | `category` parameter is **required** — missing = error |
| **Queue name (category)** | Page files | `category` is optional but if present must be in the allowed list and not start with `ChatWeb` |
| **lastPage parameter** | Page files | Every page must set `lastPage`; value must match the page's filename stem exactly |

`$sys.func.IF()` expressions are parsed and each branch value validated individually. Pure `$session.params.*` references that cannot be statically resolved are flagged as warnings.

### Routing & reachability

| Check | Rule |
|---|---|
| **Head intent coverage** | Every `sys-head` intent should be routed by a head-intent route group |
| **Route group symmetry** | An intent in one head-intent group but not its sibling (postpaid vs prepaid) is flagged |
| **Dead intents** | Intents no route anywhere references |
| **Intent references** | Every route's `intent` must exist in `intents/` |
| **Target references** | Every `targetPage` / `targetFlow` must resolve; cross-flow page targets need an explicit `targetFlow` |
| **Page reachability** | Pages with no inbound route, and pages with no outbound route |

### NLU / training phrases

Ports the objective half of `VOICEBOT_INTENT_ANALYSIS_PLAYBOOK.md` to DFCX.

| Check | Rule |
|---|---|
| **Cross-intent duplicates** | The same normalised phrase training two intents |
| **Near-duplicates** | Cross-intent phrase pairs at token Jaccard ≥ 0.6, rolled up per intent pair |
| **Within-intent duplicates** | Repeated phrases inside one intent |
| **Thin intents** | Head intents under 10 training phrases |
| **Class imbalance** | Largest head intent ≥ 20× the smallest |
| **Metadata drift** | `numTrainingPhrases` vs phrases actually exported |
| **ASR noise** | Known mistranscriptions that are themselves valid words (`plane`→plan, `swim`→SIM, …) |

### Page & fulfillment hygiene

Missing `entryFulfillment`, **pages that end the conversation without saying anything**, silent transit pages, required form parameters with no initial prompt, missing no-match/no-input reprompt handlers, empty conditional cases, missing page descriptions, and unresolved placeholders (`TODO`, `{{…}}`) in customer-facing copy.

Silent-termination detection excludes pages that assign a `category` queue or emit a `liveAgentHandoff` directive — there a human speaks next, so bot silence is by design.

### Agent config integrity

Carousel cards validated against the `customPayloadTemplates` contract **declared in `agent.json`** rather than hardcoded rules; entity types referenced but undefined, defined but unused, or list-kind with no values; NLU classification thresholds outside a sane band; head intents with no test case.

---

## Pipeline

```
<agent_root>/
├── agent.json                       ← payload templates, agent settings
├── flows/<flow>/<flow>.json         ← flow file  (category required)
│   └── pages/<page>.json            ← page files (lastPage, rich media, hygiene)
├── intents/<intent>/                ← metadata + trainingPhrases/en.json
├── entityTypes/<entity>/            ← metadata + entities/en.json
├── agentTransitionRouteGroups/      ← reusable route groups
└── testCases/
              │
              ▼
   validate.py (7 check modules + journey tracer)
              │
              ├──► output/validation_report.html   findings + journeys
              ├──► output/journey_context.csv      one row per head intent
              └──► output/journey_context.json     full context pack
```

---

## Setup

```bash
git clone https://github.com/<your-username>/google-agent-dfcx-validation.git
cd google-agent-dfcx-validation

python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure queue names
cp config/valid_queue_names.example.txt config/valid_queue_names.txt
# Edit config/valid_queue_names.txt — add your valid category values, one per line
```

---

## Usage

```bash
# Run validation + journey extraction
python validate.py path/to/your/agent_export/

# Custom report path
python validate.py path/to/agent/ --output reports/sprint42.html

# Include full per-finding detail in console output
python validate.py path/to/agent/ --verbose

# Checks only, skip journey extraction
python validate.py path/to/agent/ --no-journeys

# Fail the build on the newer check families too
python validate.py path/to/agent/ --strict
```

The script exits with code `0` if no errors are found, `1` if any errors are found — suitable for CI pipeline integration.

### Severity policy

The three original checks fail the build on error. The four newer families — routing, NLU, page hygiene and agent config — report as **warnings by default**, so switching them on against an existing agent does not turn CI red on day one.

Promote a family by moving its label out of `WARN_ONLY_CHECKS` in `validator/config.py`, or run everything at full severity with `--strict`.

---

## Journey context

For every `sys-head` intent, the tracer follows the agent's own routing to answer *what is this journey configured to do?*

```
head intent
    │  matched by a route group, flow, or page route
    ▼
entry page ──► page ──► page ──► end state
                 │
                 ├─ says   : what the bot tells the customer
                 ├─ asks   : form parameters collected
                 ├─ sets   : topic, category, friendlyTitle, lastPage
                 └─ hands off: category assignment = live-agent queue
```

Three journey shapes are recognised: `page flow`, `inline answer` (the reply sits on the route itself and no page is visited — the FAQ and small-talk pattern), and `unrouted` (the NLU can match it but nothing handles it — always a defect).

Route groups attached to a flow are deliberately **not** followed. `agent-routing`, `small-talk` and `faq` are global escape hatches present on nearly every page; traversing them would make every journey span the whole agent.

### Outputs

| File | Contents |
|---|---|
| `output/journey_context.csv` | One row per head intent, 26 columns — entry points, flows, pages, topics, questions, handoff queues, end states, responses, sample phrases |
| `output/journey_context.json` | Full detail: every page, every response, every training phrase |
| `output/agent_analysis.xlsx` | 9-sheet workbook (see below) — written with `--excel` |
| Journeys tab in the HTML report | One expandable card per head intent, with a search box that matches intent, flow, page, queue and response text |

### Excel workbook

```bash
pip install openpyxl
python validate.py path/to/agent/ --excel
```

Nine sheets, colour-coded, frozen panes, auto-filtered, sorted worst-first:

| # | Sheet | Contents |
|---|---|---|
| 1 | **Overview** | Agent inventory, journey shapes, health and verdict tallies, per-check error/warning counts |
| 2 | **Journey Analysis** | One row per head intent — shape, health, purpose, what it does, flows, queues, recommendation |
| 3 | **Response vs Scope** | Purpose beside the bot's actual responses, with verdict and critique |
| 4 | **Coverage Gaps** | Unrouted intents, journeys with no live-agent path, route-group gaps and asymmetry, missing test coverage |
| 5 | **Overlap & Confusion** | Exact and near-duplicate intent collisions with example phrases |
| 6 | **ASR & Noise Phrases** | Known mistranscriptions kept as training data |
| 7 | **Data Hygiene** | Empty phrases, within-intent duplicates, metadata drift, thin head intents |
| 8 | **Phrase Counts** | Per-intent volume and health rating |
| 9 | **Validation Findings** | Every error and warning from every check |

`openpyxl` is **optional**. Without it, `--excel` prints a warning and skips the workbook — everything else still runs, so the tool stays stdlib-only in CI.

### Narrative pass

The CSV's last eight columns — `purpose`, `what_the_journey_does`, `response_verdict`, `response_critique`, `training_phrase_critique`, `coverage_gaps`, `health`, `recommendation` — are judgement, not extraction. They are filled by an LLM pass over `journey_context.json`, specified in [`JOURNEY_ANALYSIS_PLAYBOOK.md`](JOURNEY_ANALYSIS_PLAYBOOK.md).

Write the results to `output/journey_narratives.json` and re-run `validate.py`; they merge into both the CSV and the report. Until then the columns stay empty and everything else still works.

```bash
python validate.py path/to/agent/ --narratives analysis/narratives.json
```

---

## Configuration

### Queue names

Add or remove valid `category` values in `config/valid_queue_names.txt`:

```
# config/valid_queue_names.txt
AppMsg_VF_NBNCare
AppMsg_VF_PostpaidCare
AppMsg_VF_PrepaidCare
AppMsg_VF_Saves
AppMsg_VF_TechSupport
Upgrades
```

This file is gitignored. The `.example.txt` version ships with placeholder values and is committed.

### URL routing

Internal/external URL classification is controlled by `INTERNAL_URL_PREFIX` in `validator/config.py`:

```python
INTERNAL_URL_PREFIX: str = "https://vfau"  # URLs starting with this are internal
```

---

## Report

The HTML report is self-contained — no server, no external dependencies. It can be opened locally, emailed, or committed as a build artifact.

**Validation tab**

- **Summary cards** — errors, warnings, passes, and counts of flows, pages, intents and head intents
- **Per-check breakdown** — errors and warnings grouped by check family, collapsible
- **Filter bar** — show all / errors only / warnings only / passed only
- **Finding detail** — file path, message, raw value, and JSON breadcrumb for every finding

**Journeys tab**

- One card per head intent, tagged with its flows, handoff queues, page count and phrase count
- Expand for journey shape, entry points and conditions, the full page flow with what the bot says at each step, and sample training phrases
- Search box filters across intent name, flow, page, queue and response text
- Narrative analysis appears at the top of each card once the narrative pass has run

Sections with only passing results are collapsed by default.

---

## CI integration

```yaml
# .github/workflows/validate.yml
- name: Validate DFCX agent
  run: python validate.py ${{ env.AGENT_EXPORT_PATH }}
```

Exit code `1` on any error causes the workflow step to fail.

---

## Stack

`Python 3.10+` · stdlib only (`json`, `csv`, `pathlib`, `urllib.parse`, `re`, `dataclasses`, `collections`, `itertools`) · self-contained HTML report
