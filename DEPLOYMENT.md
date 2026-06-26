# Deployment Guide

## Local development (OrbStack + Kubernetes)

### 1. Install OrbStack

```bash
brew install orbstack
```

Open OrbStack, go to **Settings → Kubernetes → Enable Kubernetes**. That's it — no VM, no extra config. OrbStack provides a `docker` CLI and a local K8s cluster sharing the same runtime, so images you build with `docker build` are immediately available to K8s without a registry push.

### 2. Set kubectl context

```bash
kubectl config use-context orbstack
kubectl get nodes   # should show a single ready node
```

### 3. Build the app image

```bash
cd /path/to/portfolio_advisor
docker build -t portfolio-advisor:latest .
```

### 4. Deploy to local K8s

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/ollama-statefulset.yaml
kubectl apply -f k8s/ollama-service.yaml
kubectl apply -f k8s/app-deployment.yaml
kubectl apply -f k8s/app-service.yaml
```

### 5. Pull the model (first time only)

Wait for the Ollama pod to be ready, then pull the model into its PVC:

```bash
kubectl wait --for=condition=ready pod -l app=ollama -n portfolio-advisor --timeout=60s
kubectl exec -n portfolio-advisor ollama-0 -- ollama pull qwen2.5:3b
```

The model is stored on the PVC, so subsequent pod restarts skip this step.

### 6. Test the API

OrbStack automatically assigns a local DNS name to Services. Forward the port to test:

```bash
kubectl port-forward -n portfolio-advisor svc/portfolio-advisor 8080:80
```

Then in another terminal:

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "portfolio_name": "Test",
    "holdings": [
      {"ticker": "AAPL", "shares": 10, "avg_cost": 150.00},
      {"ticker": "MSFT", "shares": 5,  "avg_cost": 300.00}
    ],
    "cash_usd": 1000
  }'
```

Health check:
```bash
curl http://localhost:8080/health
```

---

## Production cluster

### 1. Push image to your registry

```bash
docker build -t ghcr.io/yourorg/portfolio-advisor:v1.0.0 .
docker push ghcr.io/yourorg/portfolio-advisor:v1.0.0
```

### 2. Update the image reference

In [k8s/app-deployment.yaml](k8s/app-deployment.yaml), change:

```yaml
image: portfolio-advisor:latest
imagePullPolicy: IfNotPresent
```

to:

```yaml
image: ghcr.io/yourorg/portfolio-advisor:v1.0.0
imagePullPolicy: Always
```

### 3. Deploy

```bash
kubectl config use-context <your-prod-context>
kubectl apply -f k8s/
```

### 4. Pull model on first deploy (same as local)

```bash
kubectl exec -n portfolio-advisor ollama-0 -- ollama pull qwen2.5:3b
```

### 5. Expose externally

Add an `Ingress` resource in front of the `portfolio-advisor` Service, or temporarily change the Service type to `LoadBalancer` in [k8s/app-service.yaml](k8s/app-service.yaml).

---

## Changing the model

Set `OLLAMA_MODEL` in [k8s/app-deployment.yaml](k8s/app-deployment.yaml) and pull the new model in the Ollama pod:

```bash
kubectl exec -n portfolio-advisor ollama-0 -- ollama pull qwen2.5:7b
```

## Scaling

Scale app replicas (Ollama is the shared bottleneck — keep it at 1 unless you have multiple GPU nodes):

```bash
kubectl scale deployment portfolio-advisor -n portfolio-advisor --replicas=4
```
