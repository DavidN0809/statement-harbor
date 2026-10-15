# Optional self-hosted integrations

These features extend the existing PaperPull run engine. They do not handle
institution credentials or fetch email links. All real-account and homelab
service acceptance remains **UNVERIFIED** until tested on the actual installation.

## Configuration and secrets

Copy `deploy/integrations.example.json` to `/config/integrations.json`, or set
`HARBOR_INTEGRATIONS` to a separately mounted JSON file. Configuration is read
each background pass. It is never returned by the dashboard API. Mount tokens,
Bridge username/password and the Bridge CA certificate as separate secret files.
Do not put real values in tracked examples, environment dumps or issue reports.
Use private TLS service origins with no path, query, fragment or userinfo.
For an explicitly configured private HTTP origin set `allow_private_http: true`;
the network path must then be trusted because HTTP carries its service token.
Redirects and environment HTTP proxies are refused; TLS verification stays on.

The dashboard edits schedules, expectations and notification suppression. Service
origins and secret references stay in administrator-managed configuration.
The worker checks delivery and notices every minute and Bridge every 15 minutes.
Configuration errors appear as fixed status codes. No remote error text is logged.

## Paperless transports

`paperless.mode` defaults to `consume`. Existing consume-folder integration and
`PAPERLESS_SUBFOLDERS=1` remain supported. `HANDED_OFF` confirms atomic publication,
not Paperless processing. An ambiguous consume crash enters `UNCERTAIN`; compare
the private archive and Paperless before any manual recovery. Never reset the
delivery database to retry files: that destroys the idempotency history.

For `mode: api`, supply `url`, `token_file` and optional `create_metadata: true`.
The client uses Paperless API v9, submits multipart PDFs, persists the task UUID,
and polls task status. A retrieved original must match the local SHA-256 before
`DELIVERED` is recorded. Paperless's MD5 checksum filter only selects candidates;
it is not used as cryptographic proof. A preexisting matching original avoids
upload entirely. API failures never cause the provider to download again.

`SUBMITTING` is committed **before** POST. If submission or task-ID persistence
has an ambiguous failure, that row only reconciles originals; it never resubmits.
Restore access and let reconciliation continue. If no original appears, inspect
Paperless tasks and worker logs privately. Only after proving there is no pending
or completed ingestion may an administrator reset that specific row offline.
There is deliberately no blind retry button for ambiguous submissions.

`PROCESSING` waits for confirmation. `API_FAILED` means a task definitively
failed or was revoked; the dashboard offers **Retry ingestion**. This validates
and sends the local original again, without a provider run. `CORRUPT` documents
are never delivered. The original archive is retained in all cases.

Each document pins its transport at enqueue time. Changing the configured mode
does not replay old consume deliveries over the API. Pending API rows pause when
API mode is disabled. Back up the outbox and its source PDFs together.

When metadata creation is enabled, the client finds or creates institution
correspondents, document types and institution/category tags. Grant the dedicated
Paperless user only the required document and metadata access. Configure safe
categories with `account_categories`, keyed by the exact install/account alias
shown in Automation, such as `Ally/primary`. Allowed categories are Checking,
Savings, Credit Card, Loan, Mortgage, Utility and Investment. Unknown values become
Financial. Types and dates come from normalized engine records. Provider titles,
names and account numbers are discarded. A safe date/institution/category/type
title plus an opaque identity suffix names consume files. API upload filenames
are opaque and the descriptive title is supplied separately. A PDF is limited
to 64 MiB for this transport.

