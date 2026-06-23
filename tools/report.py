"""
Report Generator
Formats the portfolio manager's recommendation into a clean markdown report
and prints a summary to the CLI.
"""

from datetime import datetime

ACTION_EMOJI = {
    "Strong Buy More": "🟢",
    "Add": "🟩",
    "Hold": "🟡",
    "Trim": "🟠",
    "Exit": "🔴",
}

HEALTH_EMOJI = {
    "Strong": "💪",
    "Good": "✅",
    "Fair": "⚠️",
    "Weak": "🚨",
}


def _action_badge(action: str) -> str:
    return f"{ACTION_EMOJI.get(action, '⬜')} {action}"


def generate(recommendation: dict, output_path: str = "portfolio_report.md") -> str:
    """
    Generate a markdown report and return the path.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    health = recommendation.get("overall_portfolio_health", "Unknown")
    total = recommendation.get("total_portfolio_value_usd", 0)
    holdings = recommendation.get("holdings", [])

    lines = [
        f"# Portfolio Review  ",
        f"*Generated {now}*",
        "",
        "---",
        "",
        f"## Overall: {HEALTH_EMOJI.get(health, '')} {health}",
        "",
        f"**Total value:** ${total:,.2f}",
        "",
        recommendation.get("portfolio_summary", ""),
        "",
    ]

    # Top concerns
    concerns = recommendation.get("top_concerns", [])
    if concerns:
        lines += ["### Top concerns", ""]
        for c in concerns:
            lines.append(f"- {c}")
        lines.append("")

    # Suggested actions
    actions = recommendation.get("suggested_actions", [])
    if actions:
        lines += ["### Suggested next steps", ""]
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    # Per-holding breakdown
    lines += ["---", "", "## Holdings breakdown", ""]

    for h in holdings:
        ticker = h.get("ticker", "?")
        company = h.get("company", ticker)
        action = h.get("action", "Hold")
        conviction = h.get("conviction", "")
        score = h.get("score", "?")
        rationale = h.get("rationale", "")
        risk = h.get("key_risk", "")

        lines += [
            f"### {ticker} — {company}",
            "",
            f"**Action:** {_action_badge(action)}  ",
            f"**Conviction:** {conviction}  ",
            f"**Score:** {score}/10  ",
            "",
            f"{rationale}",
            "",
            f"*Key risk: {risk}*",
            "",
            "---",
            "",
        ]

    report = "\n".join(lines)

    with open(output_path, "w") as f:
        f.write(report)

    return output_path


def print_cli_summary(recommendation: dict) -> None:
    """
    Print a compact summary to stdout.
    """
    health = recommendation.get("overall_portfolio_health", "Unknown")
    total = recommendation.get("total_portfolio_value_usd", 0)
    holdings = recommendation.get("holdings", [])

    print(f"\n{'='*60}")
    print(f"  PORTFOLIO REVIEW  |  {HEALTH_EMOJI.get(health, '')} {health}  |  ${total:,.0f}")
    print(f"{'='*60}")
    print(f"\n{recommendation.get('portfolio_summary', '')}\n")

    print(f"  {'TICKER':<8} {'ACTION':<18} {'SCORE':<7} {'CONVICTION'}")
    print(f"  {'-'*50}")
    for h in holdings:
        action = h.get("action", "Hold")
        badge = ACTION_EMOJI.get(action, "⬜")
        print(
            f"  {h.get('ticker',''):<8} "
            f"{badge} {action:<15} "
            f"{h.get('score','?')}/10   "
            f"{h.get('conviction','')}"
        )

    print(f"\n{'─'*60}")
    concerns = recommendation.get("top_concerns", [])
    if concerns:
        print("  TOP CONCERNS:")
        for c in concerns:
            print(f"  • {c}")

    suggested = recommendation.get("suggested_actions", [])
    if suggested:
        print("\n  NEXT STEPS:")
        for i, s in enumerate(suggested, 1):
            print(f"  {i}. {s}")

    print(f"{'='*60}\n")
