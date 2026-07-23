#!/usr/bin/env python3
"""
validate.py — Dialogflow CX Agent Validation Pipeline

Runs structural and configuration validation against an exported Dialogflow CX
agent folder, producing a self-contained HTML report and console output.

Usage:
    python validate.py <agent_folder>
    python validate.py <agent_folder> --output report.html
    python validate.py <agent_folder> --verbose
"""
import argparse
import sys
from pathlib import Path

from validator.loader import load_agent
from validator.checks.rich_media import check_rich_media
from validator.checks.category import check_category
from validator.checks.last_page import check_last_page
from validator.reporter import generate_html_report, print_console_summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validate an exported Dialogflow CX agent folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python validate.py ./my_agent_export\n"
            "  python validate.py ./my_agent_export --output reports/run1.html --verbose\n"
        ),
    )
    p.add_argument(
        "agent_folder",
        help="Root of the exported DFCX agent (the directory containing agent.json and flows/).",
    )
    p.add_argument(
        "--output",
        default="output/validation_report.html",
        metavar="PATH",
        help="HTML report output path (default: output/validation_report.html).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print all findings to console.",
    )
    return p.parse_args()


def _run_checks(agent) -> list[tuple[str, list]]:
    checks = [
        ("Rich Media Payloads",   check_rich_media),
        ("Queue Name (category)", check_category),
        ("Last Page Parameter",   check_last_page),
    ]
    return [(label, fn(agent)) for label, fn in checks]


def _print_summary(results: list[tuple[str, list]]) -> int:
    """Print a results table to console. Returns total error count."""
    total_errors = 0
    RED, YEL, GRN, DIM, RST = "\033[91m", "\033[93m", "\033[92m", "\033[90m", "\033[0m"
    print(f"  {'Check':<35}  {'Errors':>7}  {'Warnings':>9}  {'Passed':>7}")
    print(f"  {'─' * 35}  {'─' * 7}  {'─' * 9}  {'─' * 7}")
    for label, findings in results:
        e = sum(1 for f in findings if f.severity == "error")
        w = sum(1 for f in findings if f.severity == "warning")
        p = sum(1 for f in findings if f.severity == "pass")
        total_errors += e
        e_col = RED if e else DIM
        w_col = YEL if w else DIM
        print(
            f"  {label:<35}  "
            f"{e_col}{e:>7}{RST}  "
            f"{w_col}{w:>9}{RST}  "
            f"{GRN}{p:>7}{RST}"
        )
    print()
    return total_errors


def main() -> None:
    args = parse_args()

    agent_path = Path(args.agent_folder)
    if not agent_path.exists() or not agent_path.is_dir():
        print(f"\n\033[91m[ERROR]\033[0m Agent folder not found: {agent_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n\033[1m── Dialogflow CX Agent Validator ───────────────────────────────────\033[0m")
    print(f"  Agent  : {agent_path.resolve()}")
    print(f"  Report : {args.output}\n")

    print("Loading agent files...")
    try:
        agent = load_agent(agent_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(f"  {len(agent.flow_files)} flow file(s)  ·  {len(agent.page_files)} page file(s)\n")

    print("Running checks...\n")
    results = _run_checks(agent)
    total_errors = _print_summary(results)

    if args.verbose:
        print_console_summary(results)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Generating report → {output_path} ...")
    generate_html_report(results, agent, output_path)
    print(f"Done. Open \033[4m{output_path}\033[0m in your browser.\n")

    if total_errors:
        print(f"\033[91m✗  {total_errors} error(s) found — see report for details.\033[0m\n")
        sys.exit(1)
    else:
        print(f"\033[92m✓  All checks passed.\033[0m\n")


if __name__ == "__main__":
    main()
