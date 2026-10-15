# Statement Harbor

Statement Harbor is a self-hosted financial document collector derived from
[PaperPull](https://github.com/rheeloaded/paperpull). It is a modified fork,
not an upstream release. Source: <https://github.com/DavidN0809/statement-harbor>.
AGPL-3.0-only, upstream notices and the trademark policy remain applicable.
The fork distributes its server image as Statement Harbor. Upstream desktop
packaging workflows are dormant in this fork until those artifacts are renamed.

## Current scope

Milestones 1 and 2 and the locally testable advanced integrations have source
implementations and synthetic regression tests.
No real financial credentials were used. The Docker build and local container
smoke/self-test passed, including Chrome's namespace sandbox and seccomp.
Homelab Kubernetes deployment, actual provider session persistence and
Paperless processing remain **UNVERIFIED**. The repository contains deployment
samples, not an assertion that a homelab rollout has been validated.

Implemented:

- Durable SQLite schedules, settings, attempts, success timestamps, bounded
  exponential retries, coalesced missed runs and interrupted-job recovery.
- Global scheduling and per-provider/per-account switches, daily, weekly,
  monthly and five-field custom cron, IANA timezones, global concurrency and
  minimum intervals. Default monthly schedule: day 10 at 09:00 New York time.
- A server-only Automation dashboard with state, timing, counts, schedule
  editing, run requests, explicit resume and local delivery retries.
- Background execution through the existing panel subprocess and provider
  main function. Closing the Automation page does not stop a scheduled job.
- Existing interactive profile/CDP reuse. A missing browser can reopen its
  existing profile at `about:blank`, without navigating to a login endpoint.
  Provider navigation then determines whether the session is usable.
- Fail-closed authentication/challenge signals, no automatic authentication
  retries, no inactivity-session extension clicks, and no raw scheduled logs.
- Durable PDF validation and consume-folder outbox, independent delivery
  retries, atomic publication, and conservative handling of ambiguous crashes.

Additional implementation:

- Optional Paperless REST delivery with durable submission/task state, original
  SHA-256 verification, safe metadata and independent ingestion retries.
- Optional Proton Bridge read-only IMAP hints with authenticated-sender checks,
  durable UID cursors and no hyperlink or attachment retrieval.
- Persistent Home Assistant intervention notices, deduplication and per-provider
  suppression. Transient delivery failures have an hour's grace.
- Local monthly/quarterly/annual archive expectations, separate financial account
  keys, opt-in bounded publication retries and durable historical backfill.
- Consume-folder and REST-only Compose/Kubernetes deployment examples and mounted
  secret references. See [INTEGRATIONS.md](INTEGRATIONS.md).

Outstanding live-account dependency:

NCSECU, SoFi and FFSB have no runnable adapters yet and are tracked as planned
work in repository issues. No stub providers are shipped. Authenticated
document lists and download controls need actual authorized sessions;
FFSB's public eStatements page does not establish mortgage coverage.
Aqua and Rutherford remain future work. No selectors or provider functionality
have been invented.
See [PROVIDER-VALIDATION.md](PROVIDER-VALIDATION.md) for evidence and acceptance.
The complete project definition of done remains unfulfilled until those provider
adapters, actual service ingestion and homelab deployment are validated.

## Architecture audit

Examined upstream commit `9f0fd44d34cd2dba9c944601f1ee07d933bd2c87` (v0.52.0).
The clone retained upstream history. `upstream` points to rheeloaded/paperpull,
and `origin` points to DavidN0809/statement-harbor.

| Area | Existing architecture | Fork extension |
| --- | --- | --- |
| Server | `gui/app.py` FastAPI panel, `server_mode.py` password gate and browser-screen proxy | Server lifespan owns one dispatcher and an exclusive process lock |
| Provider orchestration | Each `*_docs.py` or `*_receipts.py` coordinates discovery and downloads | Existing `--all --yes` performs discovery and skips the engine's sticky downloaded records |
| Provider behavior | `*_site.py` holds host allowlists, safe-control checks, selectors and session detectors | A core entry-point wrapper translates existing detectors into fixed unattended states |
| Core | AppSpec-bound storage, identity, PDF validation, capture/delivery, keys, classification, readiness, progress journals | Small scheduling-only filename policy and a separate local delivery outbox |
| Browser | Playwright attaches over loopback CDP to each account's profile, stored outside the shared data directory | No password/MFA/CAPTCHA automation, profile identity checked before execution |
| Download history | `discovery.json`, `progress.json`, sticky `downloaded_ok`, indexes and `new-this-run.txt` | Reuses this identity/history rather than introducing a second scraper ledger |
| Paperless | Post-run trusted plug-in copies only new PDFs with hidden staging files | Optional durable outbox enabled in the fork image, legacy copy mode retained for compatibility |
| Security | scrypt password, random HttpOnly sessions, origin and Host checks, frame protection, trusted-image imports with `-P` | Automation routes retain those guards, settings use fixed schemas and SQL parameters |
| Build | Tracked-file allowlist, Debian Python image, signed Chrome bootstrap, non-root application, custom seccomp | Existing build/sandbox retained, fork image identity and health check added |
| Status | Existing local `tools/status.py`, GUI history and archive analysis | Automation overview adds per-account state and last/next run times |
| Tests | Core, provider, panel and server suites, synthetic DOM fixtures, browser fixtures and privacy canary | Scheduler, outbox, wrapper, API and deployment regressions |

### Existing providers

Upstream already contains American Express (`amex`), Citi, Discover
(`discovercard`), Chase, Wealthfront, Amazon, Fidelity, Ally and Nelnet.
These adapters were retained. No claim is made that upstream's reported
validation applies to this user's accounts.

Ally's adapter targets **Ally Bank**, particularly its Statements & Documents
interface and tax-document tabs. It is not an Ally Auto adapter. Confirm the
actual product before enabling a schedule. Its current tab/session may not
survive restart even with a persistent profile.

Nelnet targets **nelnet.studentaid.gov** federal student-loan servicing. Its
existing inbox statements/notices and print-rendered 1098-E path remain intact.
Confirm whether the user's loan is serviced through that portal or a different
Nelnet/private-loan product. Synthetic tests cannot establish account coverage.

## Scheduling contract

SQLite stores declarative cron data, never executable pickles. APScheduler's
CronTrigger calculates the next aware instant, persisted in UTC. Downtime
coalesces missed occurrences into one check. The repeated DST hour represents
distinct UTC instants, and minimum intervals prevent closely spaced automatic
runs. A nonexistent wall-clock time follows CronTrigger semantics, so use
09:00 rather than the DST transition hours for financial schedules. Day 31
skips shorter months. Weekdays use APScheduler numbering, Monday 0 to Sunday 6.

Automation starts disabled. A new account schedule is disabled unless enabled
explicitly. Existing provider download delays are preserved. Default global
concurrency is two, minimum automatic interval is six hours, failure retry
delay is six hours doubling for at most two retries. After retry exhaustion,
the job stays FAILED until a manual request. These values are configurable.

Run now is an explicit manual request and can run while automatic scheduling
is disabled. It bypasses the automatic minimum interval, while retaining the
account lock and global concurrency cap. A known RATE_LIMITED job cannot be
manually queued before its backoff ends. AUTH_REQUIRED and CHALLENGE_REQUIRED
need an explicit resolved/resume action. Saving a schedule never clears them.

On restart an interrupted job is retried after the minimum interval. The
existing `--all` path repeats discovery and continues from sticky history,
including failed documents. It does not replay already successful downloads.
This is intentionally not `--resume`, which does not always discover newly
published documents and requires a complete earlier listing.

READY, RUNNING, AUTH_REQUIRED, CHALLENGE_REQUIRED, RATE_LIMITED, COMPLETED,
NO_NEW_DOCUMENTS, FAILED and PAUSED are durable states. Ambiguous stopped runs
become PAUSED, not successful empty checks. Allowlisted HTTP 429 responses stop
the next guarded provider operation and produce RATE_LIMITED. Other provider
rate-limit classification depends on that adapter. An unrecognized wall can
require inspection as PAUSED. A missing detector contract also
pauses before browser startup.

In addition to the server process lock, each scheduled subprocess holds an OS
account lock. A replacement server cannot drive that account while an orphaned
worker still owns it. Supervised runs check that lock as well. Run the supplied
single-worker container, without Uvicorn reload or multiple application owners.

Connecting the browser screen cancels active scheduled work safely and pauses
dispatch globally. Because the shared screen can control any provider, this
is deliberately broader than an account-level pause. Cancelled jobs become
PAUSED and require explicit resume after closing the screen. A server restart
cancellation instead retains RUNNING for crash recovery.

Scheduled filenames use date, the fixed provider name and `Document`. Distinct
same-day PDFs retain the engine's unique suffixes and identity keys. This
excludes provider titles, account labels, addressees and custom patterns that
could carry full account numbers. Existing supervised naming is preserved.

## Delivery contract

The existing engine owns provider/account/type/period/provider-document IDs
and successful-download state. The outbox adds SHA-256, source location and an
independent handoff state, so failed delivery never requires a redownload.
Different same-date PDFs get separate rows. Local paths remain private state.

PENDING is retried locally every minute and by the dashboard button. CORRUPT
means validation failed or bytes changed after enqueue. PUBLISHING is committed
before the atomic rename. HANDED_OFF confirms consume-folder publication,
not Paperless processing. Delivery filenames contain an institution label
and an opaque digest, never the original potentially sensitive filename.

The consume protocol has no processing acknowledgement. If a crash leaves no
hidden part file after PUBLISHING, it is impossible to tell whether Paperless
already consumed the file. That row becomes UNCERTAIN and is never resent
automatically. The original archive PDF remains available. Resolving that
ambiguity needs operator inspection or a future API transport. End-to-end
exactly-once confirmed ingestion is therefore **not claimed**.

Recovery can reconcile successful engine progress records created since the
prior scheduled attempt, under that account's archive root. A PDF not recorded
in durable engine progress before a hard crash still needs archive inspection.
The outbox uses the engine's stable progress key plus the PDF hash. Where a
legacy provider supplies no keyed progress record, it falls back to source
location plus hash. Renaming and explicitly re-enqueueing a legacy document
without its engine key can create a new identity. Keyed engine records remain
idempotent through source renames, including distinct same-date documents.

## Real-account acceptance

For each account, keep automation disabled, confirm the exact institution and
product, open the existing sign-in window and sign in yourself. Handle MFA
and any provider challenge yourself. Inspect Documents/Statements and run the
existing newest-few pilot. Verify each PDF's type, period, masked account and
content against the actual provider list, including multiple same-date files.

Close the screen, enable one conservative account schedule, use Run now and
verify Paperless's resulting document. Repeat with no new documents. Restart
the container and test actual session reuse. If it requires login, confirm
AUTH_REQUIRED/CHALLENGE_REQUIRED or a conservative PAUSED outcome, no repeated
authentication attempts, and successful manual recovery. Stop if the provider
disallows automation. Record provider/product/date validation locally, outside
Git. Only then consider marking that account verified.
