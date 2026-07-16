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

## Observability stack

Deploys the LGTM stack — **L**oki (logs), **G**rafana (UI), **T**empo (traces), **M**etrics via Prometheus — plus Alertmanager, alongside the app.

**Only Grafana is exposed outside the cluster.** Prometheus, Tempo, Loki, and Alertmanager have no authentication of their own, so they stay `ClusterIP`-only and are wired into Grafana as datasources — Grafana is the one thing that gets an Ingress and a login. This is the same shape a real production cluster uses: one authenticated pane of glass, not four unauthenticated internal tools sitting on the network.

```bash
kubectl apply -f k8s/tempo.yaml
kubectl apply -f k8s/loki.yaml
kubectl apply -f k8s/otel-collector.yaml
kubectl apply -f k8s/prometheus-rbac.yaml
kubectl apply -f k8s/prometheus-configmap.yaml
kubectl apply -f k8s/prometheus.yaml
kubectl apply -f k8s/alertmanager-configmap.yaml
kubectl apply -f k8s/alertmanager.yaml
```

The app pods pick up `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at the Tempo service automatically (see [k8s/app-deployment.yaml](k8s/app-deployment.yaml)) and are annotated for Prometheus pod discovery — no target lists to maintain. Log shipping runs through the **OpenTelemetry Collector** ([k8s/otel-collector.yaml](k8s/otel-collector.yaml)), not Promtail (deprecated upstream in favor of OTel-native pipelines / Grafana Alloy): a DaemonSet tails every pod's container logs off the node filesystem via the `filelog` receiver, enriches them with pod metadata via `k8sattributesprocessor`, and pushes to Loki via the `loki` exporter. No changes needed in the app itself, since it already logs structured JSON to stdout — the collector does the same job Promtail did, just through OTel Collector components instead of a Loki-specific agent.

### Deploy Grafana

```bash
# Admin login — generate a real password, don't ship a default one
kubectl create secret generic grafana-admin \
  -n portfolio-advisor \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$(openssl rand -base64 24)"

kubectl apply -f k8s/grafana-datasources-configmap.yaml
kubectl apply -f k8s/grafana-dashboards-configmap.yaml
kubectl apply -f k8s/grafana.yaml

# Same self-signed-cert flow as the app itself, different host/secret
./scripts/gen-selfsigned-cert.sh grafana.portfolio-advisor.local portfolio-advisor grafana-tls
kubectl apply -f k8s/grafana-ingress.yaml

INGRESS_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "${INGRESS_IP} grafana.portfolio-advisor.local" | sudo tee -a /etc/hosts
```

Retrieve the generated admin password if you didn't capture it above:

```bash
kubectl get secret grafana-admin -n portfolio-advisor -o jsonpath='{.data.admin-password}' | base64 -d
```

Open `https://grafana.portfolio-advisor.local` (trust `certs/grafana-tls.crt` the same way as the app's cert — see step 10 in local dev, above). The **Portfolio Advisor** dashboard is auto-provisioned from [k8s/grafana-dashboards-configmap.yaml](k8s/grafana-dashboards-configmap.yaml) with panels for `/analyze` success/error rate, p50/p95 latency, LLM call and token throughput, agent error rate, Ollama readiness, and a live error/warning log stream. Prometheus, Tempo, Loki, and Alertmanager are pre-wired as datasources — use Grafana's Explore view against any of them, or click through directly:

