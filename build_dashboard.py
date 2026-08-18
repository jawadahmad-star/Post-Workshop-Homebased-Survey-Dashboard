#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
====================================================================================
 POST-WORKSHOP HOME-BASED WORKER SURVEY  —  DASHBOARD BUILDER
 Research Solutions (M&A Research Solutions LLC)  |  www.rs.org.pk
====================================================================================

 Reads the raw survey exports, joins them to the tracking roster, pulls the full
 question wording straight out of the SurveyCTO form definitions, and writes a
 single self-contained `index.html` with the whole labelled micro-dataset baked
 in as an encrypted blob.

   INPUTS  (all in the same folder as this script, names configurable below)
     • Post-workshop HBW Survey - Wife.dta          — wife survey, Stata (preferred)
     • Post-workshop HBW Survey - Husband.dta       — husband survey, Stata
     • Post-workshop HBW Survey - Wife_WIDE.csv     — CSV fallback if .dta missing
     • Post-workshop HBW Survey - Husband_WIDE.csv
     • postworkshop_roaster.xlsx                    — sampling frame / tracking sheet
     • *_Jul27.xlsx                                 — SurveyCTO XLSForms (question text)
     • dashboard_template.html                      — the UI shell

   OUTPUT
     • index.html   — the dashboard, ready to open or to publish

 The payload is encrypted with AES-GCM (PBKDF2-SHA256, 200k iterations) under the
 dashboard password, so the micro-data is not readable from the published source
 even though the page itself is a static file.

 Usage:  python build_dashboard.py            (build)
         python build_dashboard.py --plain    (build without encryption, for debugging)
====================================================================================
"""

from __future__ import annotations

import base64
import hashlib
import html as htmllib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

# The progress log uses arrows and bullets, which a default Windows console
# (cp1252) cannot encode -- a bare print() there raises UnicodeEncodeError and
# kills an otherwise finished build. Force UTF-8 on the streams instead.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# --------------------------------------------------------------------------------------
#  CONFIGURATION
# --------------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

DASHBOARD_PASSWORD = "PWHBW2026_RS"

FILES = {
    "wife_dta":      "Post-workshop HBW Survey - Wife.dta",
    "husb_dta":      "Post-workshop HBW Survey - Husband.dta",
    "wife_csv":      "Post-workshop HBW Survey - Wife_WIDE.csv",
    "husb_csv":      "Post-workshop HBW Survey - Husband_WIDE.csv",
    "roster":        "postworkshop_roaster.xlsx",
    "wife_form":     "Post-Workshop Home-Based Worker Survey - Wife_Jul27.xlsx",
    "husb_form":     "Post-workshop HBW Survey - Husband_Jul27.xlsx",
    "template":      "dashboard_template.html",
    "output":        "index.html",
}

# Fields never shipped to the browser: direct contact details and free-text identifiers.
DROP_ALWAYS = {
    "subscriberid", "simid", "devicephonenum", "username", "text_audit_file",
    "quiet_perc", "caseid", "deviceid", "no_mob_wallet", "account_holder",
    "easyload_card_photo", "formdef_version", "enum_other", "list_contacted_empl_count",
}

# --------------------------------------------------------------------------------------
#  PERSPECTIVE-NEUTRAL ANSWER LABELS
#
#  The two questionnaires are parallel forms, so a given code means the same thing
#  in both — but several lists word the option from the respondent's point of view.
#  On "who first raised the idea", code 1 reads "I did" to the wife and "Wife" to
#  the husband: the same answer, spelled two ways.
#
#  Comparing the printed labels therefore scored a couple who agreed perfectly as
#  disagreeing, and split one category into two bars on the wife/husband charts.
#  Re-labelling both forms from the code fixes the charts and the agreement scores
#  at once. Keyed by the XLSForm list name; lists whose wording already matches are
#  left alone.
# --------------------------------------------------------------------------------------

NEUTRAL_CHOICES = {
    "discuss_who": {
        1: "The wife", 2: "The husband", 3: "Parents or parents-in-law",
        4: "Other relatives", 99: "Someone else",
    },
    "notattend": {
        1: "She was not interested",
        2: "She was interested but could not go for family reasons",
        3: "The husband did not approve",
        4: "The family did not approve",
        5: "No family member could accompany her",
        6: "Does not remember",
        7: "She was not invited",
        99: "Other",
    },
    "job_offer": {
        1: "Yes, but she could not accept",
        2: "Yes, she accepted but never started",
        3: "Yes, she accepted and is working",
        4: "No",
        98: "Doesn't know",
    },
    "trip_company": {
        1: "Alone", 2: "With her husband", 3: "With another male family member",
        4: "With a female family member", 5: "With friends/coworkers",
        6: "With friends/others", 99: "Other",
    },
}


def apply_neutral_labels(choices: dict) -> None:
    """Rewrite a form's choice lists in place with the shared wording."""
    for listname, mapping in NEUTRAL_CHOICES.items():
        for item in choices.get(listname, []):
            if item["v"] in mapping:
                item["label"] = mapping[item["v"]]


