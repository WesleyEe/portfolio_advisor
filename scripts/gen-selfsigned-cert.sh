#!/usr/bin/env bash
# Generates a self-signed TLS certificate for the ingress host and loads it
# into the cluster as a Secret that k8s/app-ingress.yaml references.
set -euo pipefail

HOST="${1:-portfolio-advisor.local}"
NAMESPACE="${2:-portfolio-advisor}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"
SECRET_NAME="portfolio-advisor-tls"

mkdir -p "$OUT_DIR"

echo "Generating self-signed cert for CN=${HOST} ..."
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "${OUT_DIR}/tls.key" \
  -out "${OUT_DIR}/tls.crt" \
  -subj "/CN=${HOST}/O=portfolio-advisor" \
  -addext "subjectAltName=DNS:${HOST}"

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl apply -f "$(dirname "${BASH_SOURCE[0]}")/../k8s/namespace.yaml"

kubectl create secret tls "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --cert="${OUT_DIR}/tls.crt" \
  --key="${OUT_DIR}/tls.key" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret '${SECRET_NAME}' created/updated in namespace '${NAMESPACE}'."
echo
echo "To trust this certificate in your browser, import ${OUT_DIR}/tls.crt"
echo "into your OS/browser trust store (it will otherwise show as untrusted)."
