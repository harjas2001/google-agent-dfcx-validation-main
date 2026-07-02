"""
reporter.py — HTML report and console output for DFCX validation results.

Generates a single self-contained HTML file with inline CSS and JavaScript.
No external dependencies — the report can be opened offline, emailed, or
committed to a repo as a build artifact.
"""
import html
from datetime import datetime
from pathlib import Path

from validator.loader import AgentIndex
from validator.checks.models import Finding


# ── Console output ────────────────────────────────────────────────────────────

def print_console_summary(results: list[tuple[str, list[Finding]]]) -> None:
    """Print all findings grouped by check to stdout."""
    RED, YEL, GRN, DIM, BLD, RST = (
        "\033[91m", "\033[93m", "\033[92m", "\033[90m", "\033[1m", "\033[0m"
    )
    SEV_COLOR = {"error": RED, "warning": YEL, "pass": GRN}

    for label, findings in results:
        non_pass = [f for f in findings if f.severity != "pass"]
        if not non_pass:
            continue
        print(f"\n{BLD}── {label} ──{RST}")
        for f in non_pass:
            col = SEV_COLOR.get(f.severity, DIM)
            badge = f.severity.upper().ljust(7)
            print(f"  {col}{badge}{RST}  {f.file_path}")
            print(f"         {f.message}")
            if f.detail:
                print(f"         {DIM}{f.detail}{RST}")
    print()


# ── HTML report ───────────────────────────────────────────────────────────────

def generate_html_report(
    results: list[tuple[str, list[Finding]]],
    agent: AgentIndex,
    output_path: Path,
) -> None:
    """
    Render all findings as a self-contained HTML file and write to disk.

    Args:
        results:     List of (check_label, findings) from run_checks().
        agent:       The loaded AgentIndex (used for meta stats).
        output_path: Target file path for the HTML report.
    """
    all_findings: list[Finding] = [f for _, fs in results for f in fs]
    total_errors   = sum(1 for f in all_findings if f.severity == "error")
    total_warnings = sum(1 for f in all_findings if f.severity == "warning")
    total_passes   = sum(1 for f in all_findings if f.severity == "pass")

    timestamp = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    agent_name = agent.root.resolve().name

    html_content = _render_html(
        results=results,
        agent_name=agent_name,
        agent_path=str(agent.root.resolve()),
        timestamp=timestamp,
        flow_count=len(agent.flow_files),
        page_count=len(agent.page_files),
        total_errors=total_errors,
        total_warnings=total_warnings,
        total_passes=total_passes,
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)


def _render_html(
    results: list[tuple[str, list[Finding]]],
    agent_name: str,
    agent_path: str,
    timestamp: str,
    flow_count: int,
    page_count: int,
    total_errors: int,
    total_warnings: int,
    total_passes: int,
) -> str:

    status_class = "status-fail" if total_errors else ("status-warn" if total_warnings else "status-pass")
    status_text  = "FAILED" if total_errors else ("WARNINGS" if total_warnings else "PASSED")

    check_sections_html = _render_check_sections(results)
    summary_rows_html   = _render_summary_rows(results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>DFCX Validation — {html.escape(agent_name)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:        #0d1117;
  --surface:   #161b22;
  --surface2:  #1c2128;
  --border:    #30363d;
  --border2:   #21262d;
  --text:      #e6edf3;
  --text-dim:  #7d8590;
  --text-mid:  #b1bac4;
  --red:       #f85149;
  --red-bg:    #1e0a0a;
  --red-border:#420d0d;
  --amber:     #d29922;
  --amber-bg:  #1a1500;
  --amber-bdr: #3d2f00;
  --green:     #3fb950;
  --green-bg:  #071e0f;
  --green-bdr: #0d4220;
  --blue:      #58a6ff;
  --blue-bg:   #031d41;
  --mono:      'JetBrains Mono', monospace;
  --sans:      'DM Sans', system-ui, sans-serif;
}}
html{{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.6}}
body{{min-height:100vh}}