# Multi-select variables: dummy-column prefix -> (choice list name in the XLSForm)
MULTISELECT = {
    "work_improvement":  "improved_work",
    "work_type":         "garment_functions",
    "source_opp":        "source",
    "discuss_family_who": "family_mem",
}

# Human names for the six enumerators, keyed off the roster/value-label codes.
UNKNOWN = "Not recorded"


# --------------------------------------------------------------------------------------
#  SMALL HELPERS
# --------------------------------------------------------------------------------------

def p(name: str) -> str:
    return os.path.join(HERE, FILES[name])


def log(msg: str) -> None:
    print(f"  {msg}")


def clean_text(raw) -> str:
    """Turn a SurveyCTO rich-text label into a single clean sentence."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return ""
    s = str(raw)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</p>|</div>|</li>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    s = s.replace(" ", " ").replace("⁠", "").replace("﻿", "")
    s = unicodedata.normalize("NFKC", s)
    # Stata exports mangle smart quotes into U+FFFD; put sensible characters back.
    s = s.replace("�", "'")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[•\-\*\s]+", "", s)
    return s


def to_num(v):
    """Coerce to a plain int/float, or None."""
    if v is None:
        return None
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if (np.isnan(v) or np.isinf(v)) else (int(v) if float(v).is_integer() else round(float(v), 4))
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "na", "none", "."}:
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else round(f, 4)
    except ValueError:
        return None


def jsonable(o):
    """Recursively make numpy/pandas types JSON-safe."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d %H:%M:%S")
    if o is pd.NaT:
        return None
    if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
        return None
    return o


# --------------------------------------------------------------------------------------
#  AREA NAME NORMALISATION
#  The roster's `area` column is free text typed in the field, so the same
#  neighbourhood shows up a dozen ways. Collapse it to a canonical set.
# --------------------------------------------------------------------------------------

#  Patterns are matched against the entry with all spaces and punctuation
#  stripped, so "Umer twn", "U Mer Town" and "Umar town" all collapse together.
#  Order matters — the first rule that hits wins.
AREA_RULES = [
    (r"^dh[a-z]*p",             "Dharampura"),           # dharampura / dhrampura / dhampura / dharumpur
    (r"chungi|nawab",           "Nawab Chowk / Chungi"),
    (r"^gla",                   "Glaxo Town"),           # glaxo town / glawo twn
    (r"anumroad",               "Anum Road"),
    (r"^u+[mn][ea]r",           "Umar Town"),            # umar / umer / uner / unar / uumer town
    (r"^y[ou]+h",               "Youhanabad"),           # yohanabad / youhanabad / yuhanabad / yohababad
]


def normalise_area(raw) -> str:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return UNKNOWN
    s = re.sub(r"[^a-z0-9]", "", str(raw).strip().lower())
    if not s:
        return UNKNOWN
    for pattern, canon in AREA_RULES:
        if re.search(pattern, s):
            return canon
    return re.sub(r"\s+", " ", str(raw).strip()).title()


# --------------------------------------------------------------------------------------
#  1.  SURVEYCTO FORM DEFINITIONS  →  full question text + choice lists
# --------------------------------------------------------------------------------------

