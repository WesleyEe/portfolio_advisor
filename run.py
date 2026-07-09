"""
PortfolioAdvisor — main entrypoint
Run: python run.py [--holdings data/holdings.json] [--output report.md]

Workflow:
  1. Load holdings from JSON
  2. Market Agent: fetch live prices + risk metrics
  3. News + Analyst Agent: concurrent web research per ticker
  4. Portfolio Manager: synthesize everything into a recommendation
  5. Report: print CLI summary + write markdown file
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure project root is on path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from llm import server as llm_server
from agents import market_agent, news_analyst_agent, portfolio_manager
from tools import report


def load_holdings(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def spinner(msg: str):
    """Simple progress indicator."""
    print(f"\n⟳  {msg}...", flush=True)


def main():
    parser = argparse.ArgumentParser(description="AI-powered portfolio advisor")
    parser.add_argument("--holdings", default="data/holdings.json", help="Path to holdings JSON")
    parser.add_argument("--output", default="portfolio_report.md", help="Output markdown report path")
    parser.add_argument("--no-research", action="store_true", help="Skip web research (faster, offline mode)")
    args = parser.parse_args()

    # ── 1. Load holdings ──────────────────────────────────────────────────────
    holdings_path = Path(args.holdings)
    if not holdings_path.exists():
        print(f"✗  Holdings file not found: {holdings_path}")
        sys.exit(1)

    # ── 0. Start local LLM ────────────────────────────────────────────────────
    model = llm_server.model_name()
    print(f"\n🤖  Starting local LLM ({model}) …")
    llm_server.start()
    llm_server.ensure_model(model)
    print("   ✓  Ollama ready  (override model: OLLAMA_MODEL=<name>)")

    portfolio = load_holdings(holdings_path)
    holdings = portfolio["holdings"]
    print(f"\n📂  Loaded {len(holdings)} holdings from {holdings_path}")
    for h in holdings:
        print(f"    {h['ticker']:6}  {h['shares']} shares @ ${h['avg_cost']:.2f}")

    # ── 2. Market data ────────────────────────────────────────────────────────
    spinner("Fetching live market data")
    t0 = time.time()
    market_data = market_agent.run(holdings)
    risk_metrics = market_agent.portfolio_risk_metrics(holdings)
    print(f"   ✓  Market data fetched in {time.time()-t0:.1f}s")

    for ticker, data in market_data.items():
        if "error" not in data:
            price = data.get("current_price")
            pnl = data.get("pnl_pct")
            print(f"    {ticker:6}  ${price:.2f}  ({'+' if pnl >= 0 else ''}{pnl:.1f}%)")

    # ── 3. News + analyst research ────────────────────────────────────────────
    if args.no_research:
        print("\n⚡  Skipping web research (--no-research flag)")
        research = {}
    else:
        spinner("Running news + analyst research (this takes ~30–60s)")
        t0 = time.time()
        research = news_analyst_agent.run(market_data)
        print(f"   ✓  Research complete in {time.time()-t0:.1f}s")

        for ticker, r in research.items():
            news_sentiment = r.get("news", {}).get("sentiment", "?")
            analyst_rating = r.get("analyst", {}).get("consensus_rating", "?")
            print(f"    {ticker:6}  news: {news_sentiment:8}  analyst: {analyst_rating}")

    # ── 4. Portfolio Manager synthesis ────────────────────────────────────────
    spinner("Portfolio Manager synthesizing recommendation")
    t0 = time.time()
    recommendation = portfolio_manager.run(market_data, research, risk_metrics, portfolio)
    print(f"   ✓  Analysis complete in {time.time()-t0:.1f}s")

    if "error" in recommendation:
        print(f"\n✗  Portfolio Manager error: {recommendation['error']}")
        sys.exit(1)

    # ── 5. Output ─────────────────────────────────────────────────────────────
    report.print_cli_summary(recommendation)

    output_path = report.generate(recommendation, args.output)
    print(f"📄  Full report saved to: {output_path}\n")


if __name__ == "__main__":
    main()
