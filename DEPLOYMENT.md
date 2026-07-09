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

### 6. Install an Ingress controller

The cluster has no ingress controller by default — install ingress-nginx once per cluster:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

On OrbStack, the controller's `LoadBalancer` Service gets a routable local IP automatically — no cloud load balancer required.

### 7. Generate a self-signed certificate and load it as a Secret

```bash
./scripts/gen-selfsigned-cert.sh portfolio-advisor.local
```

This creates `certs/tls.crt` / `certs/tls.key` (CN/SAN = `portfolio-advisor.local`, 825-day validity) and stores them as the `portfolio-advisor-tls` Secret in the `portfolio-advisor` namespace, which [k8s/app-ingress.yaml](k8s/app-ingress.yaml) references for TLS termination.

### 8. Apply the Ingress

```bash
kubectl apply -f k8s/app-ingress.yaml
```

This fronts the `portfolio-advisor` Service with TLS at host `portfolio-advisor.local` and redirects plain HTTP to HTTPS.

### 9. Point the domain at the ingress

Resolve `portfolio-advisor.local` to the ingress controller's external IP via `/etc/hosts`, so your browser treats it like a real internet domain:

```bash
INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "${INGRESS_IP} portfolio-advisor.local" | sudo tee -a /etc/hosts
```

### 10. Trust the self-signed certificate (optional but recommended)

Without this, browsers and `curl` will flag the cert as untrusted. On macOS:

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/tls.crt
```

Skip this and just click through the browser warning, or pass `--cacert certs/tls.crt` to `curl`, if you'd rather not touch the system trust store.

### 11. Test the API over HTTPS at the domain

```bash
curl --cacert certs/tls.crt https://portfolio-advisor.local/health
```

Or, if you trusted the cert in step 10, open `https://portfolio-advisor.local/health` directly in your browser.

```bash
curl -X POST https://portfolio-advisor.local/analyze \
  -H "Content-Type: application/json" \
  --cacert certs/tls.crt \
  -d '{
    "portfolio_name": "Test",
    "holdings": [
      {"ticker": "AAPL", "shares": 10, "avg_cost": 150.00},
      {"ticker": "MSFT", "shares": 5,  "avg_cost": 300.00}
    ],
    "cash_usd": 1000
  }'
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

Install ingress-nginx (or your provider's ingress controller) once per cluster, then apply [k8s/app-ingress.yaml](k8s/app-ingress.yaml) — same as steps 6–9 in local development above. For a real domain, replace `portfolio-advisor.local` in `k8s/app-ingress.yaml` with your actual DNS name, point that DNS record at the ingress controller's external IP, and swap the self-signed cert for one from a real CA (e.g. cert-manager + Let's Encrypt) instead of `scripts/gen-selfsigned-cert.sh`.

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