def read_form(path: str) -> tuple[dict, dict]:
    """Return ({var: {text, type, list}}, {list_name: [{v, label}]}) from an XLSForm."""
    questions, choices = {}, {}
    if not os.path.exists(path):
        log(f"! form definition not found: {os.path.basename(path)}")
        return questions, choices

    survey = pd.read_excel(path, sheet_name="survey")
    label_col = "label:eng" if "label:eng" in survey.columns else "label"
    for _, r in survey.iterrows():
        name = r.get("name")
        qtype = str(r.get("type") or "").strip()
        if not isinstance(name, str) or not name.strip():
            continue
        if qtype.startswith(("begin ", "end ", "note", "calculate")):
            continue
        text = clean_text(r.get(label_col)) or clean_text(r.get("label"))
        if not text:
            continue
        listname = ""
        m = re.match(r"select_(one|multiple)\s+(\S+)", qtype)
        if m:
            listname = m.group(2)
        questions[name.strip()] = {
            "text": text,
            "type": qtype.split()[0] if qtype else "",
            "list": listname,
        }

    ch = pd.read_excel(path, sheet_name="choices")
    ch_label = "label:eng" if "label:eng" in ch.columns else "label"
    for ln, grp in ch.dropna(subset=["list_name"]).groupby("list_name", sort=False):
        items = []
        for _, r in grp.iterrows():
            v = to_num(r.get("value"))
            lab = clean_text(r.get(ch_label)) or clean_text(r.get("label"))
            if v is None or not lab:
                continue
            items.append({"v": v, "label": lab})
        if items:
            choices[str(ln).strip()] = items
    return questions, choices


# --------------------------------------------------------------------------------------
#  2.  SURVEY DATA  →  labelled records
# --------------------------------------------------------------------------------------

def read_survey(dta_path: str, csv_path: str, tag: str):
    """Load one survey. Returns (raw numeric frame, {var: {code: label}})."""
    if os.path.exists(dta_path):
        from pandas.io.stata import StataReader
        df = pd.read_stata(dta_path, convert_categoricals=False)
        with StataReader(dta_path) as rdr:
            vlabels = {
                var: {int(k): clean_text(v) for k, v in mapping.items()}
                for var, mapping in rdr.value_labels().items()
            }
        log(f"{tag}: {len(df)} records from {os.path.basename(dta_path)} "
            f"({len(vlabels)} labelled variables)")
        return df, vlabels

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = [c.strip().lower().replace("-", "").replace(" ", "_") for c in df.columns]
        log(f"{tag}: {len(df)} records from {os.path.basename(csv_path)} (CSV fallback — "
            f"value labels come from the form definition)")
        return df, {}

    raise SystemExit(f"ERROR: no data file found for {tag}. Looked for:\n"
                     f"  {dta_path}\n  {csv_path}")


