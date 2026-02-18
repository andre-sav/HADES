#!/usr/bin/env python3
"""Convert HADES development complexity doc into a professional PDF."""

from pathlib import Path
from fpdf import FPDF

BRIEFING_DIR = Path(__file__).parent
MARGIN = 15
PAGE_W = 210
CONTENT_W = PAGE_W - 2 * MARGIN


class ComplexityPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 6, "HADES - Why Development Takes Time  |  For Damione", align="L")
            self.cell(0, 6, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
            self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "Confidential - February 2026", align="C")


def section(pdf, title):
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(40, 40, 60)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    y = pdf.get_y()
    pdf.set_draw_color(99, 102, 241)
    pdf.set_line_width(0.8)
    pdf.line(MARGIN, y, MARGIN + 50, y)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(6)


def subsection(pdf, title):
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(60, 60, 80)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def body(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(CONTENT_W, 5.5, text)
    pdf.ln(3)


def bullet(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(6, 5.5, "-")
    pdf.multi_cell(CONTENT_W - 6, 5.5, text)
    pdf.ln(1)


def bold_bullet(pdf, label, text):
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 50)
    x = pdf.get_x()
    pdf.cell(6, 5.5, "-")
    pdf.cell(pdf.get_string_width(label) + 1, 5.5, label)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(CONTENT_W - 6 - pdf.get_string_width(label) - 1, 5.5, text)
    pdf.ln(1)


def table(pdf, headers, rows, col_widths=None):
    if col_widths is None:
        col_widths = [CONTENT_W / len(headers)] * len(headers)
    # Header
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 248)
    pdf.set_text_color(40, 40, 60)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, f"  {h}", border=1, fill=True)
    pdf.ln()
    # Rows
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(50, 50, 50)
    for row in rows:
        max_h = 7
        for i, cell_text in enumerate(row):
            # Estimate if wrapping needed
            if pdf.get_string_width(cell_text) > col_widths[i] - 4:
                lines = max(1, int(pdf.get_string_width(cell_text) / (col_widths[i] - 4)) + 1)
                max_h = max(max_h, lines * 5)
        y_start = pdf.get_y()
        x_start = pdf.get_x()
        for i, cell_text in enumerate(row):
            pdf.set_xy(x_start + sum(col_widths[:i]), y_start)
            pdf.multi_cell(col_widths[i], 5, f"  {cell_text}", border=1, max_line_height=5)
        pdf.set_y(max(pdf.get_y(), y_start + max_h))
    pdf.ln(3)


