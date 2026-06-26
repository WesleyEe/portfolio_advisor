"""
HTTP API for Portfolio Advisor.

Each user POSTs their holdings; the response is the structured recommendation.
The LLM calls are synchronous and CPU-bound on the Ollama side, so horizontal
pod scaling (multiple replicas) is the right lever for concurrency — not async.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llm import server as llm_server
from agents import market_agent, news_analyst_agent, portfolio_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm_server.start()
    llm_server.ensure_model()
    yield


app = FastAPI(title="Portfolio Advisor", version="1.0.0", lifespan=lifespan)


class Holding(BaseModel):
    ticker: str
    shares: float
    avg_cost: float
    sector: str = ""


class AnalyzeRequest(BaseModel):
    portfolio_name: str = "My Portfolio"
    currency: str = "USD"
    holdings: list[Holding]
    cash_usd: float = 0.0
    no_research: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    portfolio = req.model_dump()
    holdings = portfolio["holdings"]

    if not holdings:
        raise HTTPException(status_code=400, detail="holdings list is empty")

    market_data = market_agent.run(holdings)
    risk_metrics = market_agent.portfolio_risk_metrics(holdings)

    research = {} if req.no_research else news_analyst_agent.run(market_data)

    recommendation = portfolio_manager.run(market_data, research, risk_metrics, portfolio)

    if "error" in recommendation:
        raise HTTPException(status_code=500, detail=recommendation["error"])

    return recommendation
