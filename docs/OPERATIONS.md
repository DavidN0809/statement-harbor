# Statement Harbor operational runbook

## Build and test

Python 3.11 or newer is required. Use a private checkout and do not place
financial PDFs, real configuration or profiles under tracked paths.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r server/requirements.txt pytest httpx PyYAML
.venv/Scripts/python -m pip install -e core
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python -m pytest gui/tests/test_automation.py core/tests/test_outbox.py server/tests
.venv/Scripts/python tools/run_all_tests.py --jobs 4
```

On Linux use `.venv/bin/python`. The full upstream suite is substantial and
may take over an hour on a small machine. The runner verifies the privacy
canary actually ran. See [validation results](VALIDATION.md) for this checkout.

Build with Docker on x86_64 Linux, or a Docker engine supporting that platform:

```sh
python server/build.py --name statement-harbor --save statement-harbor.tar
python server/smoke.py --image statement-harbor:dev
```

The build intentionally includes only Git-tracked application files. Commit
or stage reviewed source files before building. Never use a broad working-tree
Docker context containing personal financial data. The built image uses
Statement Harbor branding. Internal `PAPERPULL_*` names stay for compatibility.

## Compose trial

Set `PAPERLESS_CONSUME_HOST` to Paperless's existing consume directory, then:

```sh
docker compose -f deploy/compose.yaml config
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml logs collector
```

The sample binds only `127.0.0.1:8765`. Reach it through your private reverse
proxy, SSH tunnel or VPN. Do not forward it publicly. If your proxy runs in a
different container, attach a private Docker network and route to `collector`,
or deliberately bind the service to a trusted LAN address. Set
`PAPERPULL_HOSTS` to the private DNS name. Use TLS at your proxy.

Choose a dashboard password using the first-start setup code. Add the existing
providers and accounts, sign in interactively and validate the pilot. The
Automation link edits schedules. Start with one account and low concurrency.

Do not point the fork at an upstream installation's active profiles while the
upstream container is running. Only one application may own these volumes.
No debugging/VNC ports should be published. The upstream custom seccomp profile
is required, and `--no-sandbox`, privileged containers and unconfined seccomp
are prohibited.

## Kubernetes prerequisites

Do not apply the sample blindly to an existing homelab. Configure:

1. An x86_64 node whose kernel permits unprivileged user namespaces and whose
   security policy supports upstream Chrome's sandbox. Install the unchanged
   `server/seccomp-chrome.json` as
   `/var/lib/kubelet/seccomp/profiles/statement-harbor-chrome.json` on every
   eligible node. Use your node-management process, not a privileged app pod.
2. A locally loaded or privately hosted `statement-harbor` image, preferably
   pinned by digest. Replace both init and application image references.
3. Appropriate storage classes and capacities for the four PVCs. Use one
   replica and Recreate updates. SQLite and browser profiles require reliable
   filesystem locking and atomic rename. Prefer block-backed local filesystems
   over network filesystems with uncertain locking semantics.
4. The existing Paperless consume storage exposed through a compatible PVC
   named `paperless-consume` in the `statement-harbor` namespace. A PVC cannot
   reference another namespace's claim. Arrange an appropriate RWX share or
   provision equivalent storage through your cluster administrator. Never
   mount one RWO filesystem concurrently on incompatible nodes. REST ingestion
   for deployments without shared storage remains deferred.
5. A private ingress controller and NetworkPolicy-capable CNI. Adapt the
   ingress namespace selector and the `PAPERPULL_HOSTS` value. No public ingress
   or browser debugging service is included. Standard NetworkPolicy allows
   outbound public HTTP(S), needed for institution sites and signed Chrome
   bootstrap. For stronger FQDN restriction, use your CNI's domain policy or a
   controlled egress proxy, listing each provider's verified hosts. The DNS
   policy assumes CoreDNS pods carry `k8s-app=kube-dns`, adapt for NodeLocal DNS.
6. Kubernetes Secrets for optional credentials. Initial dashboard setup needs
   no plaintext Secret. If provisioning its initial password, inject
   `PAPERPULL_PASSWORD` using a Secret `valueFrom.secretKeyRef`, never a committed
   value. Remove it after setup. No institution passwords are accepted.

The sample's init container runs as root only for upstream's signed Chrome
bootstrap and directory ownership. It drops all capabilities except CHOWN,
FOWNER and DAC_OVERRIDE. The application runs as UID/GID 1000, with no
capabilities, a read-only root filesystem, writable temporary/home volumes,
and a read-only browser volume. Validate this on the target kernel. The init
container needs writable image layers for apt. The pod is not suitable for a
namespace enforcing Kubernetes Restricted admission without an approved
bootstrap arrangement. Do not weaken Chrome's sandbox to satisfy admission.

```sh
kubectl apply --dry-run=client -f deploy/kubernetes.yaml
kubectl apply -f deploy/kubernetes.yaml
kubectl -n statement-harbor rollout status deployment/statement-harbor
kubectl -n statement-harbor exec deployment/statement-harbor -- python /opt/paperpull/server/selftest.py
```

Only the operator should perform these cluster mutations after tailoring the
manifest. No deployment was attempted during development. The `/healthz`
probe checks service, dispatch and local-delivery task availability. A failed
durable state update stops dispatch and fails health. The endpoint reveals
only availability, never account data. It does not certify financial sessions.

## Recovery and intervention

- **AUTH_REQUIRED:** automatic runs stop. Open Accounts, sign in yourself in
  the existing window, close the screen, then select Resolved, resume.
- **CHALLENGE_REQUIRED:** complete the provider's own challenge yourself.
  Never provide codes or credentials to automation. Resume explicitly.
- **PAUSED:** inspect the provider page and supervised diagnostic tools. The
  scheduler refuses to guess whether an unrecognized stop is safe to retry.
- **FAILED:** inspect the provider through the existing supervised interface.
  Automatic retries are bounded. Correct the cause and request a new run.
- **RATE_LIMITED:** leave the job alone through its backoff. Some adapters
  cannot identify rate limiting separately and will pause instead.
- **PENDING delivery:** restore the consume mount/permissions. Local retries
  continue each minute without accessing the institution. Retry handoffs runs
  only the local outbox and does not redownload anything.
- **CORRUPT:** retain the original for private inspection. Correct the archive
  through supervised provider tools, then enqueue the corrected PDF. Do not
  force an HTML login page or incomplete PDF into Paperless.
- **UNCERTAIN:** first find the opaque digest filename/content in Paperless's
  documents, tasks, duplicate history and consume folder. Stop the application
  and back up the database before resolving it. If confirmed ingested, record
  HANDED_OFF. If positively confirmed absent, set PENDING and retry. Do not
  assume absence from the consume directory means failure. An absent part
  file cannot distinguish successful consumption from an interrupted publish.

The private `delivery.sqlite3` stores IDs, source/destination paths, SHA-256
and fixed states/errors. Use a local SQLite client against a stopped instance
for exceptional reconciliation. There is deliberately no blind UNCERTAIN
retry button. Keep this state with the source PDFs to avoid losing the evidence.

After any crash, review RUNNING recovery and the outbox. The successful
engine progress ledger is authoritative for downloads, and the outbox for
handoffs. Review unrecorded orphan PDFs if the crash preceded progress save.

## Backups and upgrades

Stop the application cleanly before a coordinated snapshot. Back up `/data`
(PDFs and progress), `/config` (password hash, schedules and outbox), and the
deployment configuration. Back up `/profiles` only to an encrypted,
access-controlled destination because it contains live sessions. Exclude
profiles from routine shared-folder backups. `/browser` can be redownloaded.

Keep archive data and both SQLite databases in the same recovery generation.
Restoring old delivery state against current PDFs can cause another handoff.
Do a restore drill with scheduling disabled and consume unmounted first.
File permissions should be 0700 for profiles/config directories and 0600 for
SQLite files. Protect source PDFs and the data share from other writers.

Before upgrading, preserve a volume snapshot and the prior image digest.
Merge upstream into a review branch and run the provider/core/panel/server
regressions, including the browser privacy canary and container self-test.
Never merge upstream authentication or sandbox changes without review.
Rollback restores the matching image and matching volume snapshot together.

## Security boundaries

The password gate and Host/origin/frame checks protect every automation route.
The scheduler is a single-process service, and a second worker fails startup
before it can recover jobs. Never run multiple Uvicorn workers or replicas
against these profiles or databases. No shell command is accepted by the
scheduling API. Provider entry paths and import roots still come from the
trusted image. Scheduler settings contain cron/zone values and enum states,
not credentials. Scheduled raw subprocess output is discarded, and provider
file logging is disabled for scheduled work.

Existing supervised tools can produce private archive indexes, diagnostics
and local logs under upstream's rules. Do not publish them. Account aliases,
provider-install names, PDFs, browser profiles and private state are sensitive
even when central automation logs contain no account numbers. Protect the
dashboard with the same care as an authenticated bank browser.
