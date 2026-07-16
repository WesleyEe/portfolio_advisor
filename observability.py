"""
Central telemetry setup: structured logging, distributed tracing, metrics,
and error tracking. Imported once at process start by api.py and run.py.

Design:
  - Logging: structlog, JSON in prod-like environments, key=value in a TTY.
    Every log line carries request_id + trace_id so a single request can be
    grepped/correlated across logs, traces, and (via exemplars) metrics.
  - Tracing: OpenTelemetry, exported via OTLP/gRPC to the Tempo collector
    deployed in k8s/tempo.yaml. If the collector is unreachable (e.g. running
    run.py locally with nothing deployed), export failures are swallowed by
    the OTel SDK's own retry/backoff — spans are still created and usable
    in-process, they just don't leave the box.
  - Metrics: prometheus_client, scraped by k8s/prometheus.yaml via the
    /metrics endpoint in api.py.
  - Errors: sentry-sdk, no-op until SENTRY_DSN is set.
"""

import logging
import os
import sys
import uuid
from contextvars import ContextVar

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# ── Metrics ──────────────────────────────────────────────────────────────
# Registered once at import time; every module imports these instances
# rather than creating their own to avoid duplicate-registration errors.

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by route, method, and status code",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)
LLM_CALLS = Counter(
    "llm_calls_total",
    "LLM generate() calls by model and outcome",
    ["model", "outcome"],
)
LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "LLM generate() latency",
    ["model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Tokens consumed by LLM calls",
    ["model", "kind"],  # kind: prompt | completion
)
AGENT_ERRORS = Counter(
    "agent_errors_total",
    "Errors raised inside an agent stage",
    ["agent", "stage"],
)
ANALYZE_REQUESTS = Counter(
    "analyze_requests_total",
    "Completed /analyze requests by outcome",
    ["outcome"],  # success | error
)
OLLAMA_READY = Gauge(
    "ollama_ready",
    "Whether this pod's last readiness check found Ollama reachable with the model loaded (1) or not (0)",
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request_context(request_id: str) -> None:
    request_id_var.set(request_id)
    span = trace.get_current_span()
    span_ctx = span.get_span_context()
    trace_id = f"{span_ctx.trace_id:032x}" if span_ctx.is_valid else "-"
    structlog.contextvars.bind_contextvars(request_id=request_id, trace_id=trace_id)


def _add_request_context(logger, method_name, event_dict):
    event_dict.setdefault("request_id", request_id_var.get())
    span = trace.get_current_span()
    span_ctx = span.get_span_context()
    if span_ctx.is_valid:
        event_dict.setdefault("trace_id", f"{span_ctx.trace_id:032x}")
        event_dict.setdefault("span_id", f"{span_ctx.span_id:016x}")
    return event_dict


def setup_logging(service_name: str) -> None:
    """Configure structlog + stdlib logging. JSON output unless stdout is a TTY."""
    json_output = not sys.stdout.isatty() or os.environ.get("LOG_FORMAT") == "json"
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_request_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # The OTLP exporter logs a warning/error on every failed batch when the
    # collector is unreachable (e.g. Tempo not deployed locally) and retries
    # on a fixed interval in a background thread — left at default level this
    # spams the app's own log stream every few seconds. Missing traces are
    # already visible as gaps in Tempo/Grafana; no need to also alarm on it here.
    logging.getLogger("opentelemetry.exporter.otlp.proto.grpc.exporter").setLevel(logging.CRITICAL)

    structlog.get_logger(__name__).info("logging_configured", service=service_name, level=level_name)


def setup_tracing(service_name: str) -> None:
    """Configure the global OTel TracerProvider with an OTLP/gRPC exporter."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    structlog.get_logger(__name__).info("tracing_configured", service=service_name, endpoint=endpoint)


def setup_sentry(service_name: str) -> None:
    """No-op unless SENTRY_DSN is set — safe to call unconditionally."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "dev"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        release=os.environ.get("APP_VERSION", "unknown"),
    )
    sentry_sdk.set_tag("service", service_name)
    structlog.get_logger(__name__).info("sentry_configured", service=service_name)


def capture_exception(exc: Exception, **context) -> None:
    """Report to Sentry if configured; always safe to call, no-ops otherwise."""
    if not os.environ.get("SENTRY_DSN"):
        return
    import sentry_sdk

    with sentry_sdk.push_scope() as scope:
        for key, value in context.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_exception(exc)


def get_tracer(name: str):
    return trace.get_tracer(name)
