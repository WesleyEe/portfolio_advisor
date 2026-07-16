"""
Market Agent
Fetches live price, returns, and basic fundamentals for each holding.
"""

import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import structlog

import observability

logger = structlog.get_logger(__name__)
tracer = observability.get_tracer(__name__)


def _fetch_ticker(ticker: str, holding: dict) -> dict:
    with tracer.start_as_current_span("market_agent.fetch_ticker") as span:
        span.set_attribute("ticker", ticker)
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # 30-day history for return calculation
            end = datetime.today()
            start = end - timedelta(days=35)
            hist = stock.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if current_price is None and not hist.empty:
                current_price = round(float(hist["Close"].iloc[-1]), 2)

            # 30-day price return
            if len(hist) >= 20:
                price_30d_ago = float(hist["Close"].iloc[-20])
                ret_30d = round(((current_price - price_30d_ago) / price_30d_ago) * 100, 2)
            else:
                ret_30d = None

            # P&L on this position
            avg_cost = holding["avg_cost"]
            shares = holding["shares"]
            unrealized_pnl = round((current_price - avg_cost) * shares, 2) if current_price else None
            pnl_pct = round(((current_price - avg_cost) / avg_cost) * 100, 2) if current_price else None

            return {
                "ticker": ticker,
                "current_price": current_price,
                "avg_cost": avg_cost,
                "shares": shares,
                "position_value": round(current_price * shares, 2) if current_price else None,
                "unrealized_pnl": unrealized_pnl,
                "pnl_pct": pnl_pct,
                "return_30d_pct": ret_30d,
                "sector": holding.get("sector"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "analyst_target_price": info.get("targetMeanPrice"),
                "dividend_yield": info.get("dividendYield"),
                "company_name": info.get("longName", ticker),
            }
        except Exception as e:
            observability.AGENT_ERRORS.labels(agent="market", stage="fetch_ticker").inc()
            logger.error("market_agent_fetch_failed", ticker=ticker, error=str(e))
            observability.capture_exception(e, ticker=ticker)
            span.record_exception(e)
            return {"ticker": ticker, "error": str(e)}


def run(holdings: list[dict]) -> dict:
    """
    Returns a dict keyed by ticker with price data and basic fundamentals.
    """
    results = {}
    for holding in holdings:
        ticker = holding["ticker"]
        results[ticker] = _fetch_ticker(ticker, holding)
    return results


def portfolio_risk_metrics(holdings: list[dict]) -> dict:
    """
    Compute portfolio-level concentration and volatility metrics.
    """
    tickers = [h["ticker"] for h in holdings]

    with tracer.start_as_current_span("market_agent.portfolio_risk_metrics") as span:
        try:
            # 90-day close prices for all tickers
            end = datetime.today()
            start = end - timedelta(days=95)
            raw = yf.download(
                tickers,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True
            )["Close"]

            if isinstance(raw, pd.Series):
                raw = raw.to_frame(name=tickers[0])

            returns = raw.pct_change().dropna()
            vol = returns.std() * (252 ** 0.5) * 100  # annualised %

            corr_matrix = returns.corr().round(2).to_dict()

            return {
                "annualised_volatility_pct": {t: round(float(v), 1) for t, v in vol.items()},
                "correlation_matrix": corr_matrix,
            }
        except Exception as e:
            observability.AGENT_ERRORS.labels(agent="market", stage="risk_metrics").inc()
            logger.error("market_agent_risk_metrics_failed", tickers=tickers, error=str(e))
            observability.capture_exception(e, tickers=tickers)
            span.record_exception(e)
            return {"error": str(e)}
