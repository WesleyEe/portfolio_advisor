from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api
from llm import server as llm_server


@pytest.fixture
def client():
    with patch.object(llm_server, "start"), patch.object(llm_server, "ensure_model"):
        with TestClient(api.app) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready_reports_ollama_state(client):
    with patch.object(llm_server, "is_running", return_value=True), patch.object(
        llm_server, "has_model", return_value=True
    ):
        resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["ollama_reachable"] is True
    assert body["model_loaded"] is True


def test_health_ready_returns_503_when_ollama_unreachable(client):
    with patch.object(llm_server, "is_running", return_value=False):
        resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_metrics_endpoint_exposes_prometheus_format(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "analyze_requests_total" in resp.text


def test_analyze_rejects_empty_holdings(client):
    resp = client.post(
        "/analyze",
        json={"portfolio_name": "Test", "holdings": [], "cash_usd": 0},
    )
    assert resp.status_code == 400


@patch("api.portfolio_manager.run")
@patch("api.news_analyst_agent.run")
@patch("api.market_agent.portfolio_risk_metrics")
@patch("api.market_agent.run")
def test_analyze_happy_path(mock_market, mock_risk, mock_news, mock_pm, client):
    mock_market.return_value = {"AAPL": {"position_value": 1000}}
    mock_risk.return_value = {}
    mock_news.return_value = {}
    mock_pm.return_value = {"holdings": [], "overall_portfolio_health": "Good"}

    resp = client.post(
        "/analyze",
        json={
            "portfolio_name": "Test",
            "holdings": [{"ticker": "AAPL", "shares": 10, "avg_cost": 150.0}],
            "cash_usd": 1000,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["overall_portfolio_health"] == "Good"


@patch("api.portfolio_manager.run")
@patch("api.news_analyst_agent.run")
@patch("api.market_agent.portfolio_risk_metrics")
@patch("api.market_agent.run")
def test_analyze_propagates_llm_error(mock_market, mock_risk, mock_news, mock_pm, client):
    mock_market.return_value = {}
    mock_risk.return_value = {}
    mock_news.return_value = {}
    mock_pm.return_value = {"error": "boom"}

    resp = client.post(
        "/analyze",
        json={
            "portfolio_name": "Test",
            "holdings": [{"ticker": "AAPL", "shares": 10, "avg_cost": 150.0}],
            "cash_usd": 1000,
        },
    )
    assert resp.status_code == 500
