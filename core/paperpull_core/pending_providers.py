"""Fail-closed adapter boundaries awaiting authorized portal validation.

These are deliberately not runnable PaperPull templates. Public marketing
pages cannot establish statement selectors, account enumeration or PDF identity.
Promote each product to apps/ only after completing docs/PROVIDER-VALIDATION.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .urls import is_safe_url


@dataclass(frozen=True)
class FinancialDocument:
    account_key: str  # safe internal key, never a full account number
    document_type: str
    period: str
    provider_id: str
    date: str


class Adapter(Protocol):
    def authenticated_status(self, page) -> str: ...
    def navigate_documents(self, page) -> None: ...
    def discover(self, page) -> list[FinancialDocument]: ...
    def accounts(self, page) -> list[str]: ...
    def download(self, page, document: FinancialDocument, destination) -> bool: ...


class UnverifiedProvider(RuntimeError):
    def __init__(self):
        super().__init__("UNVERIFIED: authorized document-portal validation required")


@dataclass(frozen=True)
class PendingAdapter:
    slug: str
    name: str
    website: str
    products: tuple[str, ...]
    documents: tuple[str, ...]
    documented_hosts: tuple[str, ...] = ()
    verification: str = "UNVERIFIED"
    enabled: bool = False

    def safe_url(self, url):
        return is_safe_url(url, self.documented_hosts, subdomains=False)

    def authenticated_status(self, page):
        # Never infer READY from the absence of a login form. No authenticated
        # document-list proof exists until a real session has been examined.
        return "PAUSED"

    def navigate_documents(self, page):
        raise UnverifiedProvider()

    def discover(self, page):
        raise UnverifiedProvider()

    def accounts(self, page):
        raise UnverifiedProvider()

    def download(self, page, document, destination):
        raise UnverifiedProvider()


PROVIDERS = (
    PendingAdapter("ncsecu", "NCSECU", "https://www.ncsecu.org/",
                   ("Checking", "Savings", "Credit Card", "Loan", "Mortgage"),
                   ("Statement", "Tax Form", "Notice"), ("memberaccess.ncsecu.org",)),
    PendingAdapter("sofi-banking", "SoFi Banking", "https://www.sofi.com/",
                   ("Checking", "Savings"), ("Statement", "Tax Form"), ("www.sofi.com",)),
    PendingAdapter("sofi-loans", "SoFi Loans", "https://www.sofi.com/",
                   ("Personal Loan", "Student Loan", "Refinance"), ("Statement", "Tax Form", "Notice")),
    PendingAdapter("ffsb-nc", "First Federal Savings Bank of Lincolnton", "https://www.ffsb-nc.com/",
                   ("Mortgage",), ("Statement", "Form 1098", "Escrow Analysis", "Payment History", "Notice")),
    PendingAdapter("aqua", "Aqua Water", "https://www.aquawater.com/", ("Utility",), ("Bill",)),
    PendingAdapter("rutherford-electric", "Rutherford Electric", "https://www.remc.com/", ("Utility",), ("Bill",)),
)
