# Coinbase statements and tax documents

Downloads your Coinbase monthly account statements and your tax documents
as PDFs, from a browser where you sign in yourself. Passwords and
verification codes are never handled by the downloader. Contributed by
[@JasperDale420](https://github.com/JasperDale420).

Read-only, delete-safe, part of [PaperPull](../../README.md).

## Setup and use

1. Run `setup.command` (macOS) or `setup.bat` (Windows).
2. Copy `config.example.json` to `config.json` and set your local output folder.
3. Run `login.command` / `login.bat` and sign in yourself. Leave the window open.
4. Run `paperpull coinbase diagnose`, then `paperpull coinbase pilot`.
5. Check the downloaded documents before using `paperpull coinbase all`.

The sign-in browser uses port 9286, as `config.example.json` says. Existing
download history is retained in the provider's local state files. Deleting a
downloaded file does not reset that history.

## What it saves

Both pages are on `accounts.coinbase.com`, and the app opens each by its
address.

- **Monthly statements.** The Statements page lists one statement for each
  complete month back to the account's first. Each is saved by pressing its
  row's own PDF button once, on a page loaded afresh for it, and the
  download is taken only from Coinbase's statements host. The saved PDF has
  to name its own month more plainly than the month before or after, or it
  is not filed under that month. The "Last 30 days" row is not a statement
  and is skipped.
- **Tax documents.** The 1099-DA and the other tax forms for every year since
  the account's first transaction, and the pregenerated gain and loss PDF
  reports, read from the list calls the Taxes page makes and fetched from
  Coinbase's tax forms host. Nothing is pressed there, so the page's own
  mark-read and mark-downloaded calls never happen. Each is kept under its
  own id from that list.

The statements list is called whole only when it reaches back to the month
of the account's first transaction, and a tax list that names another year
or has a page this does not read stops the listing too.

Never touched are the custom statement generator, the tax report generator,
and anything that trades, sends, stakes or changes a setting.

## Validation status

Mapped against a signed-in retail account on 2026-10-09. A full run there
saved 66 statements and 2 tax documents, every one a valid PDF. Automated
tests cover the guard, the hosts, the statement rows and their months, the
tax lists, the press of a statement's PDF button and what it brings, and
filing a statement only under its own month.
