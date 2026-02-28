#!/bin/bash
set -e

PROJECT_ID="bunny-clip-tool"
REGION="us-central1"
SA_EMAIL="bunny-clip-runner@${PROJECT_ID}.iam.gserviceaccount.com"
BUCKET="bunny-clip-tool-videos"

gcloud config set project $PROJECT_ID

# ── 1. Create GCS bucket (if not exists) ─────────────────────
gsutil ls "gs://${BUCKET}" 2>/dev/null || gsutil mb -l $REGION "gs://${BUCKET}"

# Set lifecycle: auto-delete after 24h
cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 1}
  }]
}
EOF
gsutil lifecycle set /tmp/lifecycle.json "gs://${BUCKET}"
echo "GCS bucket ready: gs://${BUCKET} (24h auto-cleanup)"

# ── 2. Create service account + IAM (if not exists) ──────────
gcloud iam service-accounts describe $SA_EMAIL 2>/dev/null || \
  gcloud iam service-accounts create bunny-clip-runner \
    --display-name="Bunny Clip Runner"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin" --quiet

echo "Service account ready: ${SA_EMAIL}"

# ── 3. Deploy Processor ──────────────────────────────────────
echo "Deploying processor..."

gcloud run deploy bunny-clip-processor \
  --source . \
  --dockerfile Dockerfile.processor \
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

PROCESSOR_URL=$(gcloud run services describe bunny-clip-processor \
  --region $REGION --format "value(status.url)")

# Allow service account to invoke processor
gcloud run services add-iam-policy-binding bunny-clip-processor \
  --region $REGION \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" --quiet

echo "Processor: ${PROCESSOR_URL}"

# ── 4. Create Telegram bot token secret ──────────────────────
# Only needed once — set your token:
# echo -n "YOUR_BOT_TOKEN" | gcloud secrets create telegram-bot-token --data-file=-
# gcloud secrets add-iam-policy-binding telegram-bot-token \
#   --member="serviceAccount:${SA_EMAIL}" --role="roles/secretmanager.secretAccessor"

# ── 5. Deploy Bot ────────────────────────────────────────────
echo "Deploying bot..."

gcloud run deploy bunny-clip-bot \
  --source . \
  --dockerfile Dockerfile.bot \
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

BOT_URL=$(gcloud run services describe bunny-clip-bot \
  --region $REGION --format "value(status.url)")

echo "Bot: ${BOT_URL}"

# ── 6. Clean up old revisions ────────────────────────────────
for SERVICE in bunny-clip-bot bunny-clip-processor; do
  LATEST=$(gcloud run services describe $SERVICE \
    --region $REGION --format="value(status.latestReadyRevisionName)")
  for rev in $(gcloud run revisions list --service $SERVICE \
    --region $REGION --format="value(name)" 2>/dev/null); do
    [ "$rev" != "$LATEST" ] && gcloud run revisions delete "$rev" \
      --region $REGION --quiet 2>/dev/null || true
  done
done

echo ""
echo "========================================"
echo "  Deployment complete!"
echo "  Processor: ${PROCESSOR_URL}"
echo "  Bot:       ${BOT_URL}"
echo "========================================"