/* ── Layout ── */
.wrap{{max-width:1100px;margin:0 auto;padding:32px 24px 80px}}
header{{border-bottom:1px solid var(--border);padding-bottom:24px;margin-bottom:32px}}
.header-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}}
.title{{font-family:var(--mono);font-size:18px;font-weight:700;letter-spacing:-0.3px}}
.title span{{color:var(--text-dim)}}
.status-badge{{
  font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:1.5px;
  padding:4px 12px;border-radius:4px;border:1px solid;
  align-self:flex-start;margin-top:2px;
}}
.status-pass{{color:var(--green);background:var(--green-bg);border-color:var(--green-bdr)}}
.status-warn{{color:var(--amber);background:var(--amber-bg);border-color:var(--amber-bdr)}}
.status-fail{{color:var(--red);  background:var(--red-bg);  border-color:var(--red-border)}}
.meta{{margin-top:12px;font-size:12px;font-family:var(--mono);color:var(--text-dim);display:flex;gap:20px;flex-wrap:wrap}}
.meta-path{{color:var(--text-mid)}}

/* ── Stat cards ── */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:32px}}
.stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 18px}}
.stat-num{{font-family:var(--mono);font-size:28px;font-weight:700;line-height:1;margin-bottom:4px}}
.stat-label{{font-size:11px;font-weight:600;letter-spacing:0.8px;text-transform:uppercase;color:var(--text-dim)}}
.stat.s-error .stat-num{{color:var(--red)}}
.stat.s-warn  .stat-num{{color:var(--amber)}}
.stat.s-pass  .stat-num{{color:var(--green)}}
.stat.s-info  .stat-num{{color:var(--blue)}}

/* ── Summary table ── */
.summary-table{{width:100%;border-collapse:collapse;margin-bottom:36px;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}}
.summary-table th{{padding:10px 16px;text-align:left;font-size:11px;font-weight:600;letter-spacing:0.8px;text-transform:uppercase;color:var(--text-dim);background:var(--surface2);border-bottom:1px solid var(--border)}}
.summary-table td{{padding:10px 16px;border-bottom:1px solid var(--border2);font-size:13px}}
.summary-table tr:last-child td{{border-bottom:none}}
.summary-table td:nth-child(2),.summary-table td:nth-child(3),.summary-table td:nth-child(4){{font-family:var(--mono);text-align:right;width:90px}}

/* ── Filter bar ── */
.filter-bar{{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap;align-items:center}}
.filter-bar span{{font-size:11px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase;color:var(--text-dim);margin-right:4px}}
.filter-btn{{
  font-family:var(--mono);font-size:11px;font-weight:600;cursor:pointer;
  padding:5px 12px;border-radius:4px;border:1px solid var(--border);
  background:transparent;color:var(--text-mid);letter-spacing:0.3px;
  transition:all .15s;
}}
.filter-btn:hover{{border-color:var(--blue);color:var(--blue)}}
.filter-btn.active{{background:var(--blue-bg);border-color:var(--blue);color:var(--blue)}}

