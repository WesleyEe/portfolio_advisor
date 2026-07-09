# PortfolioAdvisor

A multi-agent system that researches your equity holdings and recommends portfolio adjustments using a locally hosted LLM + live market data. Deployed as a Kubernetes service — no external API keys required.

## How it works

```
POST /analyze
     │
     ▼
Market Agent ──────► Live prices, P&L, fundamentals (yfinance)
     │
News + Analyst Agent ► DuckDuckGo search per ticker → local LLM analysis
     │
Portfolio Manager ──► Synthesizes everything into a structured recommendation (local LLM)
     │
     ▼
JSON response
```

The LLM runs via [Ollama](https://ollama.com) as a StatefulSet inside the cluster. The default model is **qwen2.5:3b** (~2 GB, fast on CPU; uncomment the GPU resource limit for NVIDIA nodes).

## Deployment

Full step-by-step instructions (local OrbStack setup, ingress + self-signed HTTPS, production registry/domain swap, model pulls, scaling) live in **[DEPLOYMENT.md](DEPLOYMENT.md)** — this section is just the tl;dr.

```bash
docker build -t portfolio-advisor:latest .
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/ollama-statefulset.yaml
kubectl apply -f k8s/ollama-service.yaml
kubectl apply -f k8s/app-deployment.yaml
kubectl apply -f k8s/app-service.yaml

# First run only: Ollama does not auto-pull a model, so pull it manually
kubectl wait --for=condition=ready pod -l app=ollama -n portfolio-advisor --timeout=60s
kubectl exec -n portfolio-advisor ollama-0 -- ollama pull qwen2.5:3b

# Expose over HTTPS at a real hostname instead of port-forwarding
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml
./scripts/gen-selfsigned-cert.sh portfolio-advisor.local
kubectl apply -f k8s/app-ingress.yaml
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the `/etc/hosts` entry, trusting the self-signed cert, and the production-cluster variant of these steps.

## Usage

Access the API at `https://portfolio-advisor.local` (see step 4 above). Since the cert is self-signed, `curl` needs `--cacert certs/tls.crt` unless you've added it to your system trust store.

### Analyze a portfolio

```bash
curl -X POST https://portfolio-advisor.local/analyze \
  --cacert certs/tls.crt \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_name": "My Portfolio",
    "currency": "USD",
    "cash_usd": 5000,
    "holdings": [
      { "ticker": "AAPL", "shares": 20, "avg_cost": 165.00, "sector": "Technology" },
      { "ticker": "TSLA", "shares": 10, "avg_cost": 210.00, "sector": "Consumer Discretionary" }
    ]
  }'
```

`ticker` must match the Yahoo Finance symbol exactly (e.g. `BRK-B`, `0700.HK`).

#### Skip web research (faster, offline-friendly)

Add `"no_research": true` to the request body to skip the news/analyst step and return a price + AI-only recommendation.

### Health check

```bash
curl --cacert certs/tls.crt https://portfolio-advisor.local/health
# {"status": "ok"}
```

Or visit `https://portfolio-advisor.local/health` in your browser.

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama.portfolio-advisor.svc.cluster.local:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model to use for inference |

Set these in `k8s/app-deployment.yaml` under `env:`. To change the model cluster-wide, update `OLLAMA_MODEL` there rather than per-request — see [DEPLOYMENT.md](DEPLOYMENT.md) for the full model-swap and scaling procedures.

## Actions explained

| Action | Meaning |
|---|---|
| Strong Buy More | High-conviction opportunity; add significantly |
| Add | Positive outlook; add modestly if available cash |
| Hold | No clear edge either way; maintain position |
| Trim | Reduce position size; elevated risk or stretched valuation |
| Exit | Exit the position; fundamentals or thesis has broken down |

## Disclaimer

This tool is for informational purposes only. It is not financial advice. Always do your own research and consult a qualified advisor before making investment decisions.
