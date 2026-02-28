#!/bin/bash
# ============================================================
# Bunny Clip Tool — Full Deployment Script
#
# Usage:
#   bash deploy.sh          # Full deploy (secrets + services)
#   bash deploy.sh --update # Code-only redeploy (skip secrets)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - service_account.json in current directory
#   - .env file filled in (copy from .env.example)
# ============================================================

set -e  # Stop on any error

UPDATE_ONLY=false
if [ "$1" == "--update" ]; then
  UPDATE_ONLY=true
  echo "🔄 Update mode — skipping secret creation, redeploying code only."
fi

# ── Load .env ─────────────────────────────────────────────────
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -v '^\s*$' | xargs)
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
echo "   Mode:    $([ "$UPDATE_ONLY" = true ] && echo 'UPDATE (code only)' || echo 'FULL (secrets + code)')"
echo ""

# ── Step 1: Set project ───────────────────────────────────────
gcloud config set project $PROJECT_ID --quiet

# ── Step 2: Store secrets (skip in --update mode) ─────────────
if [ "$UPDATE_ONLY" = false ]; then
  echo "🔐 Storing secrets in Secret Manager..."

  # Service account key
  if gcloud secrets describe service-account-key --quiet &>/dev/null; then
    echo "   ⏭️  service-account-key already exists — skipping"
  else
    gcloud secrets create service-account-key --data-file=service_account.json --quiet
    echo "   ✅ service-account-key created"
  fi

  # Telegram bot token
  if gcloud secrets describe telegram-bot-token --quiet &>/dev/null; then
    echo -n "$TELEGRAM_BOT_TOKEN" | \
      gcloud secrets versions add telegram-bot-token --data-file=- --quiet 2>/dev/null
    echo "   ✅ telegram-bot-token updated"
  else
    echo -n "$TELEGRAM_BOT_TOKEN" | \
      gcloud secrets create telegram-bot-token --data-file=- --quiet
    echo "   ✅ telegram-bot-token created"
  fi

  # Resend API key (if set)
  if [ -n "$RESEND_API_KEY" ]; then
    if gcloud secrets describe resend-api-key --quiet &>/dev/null; then
      echo -n "$RESEND_API_KEY" | \
        gcloud secrets versions add resend-api-key --data-file=- --quiet 2>/dev/null
      echo "   ✅ resend-api-key updated"
    else
      echo -n "$RESEND_API_KEY" | \
        gcloud secrets create resend-api-key --data-file=- --quiet
      echo "   ✅ resend-api-key created"
    fi
  fi
fi

# ── Step 3: Deploy Video Processor (main Cloud Run service) ───
echo ""
echo "⚙️  Deploying Video Processor service..."

gcloud run deploy bunny-clip-processor \
  --source . \
  --platform managed \
  --region $REGION \
  --service-account $SA_EMAIL \
  --set-env-vars "\
GCS_BUCKET=${GCS_BUCKET},\
SHEETS_ID=${SHEETS_ID},\
SOUNDS_FOLDER_ID=${SOUNDS_FOLDER_ID},\
PROCESSED_FOLDER_ID=${PROCESSED_FOLDER_ID},\
NOTIFICATION_EMAIL=${NOTIFICATION_EMAIL}" \
  --set-secrets "\
GOOGLE_APPLICATION_CREDENTIALS=service-account-key:latest,\
RESEND_API_KEY=resend-api-key:latest" \
  --memory 4Gi \
  --cpu 2 \
  --timeout 3600 \
  --no-allow-unauthenticated \
  --quiet

PROCESSOR_URL=$(gcloud run services describe bunny-clip-processor \
  --region $REGION --format "value(status.url)" --quiet)
echo "   ✅ Processor URL: $PROCESSOR_URL"

# ── Step 3b: Auto-update CLOUD_RUN_URL in .env ────────────────
if grep -q "^CLOUD_RUN_URL=" .env; then
  sed -i "s|^CLOUD_RUN_URL=.*|CLOUD_RUN_URL=${PROCESSOR_URL}|" .env
  echo "   ✅ Updated CLOUD_RUN_URL in .env"
else
  echo "CLOUD_RUN_URL=${PROCESSOR_URL}" >> .env
  echo "   ✅ Added CLOUD_RUN_URL to .env"
fi
export CLOUD_RUN_URL=$PROCESSOR_URL

# ── Step 4: Deploy Telegram Bot service ───────────────────────
echo ""
echo "🤖 Deploying Telegram Bot service..."

# Swap Dockerfile.bot → Dockerfile so --source picks it up
mv Dockerfile Dockerfile.processor
cp Dockerfile.bot Dockerfile

gcloud run deploy bunny-clip-bot \
  --source . \
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
ADMIN_CREATOR_NAME=${ADMIN_CREATOR_NAME:-Admin},\
KNOWN_CREATORS=${KNOWN_CREATORS:-},\
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

# Restore original Dockerfile
mv Dockerfile.processor Dockerfile

BOT_URL=$(gcloud run services describe bunny-clip-bot \
  --region $REGION --format "value(status.url)" --quiet)
echo "   ✅ Bot URL: $BOT_URL"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo "  Deployment complete!"
echo "════════════════════════════════════════════"
echo ""
echo "   Processor: $PROCESSOR_URL"
echo "   Bot:       $BOT_URL"
echo ""
echo "   Next steps:"
echo "   1. Update CLOUD_RUN_URL in Apps Script to: $PROCESSOR_URL"
echo "   2. Get your Telegram user ID: message @userinfobot on Telegram"
echo "   3. Add your ID to ADMIN_TELEGRAM_IDS in .env"
echo "   4. Test: send /start to your bot on Telegram"
echo ""
