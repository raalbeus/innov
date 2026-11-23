#!/usr/bin/env python3
"""Extract a bid package into per-page text and images, and locate key sections.

Usage: extract_bid.py OUT_DIR FILE.pdf [FILE.pdf ...]

For each PDF:
  OUT_DIR/<doc>/text/p001.txt   text layer of each page (may be empty)
  OUT_DIR/<doc>/img/p001.png    rendered image of each page with little or no text
                                (scanned pages); read these visually
Writes OUT_DIR/manifest.md (human/Claude-readable) and OUT_DIR/manifest.json.

The manifest lists, per document: type guess, page count, which pages are
scanned, and the pages where key bid terms appear (Bid Data Sheet, SLCC,
ABC, delivery, data center terms). Scanned pages have no hits; they must
be read from the images.
"""
import json
import os
import re
import shutil
import subprocess
import sys

MIN_TEXT_CHARS = 80  # below this a page is treated as scanned
DPI = 110

LOCATORS = {
    "Bid Data Sheet (BDS)": r"Bid Data Sheet",
    "Schedule of Requirements (Sec VI)": r"Schedule of Requirements",
    "Technical Specifications (Sec VII)": r"Technical Specifications",
    "SLCC / similar contract": r"Single Largest Completed Contract|SLCC|similar contract|similar to the Project",
    "ABC": r"Approved Budget for the Contract|\bABC\b",
    "NFCC / credit line": r"\bNFCC\b|Net Financial Contracting Capacity|committed line of credit",
    "Delivery period": r"calendar days from|delivery schedule|Delivery Period|Notice to Proceed",
    "Deadline / bid opening": r"deadline|submission and receipt of bids|opening of bids|on or before",
    "Colocation": r"co-?location|rack space|\bracks?\b|\bcage\b",
    "DR seats / office": r"DR seats?|work.?area recovery|seats?\b|office space|command cent",
    "Connectivity": r"Dedicated Internet|\bDIA\b|\bMPLS\b|bandwidth|\bGbps\b|\bMbps\b|cross.?connect|SD-?WAN|IP address",
    "Facility rating": r"TIA-?942|Uptime|\bTier\s*(III|IV|3|4)\b|Rated-?\s*[34]",
    "ISO / certifications": r"\bISO\b|PCI.?DSS|SOC ?2|accredit",
    "Personnel": r"certified|Project Manager|Engineers?\b|personnel",
    "Bulletin amendment": r"Bid Bulletin|Supplemental|amend",
}


def doc_type(name, first_text):
    n = (name + " " + first_text[:2000]).lower()
    if "bulletin" in n or "supplemental" in n:
        return "Bid Bulletin / SBB"
    if "clarification" in n:
        return "Bidder clarification letter"
    if "annex" in n or "technical specification" in n[:400] or "terms of reference" in n:
        return "TOR / Annex"
    if "invitation to bid" in n or "bid data sheet" in n or "philippine bidding documents" in n:
        return "Bidding documents (PBD)"
    return "Other"


def slug(name):
    base = os.path.splitext(os.path.basename(name))[0]
    s = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return s[:60] or "doc"


def page_texts(path):
    """Return list of page texts. Prefer pdftotext -layout (keeps tables readable)."""
    if shutil.which("pdftotext"):
        try:
            out = subprocess.run(
                ["pdftotext", "-layout", path, "-"], capture_output=True, check=True
            ).stdout.decode("utf-8", "replace")
            pages = out.split("\f")
            if pages and pages[-1].strip() == "":
                pages = pages[:-1]
            return pages
        except Exception:
            pass
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return [(p.extract_text(layout=True) or "") for p in pdf.pages]
    except Exception:
        from pypdf import PdfReader

        return [(p.extract_text() or "") for p in PdfReader(path).pages]


def render(path, pages, out_dir):
    """Render the given 1-based pages to PNG. Returns list of written files."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        for p in pages:
            img = pdf[p - 1].render(scale=DPI / 72).to_pil()
            f = os.path.join(out_dir, f"p{p:03d}.png")
            img.save(f)
            written.append(f)
        return written
    except ImportError:
        pass
    if shutil.which("pdftoppm"):
        for p in pages:
            prefix = os.path.join(out_dir, f"p{p:03d}")
            subprocess.run(
                ["pdftoppm", "-r", str(DPI), "-png", "-singlefile", "-f", str(p), "-l", str(p), path, prefix],
                check=True,
            )
            written.append(prefix + ".png")
        return written
    try:
        from pdf2image import convert_from_path

        for p in pages:
            img = convert_from_path(path, dpi=DPI, first_page=p, last_page=p)[0]
            f = os.path.join(out_dir, f"p{p:03d}.png")
            img.save(f)
            written.append(f)
    except ImportError:
        sys.stderr.write("No PDF renderer found (pypdfium2, pdftoppm or pdf2image). Scanned pages not rendered.\n")
    return written


def compact(pages):
    """[1,2,3,7,8] -> '1-3, 7-8'"""
    if not pages:
        return "-"
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        out.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = p
    out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    manifest = []
    for path in sys.argv[2:]:
        name = os.path.basename(path)
        d = slug(name)
        texts = page_texts(path)
        tdir = os.path.join(out, d, "text")
        os.makedirs(tdir, exist_ok=True)
        scanned = []
        hits = {k: [] for k in LOCATORS}
        for i, t in enumerate(texts, start=1):
            with open(os.path.join(tdir, f"p{i:03d}.txt"), "w", encoding="utf-8") as fh:
                fh.write(t)
            if len(re.sub(r"\s", "", t)) < MIN_TEXT_CHARS:
                scanned.append(i)
                continue
            for k, rx in LOCATORS.items():
                if re.search(rx, t, re.I):
                    hits[k].append(i)
        imgs = render(path, scanned, os.path.join(out, d, "img")) if scanned else []
        manifest.append(
            {
                "file": name,
                "doc": d,
                "type": doc_type(name, texts[0] if texts else ""),
                "pages": len(texts),
                "scanned_pages": scanned,
                "images": [os.path.relpath(f, out) for f in imgs],
                "hits": hits,
            }
        )

    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    lines = ["# Bid package manifest", ""]
    for m in manifest:
        lines += [
            f"## {m['file']}",
            f"- Folder: `{m['doc']}/`  Type (guess): **{m['type']}**  Pages: {m['pages']}",
            f"- Scanned pages (read from `{m['doc']}/img/`): {compact(m['scanned_pages'])}"
            + ("  **ALL PAGES SCANNED: read visually**" if len(m["scanned_pages"]) == m["pages"] else ""),
            "- Term hits by page (text pages only):",
        ]
        for k, v in m["hits"].items():
            if v:
                lines.append(f"  - {k}: {compact(v)}")
        lines.append("")
    with open(os.path.join(out, "manifest.md"), "w") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
