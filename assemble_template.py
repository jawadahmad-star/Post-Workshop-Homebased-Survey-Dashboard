#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stitch the four template fragments into `dashboard_template.html`.

The dashboard UI is kept in four editable pieces so no single file becomes
unwieldy; this joins them in order. `build_dashboard.py` then injects the data.

    _tpl_head.html   <head> + the whole stylesheet
    _tpl_body.html   <body> markup — header, filter bar, all 13 panels
    _tpl_js1.html    decryption, filters, aggregation, chart foundation
    _tpl_js2.html    panel renderers, tables, codebook

Run this only after editing a fragment. `update_dashboard` runs it for you.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = ["_tpl_head.html", "_tpl_body.html", "_tpl_js1.html", "_tpl_js2.html"]
OUT = "dashboard_template.html"


def main() -> int:
    chunks = []
    for name in PARTS:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            raise SystemExit(f"ERROR: template fragment missing: {name}")
        with open(path, "r", encoding="utf-8") as fh:
            chunks.append(fh.read().rstrip("\n"))

    body = "\n".join(chunks) + "\n"
    for marker in ("/*__PAYLOAD__*/", "__BUILD_STAMP__"):
        if marker not in body:
            raise SystemExit(f"ERROR: assembled template is missing {marker}")

    with open(os.path.join(HERE, OUT), "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"  assembled {OUT} from {len(PARTS)} fragments ({len(body)/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
