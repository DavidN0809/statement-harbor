# Provider readiness and authorized acceptance

New document portals cannot be implemented honestly from public marketing pages.
`paperpull_core.pending_providers` provides a consistent, fail-closed adapter
boundary and product inventory. All its operations stop before interacting with
a page. These entries are **disabled placeholders, not working download adapters**.
They are visible in Automation and cannot be installed as runnable templates.
Do not report Milestone 3 or the full project definition of done as achieved yet.

## Evidence gathered on 2026-10-15

| Provider | Established by official sources | Still unverified |
| --- | --- | --- |
| NCSECU | [Member Access](https://www.ncsecu.org/services/member-access) links to memberaccess.ncsecu.org, supports multiple accounts and requires user MFA. The [new portal](https://www.ncsecu.org/member-access) has an interactive migration/setup flow. | Authenticated document list, per-account cycles, tax tabs, PDF actions, portal access restrictions and restart persistence |
| SoFi Banking | [Statements guidance](https://support.sofi.com/hc/en-us/articles/33259996847629-When-will-I-get-my-Checking-and-Savings-statement) describes monthly PDFs generally within five business days, accessed through Banking/Statements. | Current DOM, per-account identity, PDF request semantics, MFA/challenge behavior and session reuse |
| SoFi Loans | [Official product site](https://www.sofi.com/) lists multiple loan products. | Which products the user has, servicing hosts, document interfaces and existing PDFs; Banking behavior must not be assumed |
| FFSB-NC mortgage | [Public eStatements page](https://www.ffsb-nc.com/estatements/) advertises eighteen months of account statements. Public online-banking links use ffsbnc.myebanking.net. | Whether this serves the user's mortgage; mortgage statements, 1098s and escrow documents are not established by the public page. No servicing host is enabled |
| Aqua | [Public site](https://www.aquawater.com/) links to aquaeportal.com. | Existing downloadable bills and read-only navigation |
| Rutherford Electric | [Public site](https://www.remc.com/) links to rutherfordbillpay.remc.com. | Existing downloadable bills and read-only navigation |

Public pages are evidence for portal investigation only. No forms, enrollment,
agreements, payment controls or account changes were submitted during research.
SoFi's business developer APIs are not an authenticated consumer-document API.

## Required validation before adding runnable templates

1. Confirm Ally Bank versus Ally Auto and identify each SoFi product. Retain the
   existing Ally Bank and Nelnet adapters unchanged until their actual account
   types and servicing portals are established. Nelnet's federal-student-loan
   statements, notices and 1098-E support remains intact.
2. In PaperPull's private interactive browser, the user signs in and handles MFA,
   agreements or enrollment themselves. The application must not accept them.
3. Inspect only the actual document area. Establish exact trusted hosts, safe
   document-control labels, account enumeration, pagination, period filtering,
   PDF download behavior and expected document identity. Do not commit DOM dumps,
   account details, screenshots, profiles, documents or tokens.
4. Clone the closest established statement provider as described in
   [adding-a-provider.md](adding-a-provider.md). Implement the site layer with
   observed selectors, preserving the shared engine, URL guards and safe controls.
   Banking and loan servicing logic must be separate where the portals differ.
5. Build synthetic DOM/PDF fixtures that preserve structure while replacing every
   private value. Test two accounts, two documents with the same date, all relevant
   types, auth expiration, challenge detection and control guards. Assert payment,
   transfer, enrollment, agreement and settings controls are always refused.
6. Run an authorized pilot. Privately check document identity and PDF contents,
   rerun to prove skips, restart the container, and test real session reuse. If
   authentication recurs, show AUTH_REQUIRED and stop; never claim unattended
   support beyond the provider's session policy.
7. Test actual Paperless processing, failed ingestion recovery and HA notices on
   synthetic PDFs before scheduling real collection. Validate Bridge trusted
   authentication headers with an intentionally spoofed test message.
8. Enable only the validated product/account. Record the acceptance date and
   limitations. A portal whose restrictions disallow automation remains disabled.
