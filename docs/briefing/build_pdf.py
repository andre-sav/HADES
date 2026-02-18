#!/usr/bin/env python3
"""Convert HADES briefing markdown + screenshots into a professional PDF."""

from pathlib import Path
from fpdf import FPDF

BRIEFING_DIR = Path(__file__).parent
MARGIN = 15
PAGE_W = 210  # A4 width mm
CONTENT_W = PAGE_W - 2 * MARGIN


class BriefingPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 6, "HADES - Lead Generation Platform  |  Prepared for Damione", align="L")
            self.cell(0, 6, f"Page {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(MARGIN, self.get_y(), PAGE_W - MARGIN, self.get_y())
            self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "Confidential - February 2026", align="C")


def add_section_title(pdf, title):
    """Add a styled section heading."""
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(40, 40, 60)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    # accent underline
    y = pdf.get_y()
    pdf.set_draw_color(99, 102, 241)  # indigo
    pdf.set_line_width(0.8)
    pdf.line(MARGIN, y, MARGIN + 50, y)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(6)


def add_subsection(pdf, title):
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(60, 60, 80)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def add_body(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(CONTENT_W, 5.5, text)
    pdf.ln(3)


def add_bullet(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    x = pdf.get_x()
    pdf.cell(6, 5.5, "-")
    pdf.multi_cell(CONTENT_W - 6, 5.5, text)
    pdf.ln(1)


def add_image(pdf, filename, caption=""):
    img_path = BRIEFING_DIR / filename
    if not img_path.exists():
        add_body(pdf, f"[Image not found: {filename}]")
        return
    # Check if we need a new page (image ~90mm tall + caption)
    if pdf.get_y() > 170:
        pdf.add_page()
    img_w = CONTENT_W
    pdf.image(str(img_path), x=MARGIN, w=img_w)
    if caption:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, caption, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)


def build():
    pdf = BriefingPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)

    # ── COVER PAGE ──
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(40, 40, 60)
    pdf.cell(0, 20, "HADES", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(99, 102, 241)
    pdf.cell(0, 10, "Lead Generation Platform", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "ZoomInfo-powered pipeline for vending services sales", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "Prepared for: Damione", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "February 18, 2026", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 6, "Confidential", align="C", new_x="LMARGIN", new_y="NEXT")

    # ── WHAT IS HADES ──
    pdf.add_page()
    add_section_title(pdf, "What Is HADES?")
    add_body(pdf,
        "HADES is a web-based tool that finds potential customers for our vending services "
        "business. It connects to ZoomInfo (a massive business contact database) to search for "
        "the right people at the right companies - then scores, organizes, and exports those "
        "leads so our sales team can start calling."
    )
    add_body(pdf,
        "Think of it as a smart funnel: millions of businesses go in, and only the contacts "
        "most likely to buy vending services come out."
    )

    # ── HOME SCREEN ──
    pdf.ln(3)
    add_section_title(pdf, "The Home Screen")
    add_image(pdf, "01_home.png", "HADES Dashboard - status, metrics, and recent activity at a glance")
    add_body(pdf, "This is the dashboard you see when you open HADES. At a glance you can see:")
    add_bullet(pdf, "Quick-action cards - Jump straight to Intent Search, Geography Search, or Export")
    add_bullet(pdf, "System status - Database connection, last run times, and whether leads are staged for export")
    add_bullet(pdf, "Key metrics - Weekly API credits used, total leads found, and number of operators in the system")
    add_bullet(pdf, "Recent runs - A log of every search run with timestamps, lead counts, and export status")

    # ── INTENT SEARCH ──
    pdf.add_page()
    add_section_title(pdf, "Two Ways to Find Leads")
    add_body(pdf,
        "HADES has two distinct search workflows, each designed for a different sales strategy."
    )
    add_subsection(pdf, "1. Intent Search - \"Who's actively looking for vending?\"")
    add_image(pdf, "02_intent.png", "Intent Workflow - find companies researching vending topics")
    add_body(pdf,
        "This workflow finds companies that are currently researching vending machines or "
        "breakroom solutions online. ZoomInfo tracks this \"buying intent\" - when a company's "
        "employees visit vending-related websites, read industry articles, or search for related terms."
    )
    add_body(pdf, "How it works:")
    add_bullet(pdf, "Pick topics (e.g., \"Vending Machines\") and signal strength (High/Medium)")
    add_bullet(pdf, "Set a target number of companies (default: 25)")
    add_bullet(pdf, "Hit Search Companies - HADES queries ZoomInfo's Intent API")
    add_bullet(pdf, "The system automatically finds the best contact at each company (managers, facility directors)")
    add_body(pdf,
        "Why it matters: These are warm leads - companies already thinking about vending. The weekly "
        "credit budget (500 credits) keeps costs controlled, and the system runs automatically every "
        "weekday morning at 7 AM."
    )

    # ── GEOGRAPHY SEARCH ──
    pdf.add_page()
    add_subsection(pdf, "2. Geography Search - \"Who's in this operator's territory?\"")
    add_image(pdf, "03_geography.png", "Geography Workflow - search by operator territory and ZIP radius")
    add_body(pdf,
        "This workflow finds contacts near a specific operator's service area using ZIP code "
        "radius searches. Unlike Intent, Geography searches have no credit cap - search as much "
        "as you need."
    )
    add_body(pdf, "How it works:")
    add_bullet(pdf, "Select an operator from the database (3,041 available)")
    add_bullet(pdf, "Enter a center ZIP code and radius (or paste a manual list of ZIP codes)")
    add_bullet(pdf, "HADES calculates all ZIP codes within that radius and queries ZoomInfo")
    add_bullet(pdf, "Contacts are filtered by industry, company size, and job title")
    add_bullet(pdf,
        "If the initial search doesn't hit the target count, the system automatically expands - "
        "adding management levels, broadening employee ranges, or increasing radius"
    )

    # ── OPERATORS ──
    pdf.add_page()
    add_section_title(pdf, "Operators - Your Sales Territory Database")
    add_image(pdf, "04_operators.png", "Operator management - 3,041 vending companies with contact details")
    add_body(pdf,
        "Operators are vending company owners - your potential customers or existing partners. "
        "HADES stores over 3,000 operators with their name, business name, phone, email, ZIP code "
        "(used as the center point for Geography searches), and team assignment."
    )
    add_body(pdf,
        "You can search, add, edit, or delete operators. The database syncs from Zoho CRM."
    )

    # ── EXPORT ──
    pdf.add_page()
    add_section_title(pdf, "Export - Getting Leads to the Sales Team")
    add_image(pdf, "05_export.png", "Export page - staged batches ready for VanillaSoft or CSV download")
    add_body(pdf,
        "Once leads are found and scored, they need to get into VanillaSoft (our call center software). "
        "The Export page shows all staged batches with lead counts and workflow type."
    )
    add_body(pdf, "Two export options:")
    add_bullet(pdf, "Push to VanillaSoft - Sends leads directly into VanillaSoft's queue via their API. One click, leads appear in the dialer.")
    add_bullet(pdf, "Download CSV - Generates a formatted CSV file with all 31 VanillaSoft fields for manual import.")
    add_body(pdf, "Each export can be tagged with an operator to track which territory the leads belong to.")

    # ── USAGE ──
    pdf.add_page()
    add_section_title(pdf, "Usage Dashboard - Budget at a Glance")
    add_image(pdf, "06_usage.png", "Usage tracking - weekly credit consumption with budget controls")
    add_body(pdf, "ZoomInfo charges per API credit, so we track every penny. The Usage Dashboard shows:")
    add_bullet(pdf, "This week's total credits used across both workflows")
    add_bullet(pdf, "Intent budget - credits used out of the 500 weekly cap, with a visual progress bar")
    add_bullet(pdf, "Geography credits - tracked separately (unlimited)")
    add_bullet(pdf, "Tabs for Weekly breakdown, By Period analysis, and Recent Query history")
    add_body(pdf, "The weekly cap and alert thresholds (50%, 80%, 95%) prevent accidental overspending.")

    # ── EXECUTIVE SUMMARY ──
    pdf.add_page()
    add_section_title(pdf, "Executive Summary - The Big Picture")
    add_image(pdf, "07_executive.png", "Executive Summary - month-to-date performance metrics and charts")
    add_body(pdf,
        "This is the page you'd show in a meeting. It answers \"how is lead generation going this month?\""
    )
    add_bullet(pdf, "118 leads exported this month at 0.84 credits per lead - that's efficiency")
    add_bullet(pdf, "Credit usage - 10 of 500 weekly intent credits used")
    add_bullet(pdf, "Geography activity - 5 searches, 34 leads found (no credit cap)")
    add_bullet(pdf, "Workflow comparison chart - Bar graph showing Geography vs. Intent volume")
    add_bullet(pdf, "Efficiency table - Credits per lead by workflow type")

    # ── AUTOMATION ──
    pdf.add_page()
    add_section_title(pdf, "Automation - Hands-Free Lead Generation")
    add_image(pdf, "09_automation.png", "Automation dashboard - scheduled runs, history, and configuration")
    add_body(pdf,
        "The Intent pipeline runs automatically on a schedule - Monday through Friday at 7:00 AM Eastern. "
        "No one needs to log in and click buttons."
    )
    add_body(pdf, "This page shows:")
    add_bullet(pdf, "Next scheduled run with countdown timer")
    add_bullet(pdf, "Last run results - status, timestamp, leads found")
    add_bullet(pdf, "Run History - Success/Failed badges with credit consumption")
    add_bullet(pdf, "Run Now button - Trigger an immediate run if you don't want to wait")
    add_bullet(pdf, "Configuration - Read-only view of the current search settings")

    # ── PIPELINE HEALTH ──
    pdf.add_page()
    add_section_title(pdf, "Pipeline Health - Is Everything Working?")
    add_image(pdf, "08_health.png", "Pipeline Health - system diagnostics with green/yellow/red indicators")
    add_body(pdf,
        "This is the system diagnostics page. Four health indicators show green/yellow/red status for:"
    )
    add_bullet(pdf, "Last Query - When was the last successful search?")
    add_bullet(pdf, "Cache - Are cached results fresh?")
    add_bullet(pdf, "Database - Is the Turso cloud database connected?")
    add_bullet(pdf, "ZoomInfo API - Is authentication valid?")
    add_body(pdf,
        "Below that, a Recent Pipeline Runs table shows every automated and manual run with timestamps, "
        "triggers, status badges, and details. If something breaks, this is where you look first."
    )

    # ── SUMMARY TABLE ──
    pdf.add_page()
    add_section_title(pdf, "Summary")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 240, 248)
    pdf.set_text_color(40, 40, 60)
    pdf.cell(55, 8, "  Capability", border=1, fill=True)
    pdf.cell(CONTENT_W - 55, 8, "  What It Does", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    rows = [
        ("Intent Search", "Finds companies actively researching vending - warm leads"),
        ("Geography Search", "Finds contacts near an operator's territory - territory coverage"),
        ("Scoring Engine", "Ranks leads by signal strength, proximity, and data freshness"),
        ("Operators", "3,000+ vending company database with CRM sync"),
        ("Export", "Push directly to VanillaSoft or download CSV"),
        ("Automation", "Daily scheduled searches with budget controls"),
        ("Usage Tracking", "Credit monitoring with weekly caps and alerts"),
        ("Health Monitoring", "Real-time status for database, API, and cache"),
    ]
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    for cap, desc in rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(55, 7, f"  {cap}", border=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(CONTENT_W - 55, 7, f"  {desc}", border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    add_body(pdf,
        "HADES turns a manual, time-consuming lead research process into an automated pipeline. "
        "The sales team gets scored, territory-assigned leads in VanillaSoft every morning without "
        "anyone touching the app."
    )

    # ── SECURITY NOTE ──
    pdf.ln(5)
    add_subsection(pdf, "Security")
    add_body(pdf,
        "The app is password-protected when deployed. Users must enter a password to access any page. "
        "Locally, it runs without a password for development convenience."
    )

    # ── OUTPUT ──
    out_path = BRIEFING_DIR / "HADES_Briefing.pdf"
    pdf.output(str(out_path))
    print(f"PDF generated: {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    build()
