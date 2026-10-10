#!/usr/bin/env bash
set -e

echo "=== Testing /healthz ==="
curl -s http://127.0.0.1:8000/healthz | jq .

echo -e "\n=== Testing /v1/documents (GET) ==="
curl -s http://127.0.0.1:8000/v1/documents | jq .

echo -e "\n=== Testing /v1/ask ==="
curl -s -X POST http://127.0.0.1:8000/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "test", "top_k": 2}' | jq .

echo -e "\n=== Testing /v1/events ==="
curl -s http://127.0.0.1:8000/v1/events | jq .

echo -e "\n=== Testing /v1/eval ==="
curl -s http://127.0.0.1:8000/v1/eval | jq .

echo -e "\n=== Testing /v1/meta ==="
curl -s http://127.0.0.1:8000/v1/meta | jq .
