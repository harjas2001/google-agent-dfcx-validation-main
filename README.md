# google-agent-dfcx-validation

Static validation pipeline for exported Dialogflow CX agent packages — catches misconfigured rich media payloads, invalid queue names, and broken page parameter contracts before they reach production.

---

## Background

Built to validate a multi-flow Dialogflow CX agent serving enterprise contact centre traffic across multiple brands. The agent export contained hundreds of page files spread across dozens of flows — manual spot-checking was not a viable QA process.

The validator runs against the exported agent folder and produces a self-contained HTML report surfacing four categories of issues: broken carousel payloads, incorrect URL link-type routing, invalid or missing queue name assignments, and lastPage parameter mismatches. Issues that historically made it to staging are now caught locally in seconds.

> **TODO:** Add timeline (month/year → month/year), approximate file count, and one-line impact metric before publishing.

---

## What it checks

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

---

## Pipeline

```
<agent_root>/
└── flows/
    └── <flow_name>/
        ├── <flow_name>.json       ← flow file  (category required)
        └── pages/
            └── <page>.json        ← page files (lastPage required, rich media checked)
                          │
                          ▼
              validate.py (3 check modules)
                          │
                          ▼
              output/validation_report.html
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
# Run validation, write report to output/validation_report.html
python validate.py path/to/your/agent_export/

# Custom report path
python validate.py path/to/agent/ --output reports/sprint42.html

# Include full per-finding detail in console output
python validate.py path/to/agent/ --verbose
```

The script exits with code `0` if no errors are found, `1` if any errors are found — suitable for CI pipeline integration.

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

- **Summary cards** — total errors, warnings, passed, file counts at a glance
- **Per-check breakdown** — errors and warnings grouped by check type, collapsible
- **Filter bar** — show all / errors only / warnings only / passed only
- **Finding detail** — file path, message, raw value, and JSON breadcrumb for every finding

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

`Python 3.10+` · stdlib only (`json`, `pathlib`, `urllib.parse`, `re`, `dataclasses`) · self-contained HTML report
