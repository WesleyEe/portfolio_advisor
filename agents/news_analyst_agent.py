"""
News + Analyst Agent
Searches DuckDuckGo for recent news and analyst views per ticker, then
uses the local LLM to distil results into structured JSON.
Runs concurrently across all holdings.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from ddgs import DDGS

from llm import server as llm

NEWS_SYSTEM = """You are a financial news research assistant.
Given a set of raw web search snippets about a stock, produce a concise JSON summary.

Return ONLY valid JSON, no prose, no markdown fences. Schema:
{
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "news_summary": "2-3 sentence summary of key recent developments",
  "sentiment": "bullish or bearish or neutral or mixed",
  "key_events": ["event 1", "event 2"],
  "risks": ["risk 1"],
  "catalysts": ["catalyst 1"],
  "sources_used": ["headline or source name"]
}"""

ANALYST_SYSTEM = """You are a sell-side analyst research assistant.
Given a set of raw web search snippets about analyst ratings for a stock, produce a concise JSON summary.

Return ONLY valid JSON, no prose, no markdown fences. Schema:
{
  "ticker": "AAPL",
  "consensus_rating": "Buy or Overweight or Hold or Underweight or Sell or Unknown",
  "price_target_range": "e.g. $180-$220",
  "recent_rating_changes": ["e.g. Goldman upgraded to Buy on Jan 5"],
  "bull_case": "1-2 sentence bull thesis from analysts",
  "bear_case": "1-2 sentence bear thesis from analysts",
  "notable_commentary": "Any notable analyst quote or view"
}"""


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """Return DuckDuckGo text results, retrying once on rate-limit."""
    for attempt in range(2):
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception:
            if attempt == 0:
                time.sleep(2)
    return []


def _snippets_text(results: list[dict]) -> str:
    lines = []
    for r in results:
        title = r.get("title", "")
        body = r.get("body", "")
        lines.append(f"- {title}: {body}")
    return "\n".join(lines) or "No search results found."


def get_news(ticker: str, company_name: str) -> dict:
    query = f"{company_name} {ticker} stock news earnings last 7 days"
    results = _ddg_search(query)
    snippets = _snippets_text(results)

    prompt = (
        f"Ticker: {ticker}\nCompany: {company_name}\n\n"
        f"Recent web search snippets:\n{snippets}\n\n"
        "Summarise the above into the required JSON schema."
    )
    try:
        text = llm.generate(prompt=prompt, system=NEWS_SYSTEM, max_tokens=600)
        return json.loads(text)
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_analyst_views(ticker: str, company_name: str) -> dict:
    query = f"{company_name} {ticker} analyst rating price target upgrade downgrade 2025"
    results = _ddg_search(query)
    snippets = _snippets_text(results)

    prompt = (
        f"Ticker: {ticker}\nCompany: {company_name}\n\n"
        f"Recent web search snippets:\n{snippets}\n\n"
        "Summarise the analyst views into the required JSON schema."
    )
    try:
        text = llm.generate(prompt=prompt, system=ANALYST_SYSTEM, max_tokens=600)
        return json.loads(text)
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def run(market_data: dict) -> dict:
    """
    Run news + analyst research concurrently for all tickers.
    Returns { ticker: { "news": {...}, "analyst": {...} } }
    """
    results: dict = {}
    tasks = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        for ticker, data in market_data.items():
            if "error" in data:
                continue
            company = data.get("company_name", ticker)
            tasks.append((ticker, executor.submit(get_news, ticker, company)))
            tasks.append((ticker + "_analyst", executor.submit(get_analyst_views, ticker, company)))

        for key, future in tasks:
            is_analyst = key.endswith("_analyst")
            ticker = key.replace("_analyst", "")

            if ticker not in results:
                results[ticker] = {}

            try:
                result = future.result(timeout=90)
                if is_analyst:
                    results[ticker]["analyst"] = result
                else:
                    results[ticker]["news"] = result
            except Exception as e:
                field = "analyst" if is_analyst else "news"
                results[ticker][field] = {"error": str(e)}

    return results
