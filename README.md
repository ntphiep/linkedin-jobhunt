# LinkedIn Job Hunt

Score LinkedIn job postings against **your actual CV** and export a spreadsheet that tells you where to apply.

Keyword filters tell you a posting mentions Python. This tells you whether you would survive the screen, whether you can legally take the job from where you live, and what you are missing.

## Install

```
/plugin marketplace add ntphiep/linkedin-jobhunt
/plugin install linkedin-jobhunt@ntphiep-plugins
```

Requires a [HarvestAPI](https://harvest-api.com) key:

```
export HARVESTAPI_API_KEY=your_key
```

## First run

Build your profile from your CV. This step is required. The plugin ships with no personal data.

```
python skills/linkedin-jobhunt/scripts/build_profile.py your_cv.pdf \
       --linkedin https://www.linkedin.com/in/your-handle
```

Reads PDF, DOCX, TXT or MD. Extracts skills, years of experience, certifications and industry background. Proficiency is inferred from where a skill appears: listed under skills *and* repeated in your work history counts as proficient; mentioned once counts as familiar.

Then:

```
/jobhunt
```

## Scoring

Each posting is scored out of 100 across four pillars, each answering a different question.

| Pillar | Points | Question |
|---|---|---|
| Skill match | 0-30 | Does the required stack overlap what you have shipped |
| Seniority fit | 0-25 | With your years of experience, do you clear the screen |
| Reachability | 0-30 | From where you live, can you actually take this job |
| Role fit | 0-15 | Does it move you toward your target role |

Skill match measures **coverage**, not raw count. Matching 10 of 20 required technologies scores lower than matching 7 of 8.

Heavy penalties apply to postings that require work authorization you do not have, demand a seniority level well above yours, name a missing technology in the title itself, or come from bulk recruiter spam.

The verdict column says what to do: apply now, review, consider. Anything below the threshold is dropped from the output.

## Output

Two sheets.

**Opportunities** is grouped by how recently the posting went up, then ordered by region, work arrangement and score. Each row shows which of your skills matched, the coverage ratio, what is missing, and any blockers found in the description.

**Overview** breaks the results down by region, role group and work arrangement, with a chart and a ranked list of which of your skills the market asks for most.

## Configuration

| File | Contents |
|---|---|
| `taxonomy.json` | Technology vocabulary, scoring weights, market signals, seniority patterns |
| `config.json` | Search queries and LinkedIn geo IDs |
| `profile.json` | Your profile, generated, git-ignored |

To target different roles, edit `config.json` and the role patterns in `scripts/score.py`.

## Privacy

`profile.json` holds personal data and is git-ignored. This repository contains the tooling, not anyone's CV.

## License

MIT
