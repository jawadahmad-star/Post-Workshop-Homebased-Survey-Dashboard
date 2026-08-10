# Post-Workshop Home-Based Worker Survey — Live Dashboard

Fieldwork monitoring and analysis dashboard for the Post-Workshop Home-Based Worker
Survey (Lahore, Pakistan). Built by **Research Solutions** (M&A Research Solutions LLC),
[www.rs.org.pk](https://www.rs.org.pk).

**Live site:** <https://postworkshop-hbw.rs.org.pk>

---

## Daily update — the only thing you normally need to do

1. Export the two fresh files from SurveyCTO into **this folder**, keeping the same names:
   - `Post-workshop HBW Survey - Wife.dta`
   - `Post-workshop HBW Survey - Husband.dta`

   (`..._WIDE.csv` files work too — they are used automatically if the `.dta` is missing.)

2. Double-click **`update_dashboard.bat`**.

That rebuilds the dashboard from the new data and pushes it to the live site, which
refreshes about a minute later. The script tells you exactly what it did, and says so
plainly if something went wrong.

The most common failure is a data file still open in Stata or Excel — close it and run again.

---

## What the dashboard covers

Thirteen sections, all reading from the same filtered dataset:

| Section | What it answers |
|---|---|
| **Overview** | Where the round stands against the 301-couple tracking frame |
| **Field Operations** | Pace, output per enumerator, interview length, working day |
| **Data Quality** | The five baseline identity checks, interview conditions, open flags |
| **Couple Tracker** | Every couple in the frame, wife/husband interview status, searchable and exportable |
| **Home-Based Work** | The wife's current garment work — hours, earnings, effective hourly pay |
| **Outside Work** | The job-search funnel from willingness through to a job offer |
| **Discussion & Concerns** | Whether the couple has discussed outside work, and what each side says the objections are |
| **Workshop Follow-up** | Attendance at the May workshop and what followed |
| **Mobility & Agency** | Trips outside the home, who she goes with, who decides |
| **Time Use** | Unpaid work, self-reported against spouse-reported |
| **Financial Access** | Bank account, phone and mobile-wallet ownership |
| **Spousal Agreement** | The flagship check — do the two independent interviews tell the same story? |
| **Data Explorer** | Chart any variable, browse the records, and read the full codebook |

A global filter bar (field day · enumerator · area · sample type) drives **every** chart,
KPI and table on every section at once.

Every chart carries the verbatim question wording from the SurveyCTO form, and can be
downloaded as a PNG or as the CSV of the numbers behind it.

---

## Access and data protection

The dashboard is password-protected, and the protection is real rather than cosmetic.

The survey micro-data is embedded in `index.html` **encrypted with AES-256-GCM**, under a
key derived from the password with PBKDF2-SHA256 (200,000 iterations). The password is not
stored anywhere in the page — entering it *is* what decrypts the data, in your browser.
Someone who views the page source without the password sees only ciphertext.

The raw exports (`.dta`, `.csv`, `.xlsx`) are excluded by `.gitignore` and are **never**
committed. They stay on the field-office machine. This is deliberate: publishing them would
undo the encryption entirely.

> Because of that, a fresh clone of this repository can serve the dashboard but cannot
> rebuild it. Rebuilding needs the source data files, which live only on the machine that
> runs the daily update.

---

## How it fits together

```
  SurveyCTO exports (.dta / .csv)  ─┐
  postworkshop_roaster.xlsx        ─┤
  SurveyCTO form definitions (.xlsx)┘
                │
                ▼
        build_dashboard.py       reads, labels, joins to the roster,
                │                encrypts, injects into the template
                ▼
           index.html            one self-contained file — the whole dashboard
                │
                ▼
      GitHub Pages → postworkshop-hbw.rs.org.pk
```

### Files

| File | Purpose |
|---|---|
| `update_dashboard.bat` | **The daily script.** Rebuilds and publishes. Double-click it. |
| `build_dashboard.py` | Reads the data, applies all labels, encrypts, writes `index.html` |
| `assemble_template.py` | Joins the four UI fragments into `dashboard_template.html` |
| `_tpl_head.html` | `<head>` and the complete stylesheet |
| `_tpl_body.html` | Page markup — header, filter bar, all 13 sections |
| `_tpl_js1.html` | Decryption, filtering, aggregation, chart foundation |
| `_tpl_js2.html` | Section renderers, tables, codebook |
| `index.html` | The built dashboard (generated — do not edit by hand) |
| `CNAME` | Custom domain for GitHub Pages |

To change the **look or wording**, edit the relevant `_tpl_*.html` fragment and run
`update_dashboard.bat` — it re-assembles the template before rebuilding.

To change the **data handling**, edit `build_dashboard.py`.

### Labels come from the questionnaire, not from hand-typed lists

Question wording and answer options are read directly from the SurveyCTO form definitions
(`*_Jul27.xlsx`) and the Stata value labels. Nothing is transcribed by hand, so when the
questionnaire changes the dashboard follows it automatically.

Neighbourhood names in the tracking sheet are free text and arrive in dozens of spellings
(`Umar town`, `Umer twn`, `U mer town`, …). `normalise_area()` in `build_dashboard.py`
collapses them into six canonical areas. If a new area appears, add a rule there.

---

## One-time setup on a new machine

1. Install [Python 3](https://www.python.org/downloads/), ticking **"Add python.exe to PATH"**.
2. Install [Git](https://git-scm.com/download/win) and sign in to GitHub.
3. Put the survey exports, the roster and the two form definitions in this folder.
4. Run `update_dashboard.bat`. It installs the Python packages it needs on first run.

---

*Confidential — for the study team only.*
