"""
Portfolio Manager (Orchestrator)
Synthesizes market data, news, analyst views, and risk metrics into a
structured investment recommendation for each holding.
"""

import json
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

SYSTEM_PROMPT = """You are an experienced portfolio manager conducting a thorough review of a retail investor's equity portfolio.

You will receive:
1. Current holdings with prices, P&L, and fundamentals
2. Recent news summaries per stock
3. Analyst ratings and views per stock
4. Portfolio-level risk metrics (volatility, correlation)

Your task: produce a clear, actionable portfolio review.

For EACH holding, assign:
- action: one of "Strong Buy More" | "Add" | "Hold" | "Trim" | "Exit"
- conviction: "High" | "Medium" | "Low"
- score: integer 1–10 (10 = very bullish)
- rationale: 2–3 sentences explaining the call
- key_risk: the single most important risk to monitor

Then produce:
- overall_portfolio_health: "Strong" | "Good" | "Fair" | "Weak"
- portfolio_summary: 3–4 sentence overall assessment
- top_concerns: list of up to 3 portfolio-level issues
- suggested_actions: up to 3 concrete next steps

Return ONLY valid JSON matching this schema exactly — no prose, no markdown.

{
  "holdings": [
    {
      "ticker": "AAPL",
      "company": "Apple Inc.",
      "action": "Hold",
      "conviction": "Medium",
      "score": 6,
      "rationale": "...",
      "key_risk": "..."
    }
  ],
  "overall_portfolio_health": "Good",
  "portfolio_summary": "...",
  "top_concerns": ["...", "..."],
  "suggested_actions": ["...", "..."]
}"""


def run(market_data: dict, research: dict, risk_metrics: dict, portfolio_meta: dict) -> dict:
    """
    Orchestrate the final analysis. Returns structured recommendation dict.
    """

    context = {
        "portfolio_name": portfolio_meta.get("portfolio_name", "Portfolio"),
        "cash_usd": portfolio_meta.get("cash_usd", 0),
        "holdings_data": [],
        "risk_metrics": risk_metrics,
    }

    total_value = portfolio_meta.get("cash_usd", 0)
    for ticker, mkt in market_data.items():
        if "error" in mkt:
            continue
        total_value += mkt.get("position_value", 0) or 0

        holding_ctx = {
            "ticker": ticker,
            "company": mkt.get("company_name", ticker),
            "sector": mkt.get("sector"),
            "current_price": mkt.get("current_price"),
            "position_value": mkt.get("position_value"),
            "weight_pct": round((mkt.get("position_value", 0) or 0) / total_value * 100, 1) if total_value else None,
            "unrealized_pnl": mkt.get("unrealized_pnl"),
            "pnl_pct": mkt.get("pnl_pct"),
            "return_30d_pct": mkt.get("return_30d_pct"),
            "pe_ratio": mkt.get("pe_ratio"),
            "analyst_target_price": mkt.get("analyst_target_price"),
            "52w_high": mkt.get("fifty_two_week_high"),
            "52w_low": mkt.get("fifty_two_week_low"),
        }

        ticker_research = research.get(ticker, {})
        news = ticker_research.get("news", {})
        analyst = ticker_research.get("analyst", {})

        holding_ctx["news"] = {
            "summary": news.get("news_summary"),
            "sentiment": news.get("sentiment"),
            "key_events": news.get("key_events", []),
            "risks": news.get("risks", []),
            "catalysts": news.get("catalysts", []),
        }
        holding_ctx["analyst_views"] = {
            "consensus": analyst.get("consensus_rating"),
            "price_target_range": analyst.get("price_target_range"),
            "recent_changes": analyst.get("recent_rating_changes", []),
            "bull_case": analyst.get("bull_case"),
            "bear_case": analyst.get("bear_case"),
        }

        context["holdings_data"].append(holding_ctx)

    context["total_portfolio_value_usd"] = round(total_value, 2)

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=4000,
            ),
            contents="Please analyze this portfolio and return your structured recommendation:\n\n"
                     + json.dumps(context, indent=2),
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        recommendation = json.loads(text)
        recommendation["total_portfolio_value_usd"] = context["total_portfolio_value_usd"]
        return recommendation

    except Exception as e:
        return {"error": str(e), "raw_context": context}