/* ── Check sections ── */
.section{{margin-bottom:28px;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}}
.section-header{{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 16px;background:var(--surface2);border-bottom:1px solid var(--border);
  cursor:pointer;user-select:none;
}}
.section-header:hover{{background:#1f2730}}
.section-title{{font-family:var(--mono);font-size:13px;font-weight:600}}
.section-counts{{display:flex;gap:10px;font-family:var(--mono);font-size:11px}}
.sc-e{{color:var(--red)}}
.sc-w{{color:var(--amber)}}
.sc-p{{color:var(--green)}}
.sc-dim{{color:var(--text-dim)}}
.chevron{{color:var(--text-dim);font-size:10px;transition:transform .2s;margin-left:8px}}
.section-body{{padding:0}}
.section-body.collapsed{{display:none}}

/* ── Finding rows ── */
.finding{{
  display:grid;
  grid-template-columns:72px 1fr;
  gap:0;
  border-bottom:1px solid var(--border2);
  padding:10px 16px;
  transition:background .1s;
}}
.finding:last-child{{border-bottom:none}}
.finding:hover{{background:var(--surface2)}}
.finding.hidden{{display:none}}

.badge{{
  font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:1px;
  padding:2px 7px;border-radius:3px;border:1px solid;
  align-self:flex-start;margin-top:1px;white-space:nowrap;
}}
.badge-error  {{color:var(--red);  background:var(--red-bg);  border-color:var(--red-border)}}
.badge-warning{{color:var(--amber);background:var(--amber-bg);border-color:var(--amber-bdr)}}
.badge-pass   {{color:var(--green);background:var(--green-bg);border-color:var(--green-bdr)}}

.finding-content{{min-width:0}}
.finding-file{{font-family:var(--mono);font-size:11px;color:var(--blue);margin-bottom:2px;word-break:break-all}}
.finding-msg{{font-size:13px;color:var(--text);margin-bottom:2px}}
.finding-detail{{font-family:var(--mono);font-size:11px;color:var(--text-dim);word-break:break-all}}

/* ── Empty state ── */
.all-pass{{padding:20px 16px;text-align:center;color:var(--green);font-family:var(--mono);font-size:12px}}
.section-all-pass{{color:var(--green)}}

/* ── Footer ── */
footer{{margin-top:48px;padding-top:20px;border-top:1px solid var(--border2);font-size:11px;color:var(--text-dim);font-family:var(--mono);text-align:center}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="header-top">
    <div class="title"><span>dfcx-validator /</span> {html.escape(agent_name)}</div>
    <div class="status-badge {status_class}">{status_text}</div>
  </div>
  <div class="meta">
    <span>{html.escape(timestamp)}</span>
    <span class="meta-path">{html.escape(agent_path)}</span>
  </div>
</header>

<div class="stats">
  <div class="stat s-error">
    <div class="stat-num">{total_errors}</div>
    <div class="stat-label">Errors</div>
  </div>
  <div class="stat s-warn">
    <div class="stat-num">{total_warnings}</div>
    <div class="stat-label">Warnings</div>
  </div>
  <div class="stat s-pass">
    <div class="stat-num">{total_passes}</div>
    <div class="stat-label">Passed</div>
  </div>
  <div class="stat s-info">
    <div class="stat-num">{flow_count}</div>
    <div class="stat-label">Flow files</div>
  </div>
  <div class="stat s-info">
    <div class="stat-num">{page_count}</div>
    <div class="stat-label">Page files</div>
  </div>
</div>

<table class="summary-table">
  <thead>
    <tr>
      <th>Check</th>
      <th>Errors</th>
      <th>Warnings</th>
      <th>Passed</th>
    </tr>
  </thead>
  <tbody>
    {summary_rows_html}
  </tbody>
</table>

<div class="filter-bar">
  <span>Show</span>
  <button class="filter-btn active" onclick="setFilter('all')">All</button>
  <button class="filter-btn" onclick="setFilter('error')">Errors only</button>
  <button class="filter-btn" onclick="setFilter('warning')">Warnings only</button>
  <button class="filter-btn" onclick="setFilter('pass')">Passed only</button>
</div>

{check_sections_html}

</div>

<footer>
  generated by google-agent-dfcx-validation &nbsp;·&nbsp; {html.escape(timestamp)}
</footer>

<script>
function setFilter(level) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('.finding').forEach(row => {{
    if (level === 'all' || row.dataset.sev === level) {{
      row.classList.remove('hidden');
    }} else {{
      row.classList.add('hidden');
    }}
  }});
  // Update empty-state visibility per section
  document.querySelectorAll('.section-body').forEach(body => {{
    const visible = body.querySelectorAll('.finding:not(.hidden)').length;
    let empty = body.querySelector('.section-empty');
    if (visible === 0) {{
      if (!empty) {{
        empty = document.createElement('div');
        empty.className = 'all-pass section-empty';
        empty.textContent = 'No findings match this filter.';
        body.appendChild(empty);
      }}
      empty.style.display = '';
    }} else {{
      if (empty) empty.style.display = 'none';
    }}
  }});
}}

function toggleSection(el) {{
  const body = el.nextElementSibling;
  const chevron = el.querySelector('.chevron');
  if (body.classList.contains('collapsed')) {{
    body.classList.remove('collapsed');
    chevron.textContent = '▲';
  }} else {{
    body.classList.add('collapsed');
    chevron.textContent = '▼';
  }}
}}
</script>
</body>
</html>"""


def _render_summary_rows(results: list[tuple[str, list[Finding]]]) -> str:
    rows = []
    for label, findings in results:
        e = sum(1 for f in findings if f.severity == "error")
        w = sum(1 for f in findings if f.severity == "warning")
        p = sum(1 for f in findings if f.severity == "pass")
        e_col = f'<span style="color:var(--red)">{e}</span>'   if e else f'<span style="color:var(--text-dim)">{e}</span>'
        w_col = f'<span style="color:var(--amber)">{w}</span>' if w else f'<span style="color:var(--text-dim)">{w}</span>'
        p_col = f'<span style="color:var(--green)">{p}</span>'
        rows.append(
            f'<tr><td>{html.escape(label)}</td>'
            f'<td>{e_col}</td><td>{w_col}</td><td>{p_col}</td></tr>'
        )
    return "\n    ".join(rows)


def _render_check_sections(results: list[tuple[str, list[Finding]]]) -> str:
    sections = []
    for label, findings in results:
        sections.append(_render_section(label, findings))
    return "\n".join(sections)


def _render_section(label: str, findings: list[Finding]) -> str:
    e = sum(1 for f in findings if f.severity == "error")
    w = sum(1 for f in findings if f.severity == "warning")
    p = sum(1 for f in findings if f.severity == "pass")

    counts_html = []
    if e:
        counts_html.append(f'<span class="sc-e">✗ {e} error{"s" if e != 1 else ""}</span>')
    if w:
        counts_html.append(f'<span class="sc-w">⚠ {w} warning{"s" if w != 1 else ""}</span>')
    if p:
        counts_html.append(f'<span class="sc-p">✓ {p} passed</span>')
    if not findings:
        counts_html.append('<span class="sc-dim">no findings</span>')

    counts_str = "  ".join(counts_html)

    if not findings:
        body_html = '<div class="all-pass">✓ No findings</div>'
    else:
        rows = [_render_finding(f) for f in findings]
        body_html = "\n".join(rows)

    # Auto-collapse sections with no errors or warnings
    collapsed_class = " collapsed" if (e == 0 and w == 0) else ""

    return f"""<div class="section">
  <div class="section-header" onclick="toggleSection(this)">
    <span class="section-title">{html.escape(label)}</span>
    <div style="display:flex;align-items:center;gap:12px">
      <div class="section-counts">{counts_str}</div>
      <span class="chevron">{"▼" if collapsed_class else "▲"}</span>
    </div>
  </div>
  <div class="section-body{collapsed_class}">
    {body_html}
  </div>
</div>"""


def _render_finding(f: Finding) -> str:
    badge_class = f"badge-{f.severity}"
    badge_text  = {"error": "ERROR", "warning": "WARN", "pass": "PASS"}.get(f.severity, f.severity.upper())

    file_html   = f'<div class="finding-file">{html.escape(f.file_path)}</div>'
    msg_html    = f'<div class="finding-msg">{html.escape(f.message)}</div>'
    detail_html = (
        f'<div class="finding-detail">{html.escape(f.detail)}</div>'
        if f.detail else ""
    )

    return (
        f'<div class="finding" data-sev="{f.severity}">'
        f'  <div><span class="badge {badge_class}">{badge_text}</span></div>'
        f'  <div class="finding-content">{file_html}{msg_html}{detail_html}</div>'
        f'</div>'
    )
