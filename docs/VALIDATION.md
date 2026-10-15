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
own test project and volumes. The final local image ID is
`sha256:c1caef5c846c4cc8cdad8cca29275a7bc090cee7ca2101c5c2503bec73c68ced`.
This is a local image ID, not a published registry digest.

No financial sites, real credentials, live account profiles, actual Paperless
instance, Home Assistant, Proton Bridge or homelab cluster were used. Real
provider authentication longevity and ingestion processing remain UNVERIFIED.
Kubernetes manifests were structurally checked, not deployed to the homelab.
See OPERATIONS.md and STATEMENT-HARBOR.md for remaining acceptance steps and
the deliberate UNCERTAIN state for ambiguous consume-folder handoffs.