def build():
    pdf = ComplexityPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)

    # ---- COVER ----
    pdf.add_page()
    pdf.ln(45)
    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(40, 40, 60)
    pdf.cell(0, 16, "Why HADES Takes Time", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 16, "to Build Right", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(99, 102, 241)
    pdf.cell(0, 8, "A look under the hood at what makes this project complex", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "For: Damione", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "February 18, 2026", align="C", new_x="LMARGIN", new_y="NEXT")

    # ---- SHORT VERSION ----
    pdf.add_page()
    section(pdf, "The Short Version")
    body(pdf,
        "HADES looks like \"a search tool with some buttons\" from the outside. Under the hood, "
        "it's a full-stack application that integrates with 7 external systems, manages messy "
        "real-world data, enforces budget controls, and runs automated pipelines on a schedule."
    )
    body(pdf,
        "Each of those things individually is straightforward. Combining them all into a reliable, "
        "production-grade tool is where the time goes."
    )

    # ---- BY THE NUMBERS ----
    pdf.ln(3)
    section(pdf, "By the Numbers")
    table(pdf, ["Metric", "Count"], [
        ["Lines of application code", "17,000"],
        ["Lines of test code", "7,500"],
        ["Total Python files", "54"],
        ["UI pages", "11"],
        ["Core backend modules", "22"],
        ["Automated tests", "551"],
        ["External API integrations", "7"],
        ["Git commits in 15 days", "67"],
        ["Session state variables", "70"],
        ["Error-handling blocks", "78"],
        ["Design/planning documents", "33"],
        ["UI component library", "2,452 lines (custom)"],
    ], col_widths=[90, 90])
    body(pdf,
        "This is not a weekend project. It's a production application with the scope of something "
        "a small team would build over months."
    )

    # ---- SEVEN SYSTEMS ----
    pdf.add_page()
    section(pdf, "Where the Time Actually Goes")
    subsection(pdf, "1. Seven External Systems That Don't Play Nice")
    body(pdf, "HADES doesn't just query one API. It talks to:")
    bullet(pdf, "ZoomInfo Contact Search - Find people at companies by location, industry, job title")
    bullet(pdf, "ZoomInfo Intent Search - Find companies showing buying signals")
    bullet(pdf, "ZoomInfo Contact Enrich - Fill in missing details (phone, email)")
    bullet(pdf, "VanillaSoft Web Leads API - Push leads directly into the call center dialer")
    bullet(pdf, "Zoho CRM - Sync operator database (3,041 records)")
    bullet(pdf, "Turso cloud database - Store everything persistently")
    bullet(pdf, "GitHub Actions - Run the intent pipeline automatically every weekday morning")
    pdf.ln(2)
    body(pdf, "Each integration requires:")
    bullet(pdf, "Authentication (OAuth tokens, API keys, JWT)")
    bullet(pdf, "Rate limiting and retry logic (ZoomInfo throttles at ~5 req/sec)")
    bullet(pdf, "Error handling for when the service is down or returns garbage")
    bullet(pdf, "Data format translation (JSON, XML, CSV - each speaks a different language)")
    bullet(pdf, "Testing with mocks (you can't run 551 tests against live APIs)")
    pdf.ln(2)
    body(pdf,
        "Real example: VanillaSoft's API accepts XML, not JSON. Every lead has to be translated "
        "from ZoomInfo's JSON format into 31 specific XML fields with exact naming conventions. "
        "If one field is wrong, the whole push silently fails. Building and testing that integration "
        "alone was a multi-day effort."
    )

    # ---- MESSY DATA ----
    pdf.add_page()
    subsection(pdf, "2. Real-World Data Is Messy")
    body(pdf,
        "ZoomInfo's data looks clean in their documentation. In practice, every field can arrive "
        "in unexpected formats. Every one of these has caused a bug:"
    )
    bullet(pdf, 'ZIP codes come back as "75201", "75201-1234", "752011234", or just "7520" (truncated)')
    bullet(pdf, "IDs switch between integers and strings across API responses")
    bullet(pdf, 'Scores arrive as "95%" (string with percent) instead of the number 95')
    bullet(pdf, "Phone numbers in every format: (512) 431-7769, 5124317769, +15124317769")
    bullet(pdf, "Names contain HTML entities: &amp; instead of &")
    bullet(pdf, "Fields that should always exist are sometimes null, missing, or empty strings")
    pdf.ln(2)
    body(pdf,
        "Every one of these required writing defensive code and tests. This isn't hypothetical - "
        "these are real issues we've hit and fixed in production data."
    )

    # ---- BUSINESS LOGIC ----
    subsection(pdf, "3. Complex Business Logic, Not Just CRUD")
    body(pdf, "This isn't a simple \"fetch data and display it\" app. The business logic includes:")
    bold_bullet(pdf, "Lead scoring engine - ",
        "Weighted scoring based on signal strength (50%), on-site likelihood (25%), "
        "and data freshness (25%). Configurable weights, multiple calculation rules.")
    bold_bullet(pdf, "Auto-expansion - ",
        "When a search doesn't hit the target, the system expands in priority order: management "
        "levels, employee range, accuracy threshold, then radius. Each runs a new API search and deduplicates.")
    bold_bullet(pdf, "ZIP radius math - ",
        "Haversine calculation against 42,000 US ZIP codes. Handles cross-state borders "
        "(e.g., Texarkana TX automatically includes Arkansas ZIPs).")
    bold_bullet(pdf, "Budget controls - ",
        "Weekly credit caps with alerts at 50%, 80%, 95%. Tracks credits across both workflows.")
    bold_bullet(pdf, "Deduplication - ",
        "One contact per company across multiple search expansions, handling mixed ID types.")

    # ---- FOUR WORKFLOWS ----
    pdf.add_page()
    subsection(pdf, "4. Four Workflow Paths, Not One")
    body(pdf, "The app has four distinct paths, each with its own state management and edge cases:")
    table(pdf,
        ["Workflow", "Mode", "Complexity"],
        [
            ["Intent", "Autopilot", "Fully automated decision-making"],
            ["Intent", "Manual", "User reviews each company before proceeding"],
            ["Geography", "Autopilot", "Auto-expansion, auto-dedup, auto-enrich"],
            ["Geography", "Manual", "User picks contacts per company, then confirms"],
        ],
        col_widths=[40, 35, 105],
    )
    body(pdf,
        "Each mode has its own step indicator, state management, UI flow, and edge cases. "
        "The step indicator alone manages 70 session state variables to track where the user is "
        "and what data has been loaded."
    )

    # ---- CUSTOM UI ----
    subsection(pdf, "5. The UI Is Custom-Built")
    body(pdf,
        "Streamlit provides basic widgets (buttons, tables, dropdowns). Everything that makes "
        "HADES look professional is custom-built:"
    )
    bullet(pdf, "2,452 lines of CSS injected as a design system (colors, spacing, shadows, animations)")
    bullet(pdf, "Custom components: metric cards, status badges, health indicators, progress bars, "
           "step indicators, styled tables with pill badges, labeled section dividers")
    bullet(pdf, "Dark mode design with consistent color tokens across 11 pages")
    body(pdf,
        "Off-the-shelf Streamlit apps look like gray boxes with default fonts. Making it look "
        "and feel like a real product takes significant design and implementation work."
    )

    # ---- TESTING ----
    subsection(pdf, "6. Testing Everything")
    body(pdf,
        "551 tests exist because every integration, data format edge case, and business rule "
        "needs verification. The test suite covers API response parsing, scoring calculations, "
        "ZIP radius math, export format validation, budget cap enforcement, deduplication logic, "
        "and error handling. Every code change runs all 551 tests to prevent regressions."
    )

    # ---- QUICK CHANGES TABLE ----
    pdf.add_page()
    section(pdf, "What \"Quick Changes\" Actually Cost")
    body(pdf, "Changes that sound small often aren't:")
    table(pdf,
        ["Request", "Sounds Like", "Actually Involves"],
        [
            ["Add a field to export", "5 minutes",
             "CSV mapping, XML template, validation, UI column, tests"],
            ["Change scoring weights", "1 minute",
             "Config, calibration page, regression tests, sort order validation"],
            ["Add a filter option", "10 minutes",
             "UI widget, API mapping, state mgmt, defaults, expansion interaction, tests"],
            ["Push to a new system", "An afternoon",
             "API client, auth, retry, data mapping, error handling, UI, tests, credentials"],
        ],
        col_widths=[40, 30, 110],
    )

    # ---- ICEBERG ----
    pdf.ln(3)
    section(pdf, "The Iceberg")
    subsection(pdf, "What you see:")
    bullet(pdf, "A dark-themed web app with nice cards and buttons")
    bullet(pdf, "A \"Search\" button that finds leads")
    bullet(pdf, "An \"Export\" button that sends them to VanillaSoft")
    pdf.ln(3)
    subsection(pdf, "What's underneath:")
    bullet(pdf, "17,000 lines of application code across 54 files")
    bullet(pdf, "7 API integrations with auth, retry, and error handling")
    bullet(pdf, "Scoring engine with configurable weights")
    bullet(pdf, "Auto-expansion algorithm with 4 fallback tiers")
    bullet(pdf, "ZIP radius math against 42,000 centroids")
    bullet(pdf, "Budget tracking with weekly caps and alerts")
    bullet(pdf, "Deduplication across multiple search expansions")
    bullet(pdf, "551 automated tests")
    bullet(pdf, "Automated daily pipeline with monitoring")
    bullet(pdf, "Custom design system (2,452 lines of CSS)")
    bullet(pdf, "State management across 70 session variables")
    bullet(pdf, "Data cleaning for every messy format ZoomInfo throws at us")

    # ---- BOTTOM LINE ----
    pdf.add_page()
    section(pdf, "Bottom Line")
    body(pdf,
        "HADES replaces what would be hours of manual work per day: logging into ZoomInfo, "
        "searching, filtering, copying data into spreadsheets, formatting for VanillaSoft, and "
        "uploading."
    )
    body(pdf,
        "Automating that reliably - with budget controls, quality scoring, deduplication, and "
        "error handling - is a serious engineering effort. The time investment is building a tool "
        "that runs itself and doesn't break when real-world data gets weird."
    )

    # ---- OUTPUT ----
    out = BRIEFING_DIR / "HADES_Development_Complexity.pdf"
    pdf.output(str(out))
    print(f"PDF generated: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    build()
