"""
News + Analyst Agent
Uses Gemini with Google Search grounding to gather recent news and analyst opinions per ticker.
Runs concurrently across all holdings.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

NEWS_SYSTEM = """You are a financial news research assistant.
Your job: search the web for the most recent and relevant news about a given stock ticker,
then return a concise JSON summary.

Return ONLY valid JSON, no prose, no markdown fences. Schema:
{
  "ticker": "AAPL",
  "company": "Apple Inc.",
  "news_summary": "2-3 sentence summary of key recent developments",
  "sentiment": "bullish" | "bearish" | "neutral" | "mixed",
  "key_events": ["event 1", "event 2"],
  "risks": ["risk 1"],
  "catalysts": ["catalyst 1"],
  "sources_used": ["headline or source name"]
}"""

ANALYST_SYSTEM = """You are a sell-side analyst research assistant.
Your job: search the web for the latest analyst ratings, price targets, and commentary for a stock.

Return ONLY valid JSON, no prose, no markdown fences. Schema:
{
  "ticker": "AAPL",
  "consensus_rating": "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell" | "Unknown",
  "price_target_range": "e.g. $180-$220",
  "recent_rating_changes": ["e.g. Goldman upgraded to Buy on Jan 5"],
  "bull_case": "1-2 sentence bull thesis from analysts",
  "bear_case": "1-2 sentence bear thesis from analysts",
  "notable_commentary": "Any notable analyst quote or view"
}"""


def _search_with_gemini(ticker: str, system_prompt: str, user_query: str) -> dict:
    """Run a single Gemini call with Google Search grounding enabled."""
    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1000,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
            contents=user_query,
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        return json.loads(text)
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_news(ticker: str, company_name: str) -> dict:
    query = (
        f"Search for the latest news about {company_name} ({ticker}) stock "
        f"from the past 7 days. Include earnings, product launches, management changes, "
        f"regulatory news, and any major price movements."
    )
    return _search_with_gemini(ticker, NEWS_SYSTEM, query)


def get_analyst_views(ticker: str, company_name: str) -> dict:
    query = (
        f"Search for the most recent analyst ratings, price targets, and investment commentary "
        f"for {company_name} ({ticker}). Look for upgrades, downgrades, and target price changes "
        f"in the last 30 days."
    )
    return _search_with_gemini(ticker, ANALYST_SYSTEM, query)


def run(market_data: dict) -> dict:
    """
    Run news + analyst research concurrently for all tickers.
    Returns { ticker: { "news": {...}, "analyst": {...} } }
    """
    results = {}
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
                result = future.result(timeout=60)
                if is_analyst:
                    results[ticker]["analyst"] = result
                else:
                    results[ticker]["news"] = result
            except Exception as e:
                field = "analyst" if is_analyst else "news"
                results[ticker][field] = {"error": str(e)}

    return results
