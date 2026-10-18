#!/usr/bin/env bash
#
# Assemble the Part 3 serverless deploy bundle (VS Code Azure Functions extension).
#
# Copies the Function source from `serverless/` and the shared, dependency-light
# units from `src/` into `build/function/`, so the extension deploys the exact
# modules the local pipeline uses (nothing duplicated). Idempotent: re-run after
# any change to those files, then deploy from VS Code by opening `build/function/`.
#
#   bash deploy/build_function.sh
#
# The bundle is gitignored. The extension only treats a folder as an initialized
# Functions project when `.vscode/settings.json` is present, so a minimal one is
# scaffolded here (otherwise "Deploy to Function App" offers to re-initialize the
# project every time). `.funcignore` keeps the extension from uploading the
# local-only artifacts (`.venv`, `.vscode`, `local.settings.json`).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_DIR="build/function"
SERVERLESS_FILES=(function_app.py host.json requirements.txt)
SHARED_FILES=(blob_transport.py csv_log.py render.py vision.py)

# Never leave a local .venv behind; scaffold the extension's project marker.
rm -rf "$BUILD_DIR/.venv"
mkdir -p "$BUILD_DIR" "$BUILD_DIR/.vscode"

for file in "${SERVERLESS_FILES[@]}"; do
    cp "serverless/$file" "$BUILD_DIR/$file"
done
for file in "${SHARED_FILES[@]}"; do
    cp "src/$file" "$BUILD_DIR/$file"
done

cat > "$BUILD_DIR/.vscode/settings.json" <<'JSON'
{
    "azureFunctions.deploySubpath": ".",
    "azureFunctions.scmDoBuildDuringDeployment": true,
    "azureFunctions.projectLanguage": "Python",
    "azureFunctions.projectRuntime": "~4",
    "debug.internalConsoleOptions": "neverOpen"
}
JSON

cat > "$BUILD_DIR/.vscode/extensions.json" <<'JSON'
{
    "recommendations": [
        "ms-azuretools.vscode-azurefunctions",
        "ms-python.python"
    ]
}
JSON

printf '.venv\n.vscode\nlocal.settings.json\n__pycache__\n*.pyc\n' > "$BUILD_DIR/.funcignore"

echo ">> assembled $BUILD_DIR:"
ls -A "$BUILD_DIR"
