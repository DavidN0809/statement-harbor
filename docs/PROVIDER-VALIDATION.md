# Provider readiness and authorized acceptance

The requested custom providers below are planned integrations tracked as repository issues.
There are no stub adapters or dashboard entries for unimplemented providers.
After the user signs in and completes MFA, each completed adapter must
automatically discover and download existing documents using the PaperPull
engine, then reuse the authorized session for scheduled collection. Expired
sessions must require human sign-in again. See the issues for acceptance criteria.
Public pages establish investigation evidence, not authenticated selectors.

## Implementation issues

The [project tracking issue](https://github.com/DavidN0809/statement-harbor/issues/7)
groups the following adapters and their shared acceptance requirements.

- [NCSECU: automatic document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/2)
- [SoFi: automatic document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/3)
- [FFSB-NC: mortgage document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/4)
- [Aqua Water: automatic bill collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/5)
- [Rutherford Electric: automatic bill collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/6)
- [Sallie Mae: automatic loan document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/8)
- [Voya: automatic document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/11)
- [Aetna: automatic insurance document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/12)
- [MyChart: organization-specific document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/13)
- [North Carolina Farm Bureau: automatic insurance document collection after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/15)
- [NCDMV: automatic collection of existing downloadable documents after manual sign-in](https://github.com/DavidN0809/statement-harbor/issues/16)

Voya requires confirmation of the actual product and servicing portal. Aetna
requires confirmation of the member plan/portal and chosen insurance document
categories. MyChart requires the healthcare organization's exact portal; clinical
PDFs are in scope only if the user explicitly opts in. North Carolina Farm Bureau
requires confirmation of the policy product and actual document portal, starting
from the [official site](https://www.ncfbins.com/) supplied by the user. NCDMV
requires establishing the official service portal and its actual downloadable
document capabilities. These issues do not claim live support. Insurance claims,
policy changes, medical messages/actions, DMV renewals/applications and payments
are outside read-only collection.

[Automatic Paperless ingestion](https://github.com/DavidN0809/statement-harbor/issues/14)
tracks completion and end-to-end validation of the existing consume-folder and
REST API implementations. It requires independent durable ingestion retries,
processing confirmation for API delivery, accurate consume handoff/uncertain
states, metadata, duplicate prevention and crash recovery. Real Paperless
processing remains an acceptance step; mocked requests alone do not establish it.

[Application user accounts](https://github.com/DavidN0809/statement-harbor/issues/9)
are tracked separately, including per-user provider, browser, document and
schedule isolation. The current shared dashboard password is not multi-user support.

[Secure remote-browser clipboard paste](https://github.com/DavidN0809/statement-harbor/issues/10)
tracks the reported inability to paste passwords from the local browser into
the VNC sign-in session. Pasted credentials must remain user-controlled and
ephemeral, with no logging, persistence or access from another user's session.

The GitHub fork is the working repository and issue tracker. `origin` points to
DavidN0809/statement-harbor and `upstream` remains rheeloaded/paperpull.

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
