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