def build_records(df: pd.DataFrame, vlabels: dict, questions: dict, choices: dict,
                  role: str, roster_by_couple: dict) -> list[dict]:
    """Convert one survey frame into a list of fully-labelled JSON records."""
    cols = set(df.columns)

    # Choice-list fallback for value labels the .dta didn't carry (CSV path).
    def label_for(var, code):
        if code is None:
            return None
        ln = questions.get(var, {}).get("list", "")
        # Shared wording wins over the form's own, so both rounds agree.
        if ln in NEUTRAL_CHOICES and code in NEUTRAL_CHOICES[ln]:
            return NEUTRAL_CHOICES[ln][code]
        if var in vlabels and code in vlabels[var]:
            return vlabels[var][code]
        for item in choices.get(ln, []):
            if item["v"] == code:
                return item["label"]
        return str(code)

    # Which variables are categorical (get a label) vs numeric (stay numbers)?
    categorical = set(vlabels.keys())
    for var, q in questions.items():
        if q["type"] in ("select_one",) and q["list"]:
            categorical.add(var)

    records = []
    for _, row in df.iterrows():
        rec: dict = {"_role": role}

        # ---- identifiers & admin -------------------------------------------------
        couple = str(row.get("couple_id_entry") or "").strip()
        hhd = str(row.get("hhd_id") or "").strip()
        rec["couple_id"] = couple
        rec["hhd_id"] = hhd

        # SurveyCTO writes the interview start/end as timestamps; the field day and
        # the realised interview length both come off them.
        start = pd.to_datetime(row.get("starttime"), errors="coerce")
        end = pd.to_datetime(row.get("endtime"), errors="coerce")
        subm = pd.to_datetime(row.get("submissiondate"), errors="coerce")
        rec["date"] = None if pd.isna(start) else start.strftime("%Y-%m-%d")
        rec["start"] = None if pd.isna(start) else start.strftime("%Y-%m-%d %H:%M")
        rec["hour"] = None if pd.isna(start) else int(start.hour)
        rec["submitted"] = None if pd.isna(subm) else subm.strftime("%Y-%m-%d %H:%M")

        dur = to_num(row.get("duration"))
        if dur is None and not pd.isna(start) and not pd.isna(end):
            dur = int((end - start).total_seconds())
        # Kept to two decimals: rounding each record to one first, then taking
        # a median across records, shifts the headline figure by a tenth.
        rec["duration_min"] = None if dur is None else round(dur / 60.0, 2)

        # Lag between finishing the interview and the form reaching the server —
        # a standard field-management signal.
        if not pd.isna(end) and not pd.isna(subm):
            rec["upload_lag_hr"] = round((subm - end).total_seconds() / 3600.0, 1)
        else:
            rec["upload_lag_hr"] = None

        def coord(col):
            v = row.get(col)
            try:
                f = float(v)
                return None if (np.isnan(f) or f == 0) else round(f, 6)
            except (TypeError, ValueError):
                return None

        lat, lon = coord("geo_2latitude"), coord("geo_2longitude")
        rec["gps"] = [lat, lon] if (lat is not None and lon is not None) else None
        rec["gps_ok"] = "Captured" if rec["gps"] else "Not captured"

        # ---- roster join ---------------------------------------------------------
        r = roster_by_couple.get(couple, {})
        rec["area"] = r.get("area", UNKNOWN)
        rec["sampletype"] = r.get("sampletype", UNKNOWN)
        rec["in_roster"] = "Matched to roster" if r else "Not in roster"
        rec["wife_name"] = r.get("wife_name", "")
        rec["husband_name"] = r.get("husband_name", "")

        # ---- every substantive variable -----------------------------------------
        for var in df.columns:
            if var in DROP_ALWAYS or var.startswith(("b_", "verify_", "upper_", "lower_")):
                continue
            if var in {"starttime", "endtime", "submissiondate", "duration", "time", "date",
                       "device_info", "key", "geo_2latitude", "geo_2longitude",
                       "geo_2altitude", "geo_2accuracy", "couple_id_entry", "hhd_id",
                       "datetime_1"}:
                continue
            if any(var.startswith(pre + "_") and var[len(pre) + 1:].isdigit()
                   for pre in MULTISELECT):
                continue  # handled as a group below
            if var in MULTISELECT or var.endswith("_99") and var[:-3] in MULTISELECT:
                continue

            val = row.get(var)
            if isinstance(val, str):
                val = val.strip()
                if val == "":
                    continue
                rec[var] = val
                continue

            code = to_num(val)
            if code is None:
                continue
            rec[var] = label_for(var, code) if var in categorical else code

        # ---- baseline verification flags ----------------------------------------
        for base, lab in (("match_name", "Name"), ("match_hname", "Spouse name"),
                          ("match_age", "Age"), ("match_years", "Years married"),
                          ("match_child", "Children")):
            if base in cols:
                code = to_num(row.get(base))
                rec[base] = ("Matches baseline" if code == 1
                             else "Does not match" if code == 2 else None)

        # ---- multi-select groups -------------------------------------------------
        for prefix, listname in MULTISELECT.items():
            picked = []
            for item in choices.get(listname, []):
                col = f"{prefix}_{item['v']}"
                if col in cols and to_num(row.get(col)) == 1:
                    picked.append(item["label"])
            if picked:
                rec[prefix] = picked

        # ---- derived time-use totals (hours) -------------------------------------
        def hm(hcol, mcol):
            h, m = to_num(row.get(hcol)), to_num(row.get(mcol))
            if h is None and m is None:
                return None
            return round((h or 0) + (m or 0) / 60.0, 2)

        rec["own_chores"] = hm("own_chores_hr", "own_chores_min")
        rec["own_care"] = hm("own_care_hr", "own_care_min")
        rec["sp_chores"] = hm("sp_chores_hr", "sp_chores_min")
        rec["sp_care"] = hm("sp_care_hr", "sp_care_min")
        rec["own_total"] = (None if rec["own_chores"] is None and rec["own_care"] is None
                            else round((rec["own_chores"] or 0) + (rec["own_care"] or 0), 2))
        rec["sp_total"] = (None if rec["sp_chores"] is None and rec["sp_care"] is None
                           else round((rec["sp_chores"] or 0) + (rec["sp_care"] or 0), 2))

        # ---- weekly home-based work load (wife only) -----------------------------
        d, h = to_num(row.get("current_work_days")), to_num(row.get("current_work_hrs"))
        rec["work_hours_week"] = None if (d is None or h is None) else d * h

        records.append({k: v for k, v in rec.items() if v is not None and v != ""})

    return records


