# Validation record

Upstream baseline: `9f0fd44d34cd2dba9c944601f1ee07d933bd2c87`, cloned on
2026-10-15. Testing uses Python 3.13 on Windows, the versions pinned in
`server/requirements.txt`, pytest 9.1.1 and Playwright Chromium build 1243.

| Check | Result |
| --- | --- |
| Frozen upstream server baseline | 99 passed |
| Frozen upstream Ally baseline, isolated process | 124 passed |
| Frozen upstream Nelnet baseline, isolated process | 43 passed |
| All 78 repository suites | 24,230 passed, 348 skipped, 2 server-title assertions failed before the branding assertions were updated |
| Complete GUI rerun after correcting branding assertions | 751 passed, 8 platform skips |
| Latest scheduler, wrapper, OS lock, outbox and server checks on Windows | 150 passed |
| Latest Linux container automation/API/outbox/deployment checks | 79 passed |
| Latest runner dependency-selection regression tests | 87 passed |
| Explicit privacy canary rerun | 82 passed |
| Real browser dashboard interactions and manifest checks | 3 passed |
| Ruff on modified runtime Python files | Passed |
| Compose configuration | Passed |
| Tracked-source Docker build | Passed, linux/amd64, `statement-harbor:dev` |
| Final container smoke/self-test | Passed, including Chrome namespace sandbox and seccomp |

The two failures in the broad run were expectations of the upstream server
title after the fork was renamed. The complete GUI suite was rerun and passed.
All provider suites in that broad run passed, including Ally and Nelnet. The
full 78-suite runner was not repeated after the targeted fixes and additions.
The skipped cases are upstream platform limitations and provider-shape
exclusions, and the privacy canary did run. One test-client dependency emits
a Starlette deprecation warning about httpx, without a test failure.

The Docker smoke test started a fresh Compose project, chose a synthetic
password, checked unauthenticated/authenticated routes, created a synthetic
provider configuration and ran the container self-test. Chrome
155.0.8059.79 ran with its namespace sandbox and seccomp active. The test checked
that VNC was not reachable outside the container. It then removed only its
own test project and volumes. The Milestone 1/2 local image ID was
`sha256:c1caef5c846c4cc8cdad8cca29275a7bc090cee7ca2101c5c2503bec73c68ced`.
This is a local image ID, not a published registry digest.

No financial sites, real credentials, live account profiles, actual Paperless
instance, Home Assistant, Proton Bridge or homelab cluster were used. Real
provider authentication longevity and ingestion processing remain UNVERIFIED.
Kubernetes manifests were structurally checked, not deployed to the homelab.
See OPERATIONS.md and STATEMENT-HARBOR.md for remaining acceptance steps and
the deliberate UNCERTAIN state for ambiguous consume-folder handoffs.


## Advanced integration implementation validation

The continuation implements Paperless API delivery, optional Bridge triggers,
Home Assistant intervention notices, publication-cycle expectations, bounded
publication retries and historical backfill. No LLM SDK, model calls or AI-service
runtime was added.

- Broad Windows GUI/server/core integration run: 899 passed, 8 platform skips,
  one route-test fixture initialization failure. The fixture was corrected;
  the route/automation/browser/server rerun passed all 291 checks.
- Latest focused Windows API, outbox, integration and deployment checks: 37 passed.
- Linux production-image runtime checks: 104 passed. An earlier expanded test
  invocation also selected build-context tests that require Git, which is
  intentionally absent from the runtime image. Those build tests passed on the
  Windows development host; the Linux runtime selection excludes them.
- Isolated existing Ally suite: 124 passed. Nelnet: 43 passed.
- Real browser dashboard check passed, including archive-expectation edits.
- Docker build and smoke/self-test passed with namespace sandbox and seccomp on.
- REST-only Compose configuration and actual `kubectl kustomize deploy` rendering
  passed. The rendered Deployment has no consume PVC dependency and mounts its
  integration configuration and secret references read-only.
- Source lint passed. The pinned integration diff fe93dae0..495b67c3 completed
  source-backed security review with no reportable findings. This is limited to
  that change set, with no real provider or homelab penetration testing. A later
  two-line mail-folder validation guard and local-onboarding Compose example were
  separately inspected and tested as ordinary implementation changes.

A persistent local onboarding container is started separately from the temporary
smoke project, using deploy/compose.local.yaml. It has no Paperless mount or token:
this does not establish real ingestion. The configured homelab Kubernetes API was
unreachable during read-only discovery, so no cluster resources were modified.
NCSECU, SoFi and FFSB require actual authenticated portal implementation and
are tracked as planned work. No stub providers are shipped. The project must
not be described as fully operational for those providers.

## Interactive paste (GitHub issue #10)

The manual paste path was checked with 40 focused API/browser tests and 157
existing route, frame-policy and server-browser checks. A disposable Linux
container exercised actual sandboxed Chrome with synthetic password, Unicode,
multiline and embedded-frame inputs. It verified refusal for unfocused,
disabled, read-only, wrong-profile and untrusted-host targets, no form submit,
and no persistent test-text leaks. No real profiles or credentials were used.

This adds manual paste support; provider implementation and real-account
acceptance remain tracked separately in PROVIDER-VALIDATION.md.

The expanded GUI/server/outbox run passed 922 tests with eight platform skips.
Its sole initial failure was an existing documentation punctuation rule. The
sentence was corrected and all 14 documentation checks then passed. The rebuilt
Docker image passed fresh setup, authentication, provider setup and the runtime
self-test, including namespace sandbox, seccomp and private VNC checks. The
actual CLI helper also passed synthetic insertion and silent refusal checks.
