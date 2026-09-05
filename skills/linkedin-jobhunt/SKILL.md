---
name: linkedin-jobhunt
description: "Score LinkedIn job postings against the user's CV and export a spreadsheet of where to apply"
---

# LinkedIn Job Hunt

Find postings the candidate can realistically win, not the largest possible pile.
Every row in the spreadsheet must answer one question: is this worth applying to,
and why.

## Scope

Three role families only. Everything else is dropped, not down-ranked:

1. Data Engineer (incl. Cloud Data, Analytics, ETL Engineer)
2. Cloud / DevOps Engineer (incl. Platform Engineer, SRE, Infrastructure)
3. Python Developer (secondary, considered only when the first two are thin)

The gate lives in `scripts/score.py:role_group_of` and uses regex, not substring
matching. Substring matching once killed a posting titled
`Data Engineer | $90/hr Remote` because `hr ` matched `$90/hr`.

## Setup

`profile.json` is generated from the candidate's CV and is git-ignored.

```
python scripts/build_profile.py <cv.pdf> --linkedin <profile url>
```

Never hand-write it. A hand-written version once invented 15 technologies the CV
never mentioned, which shifted 55 of 57 scores by an average of 12.5 points.

## Pipeline

```
python fetch.py jobs  <dir>/jobs  --posted-limit 24h --max 25
python fetch.py posts <dir>/posts --posted-limit 24h --max 20 --pages 2
python merge_dedup.py <dir>/jobs  <dir>/merged_jobs.json  24
python merge_dedup.py <dir>/posts <dir>/merged_posts.json 24
python enrich.py <dir>/merged_jobs.json <dir>/enriched_jobs.json --limit 70
python score.py  <dir>/enriched_jobs.json <dir>/scored_jobs.json  --kind job
python score.py  <dir>/merged_posts.json  <dir>/scored_posts.json --kind post
python export.py <dir>/scored_jobs.json <dir>/scored_posts.json out.xlsx
```

Prefer the `linkedin` MCP server over `fetch.py` when it is available; always pass
`save_dir` so responses land on disk instead of in the conversation.

`enrich.py` is mandatory. Search results carry no job description, and without a
description the skill-match pillar is always zero.

## Scoring

Four pillars out of 100: skill match 30, seniority fit 25, reachability 30,
role fit 15. Skill match measures coverage of what the posting asks for, not a
raw count of matches.

`export.py:can_apply` is a hard gate, not a penalty. It drops postings that
require work authorization the candidate lacks, sit far above their level, or
need relocation. Scoring these low is not enough: a posting that says
"US citizenship" has no business appearing in the sheet at all.

## Output

Twelve columns, sorted by score descending. No merged cells, because merged rows
break Excel's own sort and filter.

## Gotchas

- HarvestAPI returns 403 for urllib's default User-Agent. `fetch.py` and
  `enrich.py` set one explicitly.
- LinkedIn rounds applicant counts to 25 and caps them at 200. Neither value is
  a real signal.
- Run Python with `PYTHONIOENCODING=utf-8` on Windows.
