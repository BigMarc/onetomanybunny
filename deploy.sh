#!/bin/bash
# ============================================================
# Bunny Clip Tool — Full Deployment Script
# Run this once to deploy both Cloud Run services.
# 
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - service_account.json in current directory
#   - .env file filled in (copy from .env.example)
# ============================================================

set -e  # Stop on any error

# ── Load .env ─────────────────────────────────────────────────
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo "❌ No .env file found. Copy .env.example to .env and fill in values."
  exit 1
fi

PROJECT_ID="bunny-clip-tool"
REGION="us-central1"
SA_EMAIL="bunny-clip-runner@${PROJECT_ID}.iam.gserviceaccount.com"

echo ""
echo "🚀 Starting Bunny Clip Tool deployment..."
echo "   Project: $PROJECT_ID"
echo "   Region:  $REGION"
echo ""

# ── Step 1: Set project ───────────────────────────────────────
gcloud config set project $PROJECT_ID

# ── Step 2: Store secrets ─────────────────────────────────────
echo "🔐 Storing secrets in Secret Manager..."

# Service account key
gcloud secrets describe service-account-key &>/dev/null || \
  gcloud secrets create service-account-key --data-file=service_account.json
echo "   ✅ service-account-key"

# Telegram bot token
echo -n "$TELEGRAM_BOT_TOKEN" | \
  gcloud secrets versions add telegram-bot-token --data-file=- 2>/dev/null || \
  echo -n "$TELEGRAM_BOT_TOKEN" | \
  gcloud secrets create telegram-bot-token --data-file=-
echo "   ✅ telegram-bot-token"

# SendGrid API key (if set)
if [ -n "$SENDGRID_API_KEY" ]; then
  echo -n "$SENDGRID_API_KEY" | \
    gcloud secrets versions add sendgrid-api-key --data-file=- 2>/dev/null || \
    echo -n "$SENDGRID_API_KEY" | \
    gcloud secrets create sendgrid-api-key --data-file=-
  echo "   ✅ sendgrid-api-key"
fi

# ── Step 3: Deploy Video Processor (main Cloud Run service) ───
echo ""
echo "⚙️  Deploying Video Processor service..."

gcloud run deploy bunny-clip-processor \
  --source . \
  --dockerfile Dockerfile \
  --platform managed \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars "\
GCS_BUCKET=${GCS_BUCKET},\
SHEETS_ID=${SHEETS_ID},\
SOUNDS_FOLDER_ID=${SOUNDS_FOLDER_ID},\
PROCESSED_FOLDER_ID=${PROCESSED_FOLDER_ID},\
NOTIFICATION_EMAIL=${NOTIFICATION_EMAIL},\
CLIP_DURATION=${CLIP_DURATION:-7},\
TEXT_FONT_SIZE=${TEXT_FONT_SIZE:-52},\
TEXT_POSITION=${TEXT_POSITION:-bottom}" \
  --set-secrets "\
GOOGLE_APPLICATION_CREDENTIALS=service-account-key:latest,\
SENDGRID_API_KEY=sendgrid-api-key:latest" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 3600 \
  --no-allow-unauthenticated \
  --quiet

PROCESSOR_URL=$(gcloud run services describe bunny-clip-processor \
  --region $REGION --format "value(status.url)")
echo "   ✅ Processor URL: $PROCESSOR_URL"

# ── Step 4: Deploy Telegram Bot service ───────────────────────
echo ""
echo "🤖 Deploying Telegram Bot service..."

gcloud run deploy bunny-clip-bot \
  --source . \
  --dockerfile Dockerfile.bot \
  --platform managed \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars "\
CLOUD_RUN_URL=${PROCESSOR_URL},\
GCS_BUCKET=${GCS_BUCKET},\
SHEETS_ID=${SHEETS_ID},\
PROCESSED_FOLDER_ID=${PROCESSED_FOLDER_ID},\
SOUNDS_FOLDER_ID=${SOUNDS_FOLDER_ID},\
ADMIN_TELEGRAM_IDS=${ADMIN_TELEGRAM_IDS},\
NOTIFICATION_EMAIL=${NOTIFICATION_EMAIL}" \
  --set-secrets "\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
GOOGLE_APPLICATION_CREDENTIALS=service-account-key:latest" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 3600 \
  --min-instances 1 \
  --allow-unauthenticated \
  --quiet

BOT_URL=$(gcloud run services describe bunny-clip-bot \
  --region $REGION --format "value(status.url)")
echo "   ✅ Bot URL: $BOT_URL"

# ── Step 5: Update Apps Script URL ───────────────────────────
echo ""
echo "📋 Copy this URL into your Apps Script CLOUD_RUN_URL variable:"
echo "   $PROCESSOR_URL"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "✅ ========================================"
echo "✅  Deployment complete!"
echo "✅ ========================================"
echo ""
echo "   Processor: $PROCESSOR_URL"
echo "   Bot:       $BOT_URL"
echo ""
echo "   Next steps:"
echo "   1. Update CLOUD_RUN_URL in Apps Script to: $PROCESSOR_URL"
echo "   2. Get your Telegram user ID: message @userinfobot on Telegram"
echo "   3. Add your ID to ADMIN_TELEGRAM_IDS in .env"
echo "   4. Redeploy bot: gcloud run deploy bunny-clip-bot --source . --dockerfile Dockerfile.bot --region $REGION"
echo "   5. Test: send a video to your bot!"
echo ""