- **Trace → logs**: open a trace in the Tempo datasource, click a span, and "Logs for this span" jumps to the matching Loki lines (correlated by trace ID within the `portfolio-advisor` namespace, since the OTel `service.name` and the Loki `app` label don't share a naming scheme — see the comment in [k8s/grafana-datasources-configmap.yaml](k8s/grafana-datasources-configmap.yaml)).
- **Logs → trace**: any log line containing a `trace_id` field renders as a clickable link straight to that trace in Tempo (via Loki's `derivedFields`).

**Enabling real SSO**: Grafana ships with just the admin/password login until you wire up an identity provider. To turn on SSO, set `GF_AUTH_GENERIC_OAUTH_ENABLED=true` in [k8s/grafana.yaml](k8s/grafana.yaml), replace the `REPLACE-ME` auth/token/API URLs and allowed domain with your IdP's (Google, Okta, GitHub, etc. all support generic OAuth2/OIDC), then create the client credentials Secret:

```bash
kubectl create secret generic grafana-oauth \
  -n portfolio-advisor \
  --from-literal=client-id='...' \
  --from-literal=client-secret='...'
kubectl rollout restart deployment/grafana -n portfolio-advisor
```

Once SSO is confirmed working, set `GF_AUTH_DISABLE_LOGIN_FORM=true` to remove the password-login fallback entirely.

### Debugging directly against a backend (fallback)

Grafana covers day-to-day use, but for ad hoc debugging (e.g. checking Prometheus's own `/targets` page, or Alertmanager's raw config) `kubectl port-forward` still works — it's a deliberate choice to keep these ClusterIP-only, not a limitation:

```bash
kubectl port-forward -n portfolio-advisor svc/prometheus 9090:9090      # http://localhost:9090
kubectl port-forward -n portfolio-advisor svc/tempo 3200:3200           # http://localhost:3200
kubectl port-forward -n portfolio-advisor svc/loki 3100:3100            # http://localhost:3100 (API only, no UI)
kubectl port-forward -n portfolio-advisor svc/alertmanager 9093:9093    # http://localhost:9093
```

Neither Tempo nor Loki ship a browser UI of their own (unlike Jaeger, which this stack used to run) — they're API-only and meant to be queried through Grafana. The port-forwards above are for hitting their HTTP APIs directly (e.g. `curl localhost:3200/api/search`), not for browsing.

### Metrics reference

Key metrics exposed at `/metrics` on the app (see [observability.py](observability.py)):

| Metric | What it tells you |
|---|---|
| `analyze_requests_total{outcome}` | Success/error rate of the core endpoint |
| `http_request_duration_seconds` | Request latency by route |
| `llm_calls_total{model,outcome}`, `llm_call_duration_seconds` | LLM reliability and speed |
| `llm_tokens_total{model,kind}` | Prompt/completion token usage, for cost/capacity planning |
| `agent_errors_total{agent,stage}` | Which pipeline stage is failing |
| `ollama_ready` | This pod's last readiness view of Ollama |

Alert rules live in [k8s/prometheus-configmap.yaml](k8s/prometheus-configmap.yaml) (`alert-rules.yml`): high `/analyze` error rate, no successful traffic, high p95 latency, high LLM failure rate, agent error spikes, and Ollama unreachable.

### Silencing / routing alerts (Alertmanager)

The default receiver in [k8s/alertmanager-configmap.yaml](k8s/alertmanager-configmap.yaml) is a no-op so the stack works without any external setup. To actually get paged, uncomment the `slack_configs` block and set a real webhook URL (or add `email_configs`/`pagerduty_configs`), then re-apply the configmap and restart the deployment:

```bash
kubectl apply -f k8s/alertmanager-configmap.yaml
kubectl rollout restart deployment/alertmanager -n portfolio-advisor
```

### Error tracking (Sentry)

Unhandled exceptions and agent-level failures are reported to Sentry when `SENTRY_DSN` is set — it's a no-op otherwise (see `observability.setup_sentry` / `observability.capture_exception`). In [k8s/app-deployment.yaml](k8s/app-deployment.yaml), replace the empty `SENTRY_DSN` env var with a `secretKeyRef` to a Secret holding your project DSN:

```bash
kubectl create secret generic portfolio-advisor-secrets \
  -n portfolio-advisor \
  --from-literal=sentry-dsn='https://xxx@oyyy.ingest.sentry.io/zzz'
```

```yaml
- name: SENTRY_DSN
  valueFrom:
    secretKeyRef:
      name: portfolio-advisor-secrets
      key: sentry-dsn
      optional: true
```

### Logs (Loki)

The app logs structured JSON to stdout (`LOG_FORMAT=json` is set in the deployment) — every line carries `request_id` and, once traces are flowing, `trace_id`/`span_id`. The OpenTelemetry Collector ([k8s/otel-collector.yaml](k8s/otel-collector.yaml)) tails these off every node and ships them to Loki, so they're searchable in Grafana's Explore view (or the dashboard's "Recent errors" panel) instead of only via live `kubectl logs`:

```logql
{namespace="portfolio-advisor"} | json | request_id="<id from a response header>"
{namespace="portfolio-advisor", app="portfolio-advisor-api"} | json | level="error"
```

`request_id`/`trace_id` are deliberately *not* Loki labels (see the `attributes/loki-labels` processor in [k8s/otel-collector.yaml](k8s/otel-collector.yaml)) — they're unique per request, and indexing unbounded values as labels is what blows up Loki's index. They're filtered via `| json` at query time instead, same as any other JSON field. Only `namespace`, `pod`, `container`, `app`, and `level` are promoted to indexed labels.

`kubectl logs` still works for tailing a live pod without going through Grafana at all:

```bash
kubectl logs -n portfolio-advisor -l app=portfolio-advisor -f | jq 'select(.request_id=="<id from a response header>")'
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
