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

### 1. Build the image

```bash
docker build -t portfolio-advisor:latest .
```

For a registry (e.g. GHCR), tag and push before applying manifests:

```bash
docker tag portfolio-advisor:latest ghcr.io/yourorg/portfolio-advisor:v1.0.0
docker push ghcr.io/yourorg/portfolio-advisor:v1.0.0
```

Then update `image:` in `k8s/app-deployment.yaml` to match.

### 2. Apply manifests

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/ollama-statefulset.yaml
kubectl apply -f k8s/ollama-service.yaml
kubectl apply -f k8s/app-deployment.yaml
kubectl apply -f k8s/app-service.yaml
```

### 3. Wait for pods to be ready

```bash
kubectl rollout status deployment/portfolio-advisor -n portfolio-advisor
kubectl rollout status statefulset/ollama -n portfolio-advisor
```

On first start, Ollama will pull the model (~2 GB, one-time). Watch progress with:

```bash
kubectl logs -f statefulset/ollama -n portfolio-advisor
```

## Usage

The service is a `ClusterIP` by default. Access it from inside the cluster, or forward a port locally for testing:

```bash
kubectl port-forward svc/portfolio-advisor 8000:80 -n portfolio-advisor
```

### Analyze a portfolio

```bash
curl -X POST http://localhost:8000/analyze \
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
curl http://localhost:8000/health
# {"status": "ok"}
```

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://ollama.portfolio-advisor.svc.cluster.local:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model to use for inference |

Set these in `k8s/app-deployment.yaml` under `env:`. To change the model cluster-wide, update `OLLAMA_MODEL` there rather than per-request.

## Scaling

Horizontal scaling is the right lever for concurrency — Ollama serializes inference, so adding replicas increases throughput linearly:

```bash
kubectl scale deployment/portfolio-advisor --replicas=4 -n portfolio-advisor
```

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
