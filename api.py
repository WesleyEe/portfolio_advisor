"""
HTTP API for Portfolio Advisor.

Each user POSTs their holdings; the response is the structured recommendation.
The LLM calls are synchronous and CPU-bound on the Ollama side, so horizontal
pod scaling (multiple replicas) is the right lever for concurrency — not async.
"""

import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

import observability
from llm import server as llm_server
from agents import market_agent, news_analyst_agent, portfolio_manager

SERVICE_NAME = "portfolio-advisor-api"

observability.setup_logging(SERVICE_NAME)
observability.setup_tracing(SERVICE_NAME)
observability.setup_sentry(SERVICE_NAME)

logger = structlog.get_logger(__name__)
tracer = observability.get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm_server.start()
    llm_server.ensure_model()
    yield


app = FastAPI(title="Portfolio Advisor", version="1.0.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", observability.new_request_id())
    observability.bind_request_context(request_id)

    start = time.perf_counter()
    route = request.url.path
    try:
        response = await call_next(request)
    except Exception as exc:
        duration = time.perf_counter() - start
        observability.HTTP_REQUESTS.labels(method=request.method, route=route, status="500").inc()
        observability.HTTP_REQUEST_DURATION.labels(method=request.method, route=route).observe(duration)
        logger.error("request_failed", path=route, method=request.method, duration_s=round(duration, 3), error=str(exc))
        observability.capture_exception(exc, path=route, method=request.method)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})
    finally:
        structlog.contextvars.clear_contextvars()

    duration = time.perf_counter() - start
    observability.HTTP_REQUESTS.labels(method=request.method, route=route, status=str(response.status_code)).inc()
    observability.HTTP_REQUEST_DURATION.labels(method=request.method, route=route).observe(duration)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_completed",
        path=route,
        method=request.method,
        status=response.status_code,
        duration_s=round(duration, 3),
    )
    return response


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
    """Liveness: is the process up? No downstream checks — a slow Ollama
    should not get this pod killed and restarted into the same slow Ollama."""
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(response: Response):
    """Readiness: can this pod actually serve /analyze right now? Checked
    separately from liveness so k8s stops routing traffic here without
    restarting the pod while Ollama is still warming up."""
    ollama_ok = llm_server.is_running()
    model = llm_server.model_name()
    model_ok = llm_server.has_model(model) if ollama_ok else False

    ready = ollama_ok and model_ok
    observability.OLLAMA_READY.set(1 if ready else 0)
    if not ready:
        response.status_code = 503
        logger.warning("readiness_check_failed", ollama_ok=ollama_ok, model_ok=model_ok, model=model)

    return {
        "status": "ready" if ready else "not_ready",
        "ollama_reachable": ollama_ok,
        "model_loaded": model_ok,
        "model": model,
    }


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    portfolio = req.model_dump()
    holdings = portfolio["holdings"]

    if not holdings:
        raise HTTPException(status_code=400, detail="holdings list is empty")

    log = logger.bind(portfolio_name=req.portfolio_name, num_holdings=len(holdings))

    with tracer.start_as_current_span("analyze.market_data"):
        log.info("market_data_started")
        market_data = market_agent.run(holdings)
        risk_metrics = market_agent.portfolio_risk_metrics(holdings)

    with tracer.start_as_current_span("analyze.research"):
        if req.no_research:
            research = {}
        else:
            log.info("research_started")
            research = news_analyst_agent.run(market_data)

    with tracer.start_as_current_span("analyze.synthesize"):
        recommendation = portfolio_manager.run(market_data, research, risk_metrics, portfolio)

    if "error" in recommendation:
        observability.ANALYZE_REQUESTS.labels(outcome="error").inc()
        log.error("analyze_failed", error=recommendation["error"])
        raise HTTPException(status_code=500, detail=recommendation["error"])

    observability.ANALYZE_REQUESTS.labels(outcome="success").inc()
    log.info("analyze_completed", overall_health=recommendation.get("overall_portfolio_health"))
    return recommendation
