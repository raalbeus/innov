#!/usr/bin/env python3
"""Fill the VITRO inter-office memo template with a Go/No-Go summary.

Usage: build_memo.py memo.json OUT.docx [--template templates/VITRO_Memo_Template.docx]

Keeps the template's letterhead, header block, footer, form number and
INTERNAL watermark. Replaces the body with the summary and the sections
in memo.json (see references/schema.md). Tables have four columns and reuse
the template's table formatting (Aptos 9pt, cobalt header, row-alt rows).
"""
import argparse
import copy
import json
import os

import docx
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

import vitro_style as vs

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "..", "templates", "VITRO_Memo_Template.docx")


def set_par_text(p_el, text):
    """Keep the first run's formatting, drop the other runs, set text."""
    runs = p_el.findall(qn("w:r"))
    for r in runs[1:]:
        p_el.remove(r)
    if not runs:
        r = OxmlElement("w:r")
        p_el.append(r)
        runs = [r]
    r = runs[0]
    for t in r.findall(qn("w:t")):
        r.remove(t)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    return r


def set_cell(tc, text, status=None):
    ps = tc.findall(qn("w:p"))
    for p in ps[1:]:
        tc.remove(p)
    r = set_par_text(ps[0], "" if text is None else str(text))
    if status:
        key = vs.RATING_STATUS.get(status)
        if key:
            fg, fill = vs.STATUS[key]
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                tcPr = OxmlElement("w:tcPr")
                tc.insert(0, tcPr)
            shd = tcPr.find(qn("w:shd"))
            if shd is None:
                shd = OxmlElement("w:shd")
                tcPr.append(shd)
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), fill)
            rPr = r.find(qn("w:rPr"))
            if rPr is None:
                rPr = OxmlElement("w:rPr")
                r.insert(0, rPr)
            for tag in ("w:color", "w:b"):
                old = rPr.find(qn(tag))
                if old is not None:
                    rPr.remove(old)
            b = OxmlElement("w:b")
            rPr.append(b)
            c = OxmlElement("w:color")
            c.set(qn("w:val"), fg)
            rPr.append(c)


def left_align(tc):
    for p in tc.findall(qn("w:p")):
        pPr = p.find(qn("w:pPr"))
        if pPr is not None:
            jc = pPr.find(qn("w:jc"))
            if jc is not None:
                pPr.remove(jc)


def _child(parent, tag, first=False):
    el = parent.find(qn(tag))
    if el is None:
        el = OxmlElement(tag)
        if first:
            parent.insert(0, el)
        else:
            parent.append(el)
    return el


def keep_next(p_el):
    pPr = p_el.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        p_el.insert(0, pPr)
    if pPr.find(qn("w:keepNext")) is None:
        pPr.insert(0, OxmlElement("w:keepNext"))


def row_props(tr, header=False):
    trPr = _child(tr, "w:trPr", first=True)
    if trPr.find(qn("w:cantSplit")) is None:
        trPr.append(OxmlElement("w:cantSplit"))
    if header and trPr.find(qn("w:tblHeader")) is None:
        trPr.append(OxmlElement("w:tblHeader"))


def set_widths(tbl, fractions):
    grid = tbl.find(qn("w:tblGrid"))
    cols = grid.findall(qn("w:gridCol"))
    total = sum(int(c.get(qn("w:w"))) for c in cols)
    ws = [int(total * f / sum(fractions)) for f in fractions]
    for c, w in zip(cols, ws):
        c.set(qn("w:w"), str(w))
    for tr in tbl.findall(qn("w:tr")):
        for tc, w in zip(tr.findall(qn("w:tc")), ws):
            tcW = _child(_child(tc, "w:tcPr", first=True), "w:tcW", first=True)
            tcW.set(qn("w:w"), str(w))
            tcW.set(qn("w:type"), "dxa")


def build_table(proto, spec):
    tbl = copy.deepcopy(proto)
    trs = tbl.findall(qn("w:tr"))
    head, body_a, body_b = trs[0], trs[1], trs[2] if len(trs) > 2 else trs[1]
    for tr in trs[1:]:
        tbl.remove(tr)
    row_props(head, header=True)
    for tc, h in zip(head.findall(qn("w:tc")), spec["headers"]):
        set_cell(tc, h)
        for p in tc.findall(qn("w:p")):
            keep_next(p)
    sc = spec.get("status_col")
    for i, row in enumerate(spec["rows"]):
        tr = copy.deepcopy(body_a if i % 2 == 0 else body_b)
        for j, (tc, v) in enumerate(zip(tr.findall(qn("w:tc")), row)):
            left_align(tc)  # text columns; the template right-aligns its figure column
            set_cell(tc, v, status=v if j == sc else None)
        row_props(tr)
        tbl.append(tr)
    if spec.get("widths"):
        set_widths(tbl, spec["widths"])
    return tbl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("memo")
    ap.add_argument("out")
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    a = ap.parse_args()
    m = json.load(open(a.memo))
    d = docx.Document(a.template)
    body = d.element.body
    els = [e for e in body.iterchildren() if e.tag != qn("w:sectPr")]
    # Template order: title p, IOM p, header tbl, blank p, summary p, heading p, body p, tbl, source p, ...
    iom_p, header_tbl = els[1], els[2]
    summary_p, heading_p, body_p, table_proto, source_p = els[4], els[5], els[6], els[7], els[8]
    protos = {k: copy.deepcopy(v) for k, v in
              dict(summary=summary_p, heading=heading_p, body=body_p, table=table_proto, source=source_p).items()}

    # IOM number: keep label run, replace the number run(s)
    runs = iom_p.findall(qn("w:r"))
    num_runs = [r for r in runs if "O000000" in "".join(r.itertext()) or "BDI-" in "".join(r.itertext())]
    if num_runs:
        set_par_text_runs = num_runs[0]
        for t in set_par_text_runs.findall(qn("w:t")):
            set_par_text_runs.remove(t)
        t = OxmlElement("w:t")
        t.text = m.get("iom_number", "[IOM number]")
        set_par_text_runs.append(t)
        for r in num_runs[1:]:
            iom_p.remove(r)

    # Header block
    vals = [m.get("date"), m.get("to"), m.get("endorsed_by"), m.get("from"), m.get("subject")]
    for tr, v in zip(header_tbl.findall(qn("w:tr")), vals):
        tcs = tr.findall(qn("w:tc"))
        set_cell(tcs[1], v or "")

    # Clear body after the blank paragraph
    for e in els[4:]:
        body.remove(e)
    sect = body.find(qn("w:sectPr"))

    def add(el):
        sect.addprevious(el)

    p = copy.deepcopy(protos["summary"])
    set_par_text(p, m["summary"])
    add(p)
    for s in m.get("sections", []):
        h = copy.deepcopy(protos["heading"])
        set_par_text(h, s["heading"])
        keep_next(h)
        add(h)
        for para in s.get("paragraphs", []):
            b = copy.deepcopy(protos["body"])
            set_par_text(b, para)
            if s.get("table"):
                keep_next(b)
            add(b)
        if s.get("table"):
            add(build_table(protos["table"], s["table"]))
            src = copy.deepcopy(protos["source"])
            set_par_text(src, s["table"].get("source", "Source: [named source]."))
            add(src)
        for para in s.get("after", []):
            b = copy.deepcopy(protos["body"])
            set_par_text(b, para)
            add(b)
    d.save(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
