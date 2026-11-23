"""VITRO design-system values for Excel output (openpyxl).

Source: VITRO design system (claude.ai/artifact/UBDmvNqfp3bg7WHjLa9EvX),
project/api/tokens.md and components/DataTable. Tables use Consolas, a cobalt
header row with white text, row-alt alternating rows, border rules, square
corners. Status goes in its own cell: label text in the status colour on its
-10 fill. Never colour a header row or a whole row.
"""
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

COBALT = "00006E"
INK = "1A1A2E"
INK_MUTED = "5A5A6E"
SURFACE = "F5F6F8"
ROW_ALT = "EEEEF7"
BORDER = "D1D1D1"
WHITE = "FFFFFF"

STATUS = {  # label colour, fill
    "green": ("1E6B45", "E3F1E9"),
    "amber": ("A35F00", "FBF0DC"),
    "red": ("B3261E", "FBE8E6"),
}

# Rating / verdict label -> status accent (None = neutral, no accent)
RATING_STATUS = {
    "Comply": "green",
    "Pass": "green",
    "Go": "green",
    "Partial": "amber",
    "Clarify": "amber",
    "Unverified": "amber",
    "Needs review": "amber",
    "Conditional Go": "amber",
    "Insufficient evidence": "amber",
    "Insufficient data": "amber",
    "Gap": "red",
    "Fail": "red",
    "No-Go": "red",
    "Partner scope": None,
    "N/A": None,
}

MONO = "Consolas"
SANS = "Aptos"
DISPLAY = "Aptos Display"

_side = Side(style="thin", color=BORDER)
GRID = Border(left=_side, right=_side, top=_side, bottom=_side)


def header_row(ws, row, ncols, height=30):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=MONO, bold=True, color=WHITE, size=10)
        cell.fill = PatternFill("solid", fgColor=COBALT)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = GRID
    ws.row_dimensions[row].height = height


def body_cell(cell, alt=False, numeric=False, bold=False):
    cell.font = Font(name=MONO, size=10, color=INK, bold=bold)
    cell.fill = PatternFill("solid", fgColor=ROW_ALT if alt else SURFACE)
    cell.alignment = Alignment(
        vertical="top", wrap_text=True, horizontal="right" if numeric else "left"
    )
    cell.border = GRID


def status_cell(cell, label):
    """Apply a status accent to one cell (label text on its -10 fill)."""
    key = RATING_STATUS.get(label)
    if not key:
        return
    fg, fill = STATUS[key]
    cell.font = Font(name=MONO, size=10, bold=True, color=fg)
    cell.fill = PatternFill("solid", fgColor=fill)


def title(ws, text, eyebrow=None, row=1):
    """Eyebrow (cobalt caps, bold) above a sheet title (Aptos Display, ink)."""
    if eyebrow:
        c = ws.cell(row=row, column=1, value=eyebrow.upper())
        c.font = Font(name=SANS, bold=True, color=COBALT, size=9)
        row += 1
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(name=DISPLAY, bold=True, color=INK, size=16)
    ws.row_dimensions[row].height = 24
    return row + 1


def source_line(ws, row, text, col=1):
    c = ws.cell(row=row, column=col, value=text)
    c.font = Font(name=SANS, italic=True, size=9, color=INK_MUTED)
    c.alignment = Alignment(wrap_text=False)


def note(ws, row, text, col=1, bold=False, size=10):
    c = ws.cell(row=row, column=col, value=text)
    c.font = Font(name=SANS, size=size, color=INK, bold=bold)
    c.alignment = Alignment(wrap_text=False, vertical="top")
    return c


def sheet_base(ws):
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = COBALT
    # Print: landscape, fit all columns to one page width, repeat nothing else
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
