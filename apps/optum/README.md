# Optum Bank HSA statements and tax forms

Downloads the monthly statements of your Optum Bank health savings account
and its tax forms, the 5498-SA and, in a year with distributions, the
1099-SA, as PDFs. This reads from a browser where you sign in yourself,
through HealthSafe ID, on the port named in `config.json` (see
`config.example.json`). Passwords and verification codes are never handled
by the downloader.

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull optum diagnose`, then `paperpull optum pilot`.
5. Check the downloaded documents before using `paperpull optum all`.

## How it works

Nothing is ever clicked. Statements and tax forms are plain links on the
member site, `account.optumbank.com`. The Forms & documents page links each
product's latest statement, which is how the app learns the products. On a
product's statements page the six newest statements are links, the older
ones are the options of the page's date selector, and the tax forms are
links. Each is fetched by its own address with the signed-in session, and
a list the app cannot read stops rather than being called whole.

## Validation status

Mapped against a signed-in account on 2026-10-09 by its contributor, whose
full run saved 21 statements and the 5498-SA. That account has one HSA.
More than one product, a second HSA, an FSA, an HRA or an investment
account, has not been tried. Each product whose statements the Forms &
documents page links is read. If you have more than one, please run
Diagnose and open an issue.

Never touched are payments, reimbursements, contributions, investments,
cards, claims, beneficiaries, settings and the HSA forms, such as rollover,
correction and closure.

## Tests

```
python -m pytest tests -q
```

Run from this folder with PaperPull's bundled Python. They use invented
values only and need no browser.
