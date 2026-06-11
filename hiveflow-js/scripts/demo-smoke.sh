#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

readonly demos=(
  "demo:sequential"
  "demo:branching"
  "demo:action-executor"
  "demo:action-error"
  "demo:action-rollback"
  "demo:subworkflow"
  "demo:subworkflow-pause"
  "demo:team-config"
  "demo:team-generator"
  "demo:llm-team-generator"
  "demo:dynamic-collaboration"
  "demo:checkpoint"
  "demo:session-events"
  "demo:live-openai"
)

npm run build

for demo in "${demos[@]}"; do
  npm run "$demo"
done