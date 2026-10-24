#!/usr/bin/env bash
# Deploy the service to Google Cloud Run.
#
#   PROJECT=my-project ALERT_EMAIL=me@gmail.com ./scripts/deploy.sh
#
# Secrets must exist first (values are never passed on the command line):
#   ring-client-id, ring-client-secret, ring-hmac-key, link-password,
#   tasks-token, smtp-password
# e.g.  printf %s 'value' | gcloud secrets create ring-client-id --data-file=-
set -euo pipefail

: "${PROJECT:?set PROJECT}" "${ALERT_EMAIL:?set ALERT_EMAIL}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-animal-tracker}"
QUEUE="${QUEUE:-clips}"
TZ_NAME="${ALERT_TIMEZONE:-America/New_York}"

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com cloudtasks.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com

gcloud firestore databases describe >/dev/null 2>&1 \
  || gcloud firestore databases create --location="$REGION"
gcloud tasks queues describe "$QUEUE" --location="$REGION" >/dev/null 2>&1 \
  || gcloud tasks queues create "$QUEUE" --location="$REGION" \
       --max-concurrent-dispatches=2 --max-attempts=3

# The runtime service account needs Firestore, Cloud Tasks and the secrets.
SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
for role in roles/datastore.user roles/cloudtasks.enqueuer roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
    --role="$role" --condition=None >/dev/null
done

deploy() {
  gcloud run deploy "$SERVICE" --source . --region="$REGION" \
    --allow-unauthenticated --cpu=2 --memory=4Gi --timeout=600 --concurrency=4 \
    --min-instances=0 --max-instances=2 \
    --set-env-vars="USE_FIRESTORE=1,GOOGLE_CLOUD_PROJECT=$PROJECT,TASKS_LOCATION=$REGION,TASKS_QUEUE=$QUEUE,ALERT_SMTP_USERNAME=$ALERT_EMAIL,ALERT_TO=$ALERT_EMAIL,ALERT_TIMEZONE=$TZ_NAME" \
    --set-secrets="RING_CLIENT_ID=ring-client-id:latest,RING_CLIENT_SECRET=ring-client-secret:latest,RING_HMAC_KEY=ring-hmac-key:latest,LINK_PASSWORD=link-password:latest,TASKS_TOKEN=tasks-token:latest,ALERT_SMTP_PASSWORD=smtp-password:latest"
}

deploy
URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"
# The worker queues tasks to its own URL, known only after the first deploy.
gcloud run services update "$SERVICE" --region="$REGION" --update-env-vars="SERVICE_URL=$URL"

cat <<MSG

Deployed: $URL
In the Ring developer portal, set:
  Account Link URL:    $URL/ring/link
  Token Exchange URL:  $URL/ring/token
  Webhook URL:         $URL/ring/webhook
MSG
