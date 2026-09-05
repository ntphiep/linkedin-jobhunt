---
description: Run the full LinkedIn job hunt pipeline and export the spreadsheet
---

Run the `linkedin-jobhunt` skill end to end with these arguments: $ARGUMENTS

Pipeline: collect postings, merge and deduplicate, fetch full descriptions,
score against the CV in profile.json, export a two-sheet spreadsheet.

If profile.json does not exist yet, build it first:
`python skills/linkedin-jobhunt/scripts/build_profile.py <path to CV>`
