# Shelby County Trustee property tax downloader

Property tax receipts, one per payment, and the current tax notice while a balance is due, for one
parcel in Shelby County, Tennessee, from the Trustee's public lookup (apps2.shelbycountytrustee.com).

No sign-in exists on this site. Put the parcel ID from a tax bill into `config.json` as `parcel_id`.
Login just opens the parcel's page. The documents are built in the browser by the page itself when
its "Print Receipt" / "Print Notice" control is pressed, and the app keeps the PDF the page made and lets
nothing open or leave. Payment lives on a separate site that this app never reaches.

Read-only: the only controls pressed are a receipt row's "Print Receipt", the "Print Notice" button,
and the tables' NEXT button. Nothing persisted carries the parcel, the owner, a bill or receipt number,
or any page address. Tests: `python -m unittest discover -s tests` with PaperPull's bundled Python.
