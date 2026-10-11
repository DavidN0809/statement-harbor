# Optum Bank HSA statement and tax-form downloader

Mapped against a signed-in account on 2026-10-09. Read-only, delete-safe, part of PaperPull. You
sign in yourself (HealthSafe ID) in the browser PaperPull opens on the port named in config.json (see config.example.json); the tool attaches
afterwards and never handles credentials.

Nothing is ever clicked. Statements and tax forms are plain links on the member site,
account.optumbank.com: the six newest statements are links, the older ones are the options of the
page's date selector, and tax forms (5498-SA, and the 1099-SA in a year with distributions) are links
on the same page. Each is fetched by its own address with the signed-in session.

Built on an account with one HSA. More than one product (a second HSA, an FSA, an HRA or an
investment account) has not been tried. Each product whose statements the Forms & documents page
links is read, and a list the app cannot read stops rather than being called whole. If you have more
than one, please run Diagnose and open an issue.

Never touched: payments, reimbursements, contributions, investments, cards, claims, beneficiaries,
settings, the HSA forms (rollover, correction, closure...). Tests: `python -m unittest discover -s
tests` from this folder with PaperPull's bundled Python.
