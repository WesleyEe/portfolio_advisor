#!/usr/bin/env bash
# Generates a self-signed TLS certificate for an ingress host and loads it
# into the cluster as a Secret. k8s/app-ingress.yaml and k8s/grafana-ingress.yaml
# reference these by SECRET_NAME.
#
# Usage: gen-selfsigned-cert.sh <host> [namespace] [secret-name]
set -euo pipefail

HOST="${1:-portfolio-advisor.local}"
NAMESPACE="${2:-portfolio-advisor}"
SECRET_NAME="${3:-portfolio-advisor-tls}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"

# Keep the original portfolio-advisor.local cert at certs/tls.crt for
# backward compatibility (DEPLOYMENT.md's curl --cacert examples reference
# it directly); other hosts/secrets get their own filenames so a second
# call (e.g. for Grafana) doesn't clobber the app's cert.
if [ "$SECRET_NAME" = "portfolio-advisor-tls" ]; then
  CERT_FILE="${OUT_DIR}/tls.crt"
  KEY_FILE="${OUT_DIR}/tls.key"
else
  CERT_FILE="${OUT_DIR}/${SECRET_NAME}.crt"
  KEY_FILE="${OUT_DIR}/${SECRET_NAME}.key"
fi

mkdir -p "$OUT_DIR"

echo "Generating self-signed cert for CN=${HOST} ..."
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "${KEY_FILE}" \
  -out "${CERT_FILE}" \
  -subj "/CN=${HOST}/O=portfolio-advisor" \
  -addext "subjectAltName=DNS:${HOST}"

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl apply -f "$(dirname "${BASH_SOURCE[0]}")/../k8s/namespace.yaml"

kubectl create secret tls "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --cert="${CERT_FILE}" \
  --key="${KEY_FILE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret '${SECRET_NAME}' created/updated in namespace '${NAMESPACE}'."
echo
echo "To trust this certificate in your browser, import ${CERT_FILE}"
echo "into your OS/browser trust store (it will otherwise show as untrusted)."