Contract sources: [Paperless upload and task API](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/api.md),
[checksum filtering](https://github.com/paperless-ngx/paperless-ngx/blob/main/src/documents/filters.py).
Validate your installed Paperless version's API schema and task behavior before
turning on production delivery; synthetic tests do not replace this check.

## Proton Mail Bridge

Use the locally operated [official Bridge](https://proton.me/support/bridge-for-linux),
its dedicated credentials and a dedicated Billing folder. The collector does not
depend on a third-party aggregation SaaS. Proton Mail itself remains the existing
external mail provider. Bridge outages do not stop cron checks or local delivery.
Bridge defaults to [IMAP port 1143](https://proton.me/support/port-already-occupied-error).
The client requires STARTTLS with the configured CA and hostname verification.
Install the Bridge certificate for the actual endpoint; never disable TLS checks.
Keep Bridge's listener private or on a trusted local tunnel.

First inspect a legitimate message locally and confirm the first
`Authentication-Results` field is added by Proton, that untrusted copies are
removed or follow it, and identify its exact authentication-service identifier.
Set `authserv_id` to that observed value. Do not guess it from the sample.
The collector requires that first result to report aligned `dmarc=pass` and an
exact allowlisted From address. Forwarded mail whose authentication cannot be
established is ignored. Configure each `mappings` entry with `app`, `account`
and an explicit `senders` list. Keep personal addresses in private config.

Only selected headers are fetched with `BODY.PEEK`; the folder is selected
read-only. No message is marked read, moved or deleted. Initial connection and
UIDVALIDITY changes baseline existing messages; only subsequent messages trigger
checks. The durable cursor prevents reprocessing across restarts. Period hints
in subjects cannot alter URLs, scope, account settings or portal selection.
Triggers coalesce and honor enablement, minimum intervals, backoff and human
authentication states. They never reset exhausted retries. Invalid Bridge
credentials stop mail login attempts for that worker; update the configuration
or restart after repairing the credential to try once again.

No direct PDF-link path is enabled. HTML bodies, links, redirects and attachments
are never fetched or opened. A valid notification only queues the existing trusted
provider adapter. Missing or unverifiable sender authentication fails closed.

## Home Assistant

Set `home_assistant.enabled`, `url` and `token_file`. The authenticated
[REST service API](https://developers.home-assistant.io/docs/api/rest/) calls only
`persistent_notification.create`. Stable opaque notification IDs and a durable
incident ledger make repeated polls and ambiguous HTTP outcomes idempotent.
Notifications include sanitized provider names and fixed actionable messages;
account aliases, dates, URLs, exception text and PDF contents are never sent.

Authentication, challenges and unexplained stops notify on intervention.
Download/rate-limit failures require at least two failed attempts. Delivery
problems must persist for an hour. Corrupt documents and missing expectations
notify when detected. Successful checks produce no notices. Per-provider
suppression is available on Automation. Existing HA persistent notices can be
dismissed in HA; a resolved and later recurring incident can notify again.

## Archive expectations and publication retries

Save a JSON array of expectations for the selected login/account in Automation.
Each rule has `start` (the first statement period), `cycle` (`monthly`, `quarterly`
or `annual`), `available_day`, `publication_lag_months`, `grace_days`, `zone` and
`document_type` (`statement`, `tax`, `bill` or `notice`). A day beyond month end
clamps to that month's final date. Quarter/year cycles advance from the configured
start month. Billing dates are local calendar dates, independent of DST hours.
History is bounded to ten years per rule. Tax document issue dates may differ
from tax years: configure the expected period to match normalized engine records.

Separate financial subaccounts under one login need separate rules with
`account_field` identifying the engine record field and `account_key` equal to
SHA-256 of that field's exact value. Determine this privately from the local
archive. Never paste actual numbers into rule labels or notifications. Without
a key, a rule covers the login's whole document stream; it cannot prove coverage
for every financial subaccount. Missing-document checks are local only.

Optional `retry_missing: true` permits two additional checks at least one day
apart within the publication window (at least seven days, or the grace interval
when longer). The account must already have completed a check. Global/provider/
account switches, account locks, authentication stops and concurrency still apply.
Historical gaps cannot trigger unbounded retries. Keep tax-only checks seasonal
and utility schedules aligned with their actual issue dates.

Historical backfill uses the selected account and explicit start/end dates,
bounded to ten years. It persists scope across interruption and failures, reuses
the existing download ledger and clears the one-off scope after success.