# --------------------------------------------------------------------------------------
#  3.  ROSTER  →  sampling frame
# --------------------------------------------------------------------------------------

def read_roster(path: str) -> tuple[list[dict], dict]:
    if not os.path.exists(path):
        log(f"! roster not found: {os.path.basename(path)} — coverage panel will be empty")
        return [], {}

    df = pd.read_excel(path)
    rows, by_couple = [], {}
    for _, r in df.iterrows():
        couple = str(to_num(r.get("couple_id")) or "").strip()
        if not couple:
            continue
        rec = {
            "couple_id": couple,
            "hhd_id": str(to_num(r.get("hhd_id")) or ""),
            "wife_name": str(r.get("wife_name") or "").strip(),
            "husband_name": str(r.get("husband_name") or "").strip(),
            "wife_age": to_num(r.get("wife_age")),
            "husband_age": to_num(r.get("husband_age")),
            "yrs_marriage": to_num(r.get("yrs_marriage")),
            "n_child": to_num(r.get("n_child")),
            "n_young_child": to_num(r.get("n_young_child")),
            "area": normalise_area(r.get("area")),
            "area_raw": str(r.get("area") or "").strip(),
            "district": str(r.get("district") or "").strip() or UNKNOWN,
            "sampletype": str(r.get("sampletype") or "").strip() or UNKNOWN,
            "baseline_round": str(r.get("b_survey_round") or "").strip() or UNKNOWN,
            "endline": str(r.get("endline") or "").strip() or UNKNOWN,
            "endline_status": (str(r.get("endline_status")).strip()
                               if isinstance(r.get("endline_status"), str) else ""),
        }
        # Eligible frame = the couples the endline actually reached.
        rec["eligible"] = rec["endline"].lower().startswith("surveyed")
        rows.append(rec)
        by_couple[couple] = rec

    log(f"roster: {len(rows)} couples "
        f"({sum(1 for r in rows if r['eligible'])} surveyed for endline)")
    return rows, by_couple


# --------------------------------------------------------------------------------------
#  4.  META  —  headline figures computed once, server-side
# --------------------------------------------------------------------------------------

def build_meta(wife: list, husb: list, roster: list) -> dict:
    wc = {r["couple_id"] for r in wife if r.get("couple_id")}
    hc = {r["couple_id"] for r in husb if r.get("couple_id")}
    eligible = [r for r in roster if r["eligible"]]
    frame_ids = {r["couple_id"] for r in eligible}

    dates = sorted({r["date"] for r in wife + husb if r.get("date")})
    durs = [r["duration_min"] for r in wife + husb if r.get("duration_min")]
    enums = {r.get("enum_name") for r in wife + husb if r.get("enum_name")}

    both = wc & hc
    target_couples = len(frame_ids) or len(roster)

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    return {
        "generated": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "generated_iso": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_date": dates[-1] if dates else None,
        "first_date": dates[0] if dates else None,
        "field_days": len(dates),
        "n_wife": len(wife),
        "n_husband": len(husb),
        "n_interviews": len(wife) + len(husb),
        "n_couples_any": len(wc | hc),
        "n_couples_both": len(both),
        "n_couples_wife_only": len(wc - hc),
        "n_couples_husb_only": len(hc - wc),
        "target_couples": target_couples,
        "target_interviews": target_couples * 2,
        "roster_total": len(roster),
        "roster_eligible": len(eligible),
        "roster_not_surveyed": len(roster) - len(eligible),
        "pct_couples": pct(len(both), target_couples),
        "pct_interviews": pct(len(wife) + len(husb), target_couples * 2),
        "pct_wife": pct(len(wife), target_couples),
        "pct_husband": pct(len(husb), target_couples),
        "median_duration": round(float(np.median(durs)), 1) if durs else None,
        "mean_duration": round(float(np.mean(durs)), 1) if durs else None,
        "min_duration": round(min(durs), 1) if durs else None,
        "max_duration": round(max(durs), 1) if durs else None,
        "n_enums": len(enums),
        "n_areas": len({r["area"] for r in roster}),
        "areas_reached": len({r.get("area") for r in wife + husb
                              if r.get("area") and r["area"] != UNKNOWN}),
        "remaining_couples": max(target_couples - len(both), 0),
    }


