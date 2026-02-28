#!/bin/bash
# ============================================================
# Bunny Clip Tool V2 — Deploy Script
#
# Run from inside the bunny-clip-tool-v2/ folder in Cloud Shell.
#
# Usage:
#   bash deploy.sh YOUR_TELEGRAM_BOT_TOKEN
#
# What it does:
#   1. Enables required GCP APIs
#   2. Creates GCS bucket (24h auto-cleanup)
#   3. Creates service account + IAM
#   4. Stores Telegram token in Secret Manager
#   5. Builds & deploys PROCESSOR (Cloud Run)
#   6. Builds & deploys BOT (Cloud Run)
# ============================================================
set -e

# ── Validate input ───────────────────────────────────────────
if [ -z "$1" ]; then
  echo "Usage: bash deploy.sh YOUR_TELEGRAM_BOT_TOKEN"
  echo ""
  echo "Get your bot token from @BotFather on Telegram."
  exit 1
fi

TELEGRAM_BOT_TOKEN="$1"
PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
SA_NAME="bunny-clip-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BUCKET="${PROJECT_ID}-clip-videos"

echo ""
echo "========================================"
echo "  Bunny Clip Tool V2 — Deploying"
echo "  Project: ${PROJECT_ID}"
echo "  Region:  ${REGION}"
echo "  Bucket:  ${BUCKET}"
echo "========================================"
echo ""

# ── 1. Enable required APIs ─────────────────────────────────
echo "[1/7] Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet
echo "  Done."

# ── 2. Create GCS bucket ────────────────────────────────────
echo "[2/7] Setting up GCS bucket..."
gsutil ls "gs://${BUCKET}" 2>/dev/null || gsutil mb -l $REGION "gs://${BUCKET}"

cat > /tmp/lifecycle.json << 'LIFECYCLE'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 1}
  }]
}
LIFECYCLE
gsutil lifecycle set /tmp/lifecycle.json "gs://${BUCKET}"
echo "  gs://${BUCKET} (24h auto-cleanup)"

# ── 3. Create service account + IAM ─────────────────────────
echo "[3/7] Setting up service account..."
gcloud iam service-accounts describe $SA_EMAIL 2>/dev/null || \
  gcloud iam service-accounts create $SA_NAME \
    --display-name="Bunny Clip Runner"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin" --quiet 2>/dev/null

echo "  ${SA_EMAIL}"

# ── 4. Store Telegram token in Secret Manager ────────────────
echo "[4/7] Storing Telegram bot token..."
if gcloud secrets describe telegram-bot-token --quiet 2>/dev/null; then
  echo -n "$TELEGRAM_BOT_TOKEN" | \
    gcloud secrets versions add telegram-bot-token --data-file=- --quiet
  echo "  Updated existing secret."
else
  echo -n "$TELEGRAM_BOT_TOKEN" | \
    gcloud secrets create telegram-bot-token --data-file=- --quiet
  echo "  Created new secret."
fi

gcloud secrets add-iam-policy-binding telegram-bot-token \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" --quiet 2>/dev/null

# ── 5. Deploy Processor ─────────────────────────────────────
echo "[5/7] Deploying processor (this takes 2-4 min)..."

# Cloud Run --source uses whatever file is named "Dockerfile"
cp Dockerfile.processor Dockerfile

gcloud run deploy bunny-clip-processor \
  --source . \
  --platform managed \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars "GCS_BUCKET=${BUCKET}" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 600 \
  --no-allow-unauthenticated \
  --max-instances 5 \
  --quiet

rm -f Dockerfile

PROCESSOR_URL=$(gcloud run services describe bunny-clip-processor \
  --region $REGION --format "value(status.url)")

gcloud run services add-iam-policy-binding bunny-clip-processor \
  --region $REGION \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" --quiet 2>/dev/null

echo "  ${PROCESSOR_URL}"

# ── 6. Deploy Bot ────────────────────────────────────────────
echo "[6/7] Deploying bot (this takes 2-4 min)..."

cp Dockerfile.bot Dockerfile

gcloud run deploy bunny-clip-bot \
  --source . \
  --platform managed \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars "PROCESSOR_URL=${PROCESSOR_URL},GCS_BUCKET=${BUCKET}" \
  --set-secrets "TELEGRAM_BOT_TOKEN=telegram-bot-token:latest" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --min-instances 1 \
  --max-instances 1 \
  --allow-unauthenticated \
  --quiet

rm -f Dockerfile

BOT_URL=$(gcloud run services describe bunny-clip-bot \
  --region $REGION --format "value(status.url)")

echo "  ${BOT_URL}"

# ── 7. Clean up old revisions ────────────────────────────────
echo "[7/7] Cleaning old revisions..."
for SERVICE in bunny-clip-bot bunny-clip-processor; do
  LATEST=$(gcloud run services describe $SERVICE \
    --region $REGION --format="value(status.latestReadyRevisionName)" 2>/dev/null) || continue
  for rev in $(gcloud run revisions list --service $SERVICE \
    --region $REGION --format="value(name)" 2>/dev/null); do
    [ "$rev" != "$LATEST" ] && gcloud run revisions delete "$rev" \
      --region $REGION --quiet 2>/dev/null || true
  done
done
echo "  Done."

echo ""
echo "========================================"
echo "  DEPLOYED SUCCESSFULLY"
echo ""
echo "  Processor: ${PROCESSOR_URL}"
echo "  Bot:       ${BOT_URL}"
echo ""
echo "  Test: message /start to your bot"
echo "  Then send any video (up to 5 min)"
echo "========================================"
