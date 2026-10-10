#!/usr/bin/env bash
set -e

echo "Starting Uvicorn..."
python -m documind.interfaces.cli serve --port 8000 &
UVICORN_PID=$!

echo "Waiting for backend..."
while ! curl -s http://127.0.0.1:8000/healthz > /dev/null; do
    sleep 1
done

echo "Backend is up! Healthz:"
curl -s http://127.0.0.1:8000/healthz | jq .

echo "Indexing fixtures/demo_docs..."
python -m documind.interfaces.cli index ./docs

echo "Running one question via ask..."
curl -s -X POST http://127.0.0.1:8000/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is documind?", "top_k": 2}' | jq .

echo "Starting frontend..."
cd Documind-frontend
python -m http.server 5500 &
HTTP_PID=$!

echo "Open http://localhost:5500/stitch_documind_glass_box_ui/code.html"

trap "kill $UVICORN_PID $HTTP_PID" EXIT
wait