# --------------------------------------------------------------------------------------
#  5.  ENCRYPTION  —  AES-256-GCM under PBKDF2-SHA256(password)
#      Mirrors exactly what the page does with WebCrypto on unlock.
# --------------------------------------------------------------------------------------

PBKDF2_ITERATIONS = 200_000


def encrypt_payload(plaintext: bytes, password: str) -> dict:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return {}

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, 32)
    blob = AESGCM(key).encrypt(iv, plaintext, None)
    b64 = base64.b64encode
    return {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iter": PBKDF2_ITERATIONS,
        "salt": b64(salt).decode(),
        "iv": b64(iv).decode(),
        "ct": b64(blob).decode(),
    }


# --------------------------------------------------------------------------------------
#  MAIN
# --------------------------------------------------------------------------------------

def main() -> int:
    plain_mode = "--plain" in sys.argv

    print("\n" + "=" * 78)
    print("  POST-WORKSHOP HBW SURVEY  —  building dashboard")
    print("=" * 78)

    log("reading form definitions …")
    q_wife, ch_wife = read_form(p("wife_form"))
    q_husb, ch_husb = read_form(p("husb_form"))
    apply_neutral_labels(ch_wife)
    apply_neutral_labels(ch_husb)
    log(f"neutral wording applied to {len(NEUTRAL_CHOICES)} perspective-dependent lists")

    log("reading roster …")
    roster, roster_by_couple = read_roster(p("roster"))

    log("reading survey data …")
    df_w, vl_w = read_survey(p("wife_dta"), p("wife_csv"), "wife")
    df_h, vl_h = read_survey(p("husb_dta"), p("husb_csv"), "husband")

    wife = build_records(df_w, vl_w, q_wife, ch_wife, "Wife", roster_by_couple)
    husb = build_records(df_h, vl_h, q_husb, ch_husb, "Husband", roster_by_couple)

    meta = build_meta(wife, husb, roster)

    payload = {
        "meta": meta,
        "roster": roster,
        "wife": wife,
        "husband": husb,
        "questions": {"wife": q_wife, "husband": q_husb},
        "choices": {"wife": ch_wife, "husband": ch_husb},
    }

    raw = json.dumps(jsonable(payload), ensure_ascii=False, separators=(",", ":"))
    log(f"payload: {len(raw) / 1024:.0f} KB "
        f"({meta['n_wife']} wife + {meta['n_husband']} husband records, "
        f"{meta['n_couples_both']} complete couples)")

    template_path = p("template")
    if not os.path.exists(template_path):
        raise SystemExit(f"ERROR: template not found: {template_path}")
    with open(template_path, "r", encoding="utf-8") as fh:
        template = fh.read()

    if plain_mode:
        blob = {"v": 0, "plain": base64.b64encode(raw.encode("utf-8")).decode()}
        log("encryption: OFF (--plain)")
    else:
        blob = encrypt_payload(raw.encode("utf-8"), DASHBOARD_PASSWORD)
        if blob:
            log(f"encryption: AES-256-GCM, PBKDF2 × {PBKDF2_ITERATIONS:,}")
        else:
            blob = {"v": 0, "plain": base64.b64encode(raw.encode("utf-8")).decode()}
            log("! `cryptography` not installed — payload embedded unencrypted.")
            log("!   run:  pip install cryptography     then rebuild")

    marker = "/*__PAYLOAD__*/"
    if marker not in template:
        raise SystemExit("ERROR: template is missing the /*__PAYLOAD__*/ marker")
    out = template.replace(marker, json.dumps(blob, separators=(",", ":")))
    out = out.replace("__BUILD_STAMP__", meta["generated"])

    out_path = p("output")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(out)

    print("-" * 78)
    print(f"  BUILT  →  {out_path}   ({os.path.getsize(out_path) / 1024:.0f} KB)")
    print(f"  Field days {meta['field_days']} · last activity {meta['last_date']}")
    print(f"  {meta['n_interviews']} interviews · {meta['n_couples_both']} couples with both spouses "
          f"· {meta['pct_couples']}% of the {meta['target_couples']}-couple frame")
    print("=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
