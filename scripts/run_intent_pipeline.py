#!/usr/bin/env python3
"""
Automated Intent Pipeline — Daily Search + Email CSV.

Runs the Intent Workflow Autopilot headlessly: intent search → score → contact
search → enrich → export → email.  Reuses all existing HADES modules directly.

Usage:
    python scripts/run_intent_pipeline.py              # Full run + email
    python scripts/run_intent_pipeline.py --dry-run    # Validate config, no API calls
    python scripts/run_intent_pipeline.py --no-email   # Run pipeline, skip email
    python scripts/run_intent_pipeline.py --verbose    # Debug logging

Cron setup (daily at 6:00 AM):
    0 6 * * * cd /Users/boss/Projects/HADES && python scripts/run_intent_pipeline.py >> logs/intent-pipeline.log 2>&1
"""

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Prevent Streamlit from auto-launching
os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")

from turso_db import TursoDatabase
from zoominfo_client import (
    ZoomInfoClient,
    IntentQueryParams,
    ContactQueryParams,
    DEFAULT_ENRICH_OUTPUT_FIELDS,
)
from scoring import score_intent_leads, score_intent_contacts, get_priority_label
from dedup import dedupe_leads
from export import export_leads_to_csv
from export_dedup import get_previously_exported, filter_previously_exported
from expand_search import build_contacts_by_company
from cost_tracker import CostTracker
from utils import get_call_center_agents, get_sic_codes, get_employee_minimum, get_employee_maximum

logger = logging.getLogger("intent_pipeline")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(config: dict, creds: dict, dry_run: bool = False,
                 trigger: str = "scheduled", db=None) -> dict:
    """Execute the full intent pipeline.

    Returns:
        {success, csv_content, csv_filename, batch_id, summary, error}
    """

    summary = {
        "topics": config["topics"],
        "signal_strengths": config["signal_strengths"],
        "target_companies": config["target_companies"],
        "intent_results": 0,
        "scored_results": 0,
        "companies_selected": 0,
        "contacts_found": 0,
        "contacts_enriched": 0,
        "contacts_exported": 0,
        "dedup_filtered": 0,
        "credits_used": 0,
        "expansions": [],
        "top_leads": [],
    }

    if dry_run:
        logger.info("Dry run — validating config and module imports only")
        return {"success": True, "csv_content": None, "csv_filename": None,
                "batch_id": None, "summary": summary, "error": None}

    # --- Init clients (use provided db or create new) ---
    if db is None:
        db = TursoDatabase(url=creds["TURSO_DATABASE_URL"],
                           auth_token=creds["TURSO_AUTH_TOKEN"])
        db.init_schema()

    client = ZoomInfoClient(
        client_id=creds["ZOOMINFO_CLIENT_ID"],
        client_secret=creds["ZOOMINFO_CLIENT_SECRET"],
    )

    cost_tracker = CostTracker(db)

    # --- Log pipeline start ---
    run_id = db.start_pipeline_run("intent", trigger, config)

    try:
        # --- Budget check ---
        budget = cost_tracker.check_budget("intent", config["target_companies"])
        if budget.alert_level == "exceeded":
            msg = f"Budget exceeded: {budget.alert_message}"
            logger.warning(msg)
            summary["budget_exceeded"] = True
            db.complete_pipeline_run(run_id, "skipped", summary, None, 0, 0, msg)
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": msg}

        # ─── Step 1: Intent Search ───
        logger.info("Step 1: Intent search for topics=%s, strengths=%s",
                    config["topics"], config["signal_strengths"])

        intent_params = IntentQueryParams(
            topics=config["topics"],
            signal_strengths=config["signal_strengths"],
            sic_codes=get_sic_codes(),
            employee_min=get_employee_minimum(),
        )
        intent_results = client.search_intent_all_pages(intent_params, max_pages=10)
        summary["intent_results"] = len(intent_results)
        logger.info("Intent search returned %d results", len(intent_results))

        if not intent_results:
            db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": None}

        # ─── Step 2: Score + select top N ───
        logger.info("Step 2: Scoring and selecting top %d companies",
                    config["target_companies"])

        scored_leads = score_intent_leads(intent_results)
        scored_leads, _dedup_removed = dedupe_leads(scored_leads)
        summary["scored_results"] = len(scored_leads)

        # Cross-session dedup: filter previously exported companies
        dedup_days = config.get("dedup_days_back", 180)
        lookup = get_previously_exported(db, days_back=dedup_days)
        new_leads, filtered_leads = filter_previously_exported(scored_leads, lookup)
        summary["dedup_filtered"] = len(filtered_leads)
        logger.info("Cross-session dedup: %d new, %d previously exported",
                    len(new_leads), len(filtered_leads))

        # Take top N by score
        target = config["target_companies"]
        selected = new_leads[:target]
        summary["companies_selected"] = len(selected)

        if not selected:
            logger.info("No new companies after dedup filtering")
            db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": None}

        # Build company lookup for later scoring
        company_scores = {}
        selected_companies = {}
        for lead in selected:
            cid = str(lead.get("companyId", ""))
            company_scores[cid] = lead
            selected_companies[cid] = lead

        # ─── Step 3: Resolve company IDs ───
        logger.info("Step 3: Resolving %d company IDs", len(selected))

        company_ids = list(selected_companies.keys())
        cached = db.get_company_ids_bulk(company_ids)
        numeric_map = {}  # hashed_id → numeric_id

        for hid in company_ids:
            if hid in cached:
                numeric_map[hid] = cached[hid]["numeric_id"]

        uncached = [hid for hid in company_ids if hid not in numeric_map]
        if uncached:
            logger.info("Enriching %d contacts to resolve company IDs (%d cached)",
                         len(uncached), len(cached))
            for hid in uncached:
                company_lead = selected_companies[hid]
                recommended = company_lead.get("recommendedContacts") or []
                if not recommended or not isinstance(recommended[0], dict):
                    continue
                pid = recommended[0].get("id")
                if not pid:
                    continue
                try:
                    enriched = client.enrich_contacts_batch(
                        person_ids=[pid],
                        output_fields=["id", "companyId", "companyName"],
                    )
                    if enriched:
                        company = enriched[0].get("company", {})
                        numeric_id = company.get("id") or enriched[0].get("companyId")
                        company_name = company.get("name") or enriched[0].get("companyName", "")
                        if numeric_id:
                            numeric_map[hid] = int(numeric_id)
                            db.save_company_id(hid, int(numeric_id), company_name)
                except Exception as e:
                    logger.warning("Could not resolve %s: %s", hid[:8], e)

        if not numeric_map:
            logger.warning("Could not resolve any company IDs")
            db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": "No company IDs resolved"}

        # ─── Step 4: Contact search + auto-select ───
        logger.info("Step 4: Contact search for %d companies", len(numeric_map))

        numeric_ids = [str(nid) for nid in numeric_map.values()]
        contact_params = ContactQueryParams(
            company_ids=numeric_ids,
            management_levels=config.get("management_levels", ["Manager", "Director", "VP Level Exec"]),
            contact_accuracy_score_min=config.get("accuracy_min", 95),
            required_fields=config.get("phone_fields", ["mobilePhone", "directPhone", "phone"]),
            required_fields_operator="or",
        )

        contacts = client.search_contacts_all_pages(contact_params, max_pages=5)
        summary["contacts_found"] = len(contacts)
        logger.info("Contact search returned %d contacts", len(contacts))

        if not contacts:
            db.complete_pipeline_run(run_id, "success", summary, None, 0, 0, None)
            return {"success": True, "csv_content": None, "csv_filename": None,
                    "batch_id": None, "summary": summary, "error": None}

        # Auto-select best contact per company (highest accuracy)
        contacts_by_company = build_contacts_by_company(contacts)
        auto_selected = {}
        for cid, data in contacts_by_company.items():
            if data["contacts"]:
                auto_selected[cid] = data["contacts"][0]

        selected_contacts = list(auto_selected.values())

        # ─── Step 5: Enrich + score + export ───
        logger.info("Step 5: Enriching %d contacts", len(selected_contacts))

        person_ids = [
            c.get("personId") or c.get("id")
            for c in selected_contacts
            if c.get("personId") or c.get("id")
        ]

        enriched = client.enrich_contacts_batch(
            person_ids=person_ids,
            output_fields=DEFAULT_ENRICH_OUTPUT_FIELDS,
        )
        summary["contacts_enriched"] = len(enriched)
        summary["credits_used"] = len(enriched)

        # Log credit usage
        cost_tracker.log_usage(
            workflow_type="intent",
            query_params={"topics": config["topics"], "source": "automation"},
            credits_used=len(enriched),
            leads_returned=len(enriched),
        )

        # Score enriched contacts
        scored_contacts = score_intent_contacts(enriched, company_scores)

        # Add metadata
        for lead in scored_contacts:
            topic = lead.get("_intent_topic", "")
            if not topic:
                topic = config["topics"][0] if config["topics"] else ""
            lead["_lead_source"] = f"ZoomInfo Intent · {topic}"
            lead["_priority"] = get_priority_label(lead.get("_score", 0))

        # Export to CSV
        agents = get_call_center_agents()
        csv_content, csv_filename, batch_id = export_leads_to_csv(
            leads=scored_contacts,
            operator=None,
            workflow_type="intent",
            data_source="ZoomInfo",
            db=db,
            agents=agents,
        )
        summary["contacts_exported"] = len(scored_contacts)
        summary["batch_id"] = batch_id

        # Top 5 leads for email summary
        for lead in scored_contacts[:5]:
            summary["top_leads"].append({
                "name": f"{lead.get('firstName', '')} {lead.get('lastName', '')}".strip(),
                "company": lead.get("companyName", "") or lead.get("company", {}).get("name", ""),
                "title": lead.get("jobTitle", ""),
                "score": lead.get("_score", 0),
                "topic": lead.get("_intent_topic", ""),
            })

        # Record outcomes for calibration tracking
        now = datetime.now(timezone.utc).isoformat()
        outcomes = []
        for lead in scored_contacts:
            cid = lead.get("companyId") or lead.get("company", {}).get("id", "")
            pid = lead.get("personId") or lead.get("id", "")
            outcomes.append((
                batch_id,
                lead.get("companyName", "") or lead.get("company", {}).get("name", ""),
                str(cid) if cid else None,
                str(pid) if pid else None,
                lead.get("sicCode", "") or lead.get("company", {}).get("sicCode", ""),
                lead.get("employeeCount") or lead.get("company", {}).get("employeeCount"),
                None,  # distance_miles (N/A for intent)
                lead.get("zipCode", "") or lead.get("company", {}).get("zip", ""),
                lead.get("state", "") or lead.get("company", {}).get("state", ""),
                lead.get("_score", 0),
                "intent",
                now,
                json.dumps({"automated": True, "topics": config["topics"]}),
            ))
        if outcomes:
            db.record_lead_outcomes_batch(outcomes)

        logger.info("Pipeline complete: %d leads exported (batch %s)",
                    len(scored_contacts), batch_id)

        db.complete_pipeline_run(
            run_id, "success", summary, batch_id,
            summary.get("credits_used", 0), len(scored_contacts), None,
        )

        return {
            "success": True,
            "csv_content": csv_content,
            "csv_filename": csv_filename,
            "batch_id": batch_id,
            "summary": summary,
            "error": None,
        }
    except Exception as e:
        db.complete_pipeline_run(run_id, "failed", summary, None, 0, 0, str(e))
        raise


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def build_email(result: dict, creds: dict, date_str: str) -> MIMEMultipart:
    """Build MIME email with HTML summary and CSV attachment."""
    summary = result["summary"]
    n_exported = summary.get("contacts_exported", 0)

    if n_exported == 0:
        subject = f"[HADES] Intent Pipeline: No Results — {date_str}"
    else:
        subject = f"[HADES] Intent Pipeline: {n_exported} leads — {date_str}"

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = creds.get("EMAIL_FROM") or creds.get("SMTP_USER", "")
    msg["To"] = creds.get("EMAIL_RECIPIENTS", "")

    # HTML body
    html = _build_html_body(summary, result.get("batch_id"))
    msg.attach(MIMEText(html, "html"))

    # CSV attachment
    if result.get("csv_content"):
        part = MIMEBase("text", "csv")
        part.set_payload(result["csv_content"].encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=result.get("csv_filename", "intent_leads.csv"))
        msg.attach(part)

    return msg


def _build_html_body(summary: dict, batch_id: str | None) -> str:
    """Build HTML summary table."""
    topics = ", ".join(summary.get("topics", []))
    rows = [
        ("Topics", topics),
        ("Signal Strengths", ", ".join(summary.get("signal_strengths", []))),
        ("Intent Results", summary.get("intent_results", 0)),
        ("Scored (non-stale)", summary.get("scored_results", 0)),
        ("Previously Exported (filtered)", summary.get("dedup_filtered", 0)),
        ("Companies Selected", summary.get("companies_selected", 0)),
        ("Contacts Found", summary.get("contacts_found", 0)),
        ("Contacts Enriched", summary.get("contacts_enriched", 0)),
        ("Contacts Exported", summary.get("contacts_exported", 0)),
        ("Credits Used", summary.get("credits_used", 0)),
    ]
    if batch_id:
        rows.append(("Batch ID", batch_id))

    table_rows = "".join(
        f"<tr><td style='padding:4px 12px;font-weight:bold'>{k}</td>"
        f"<td style='padding:4px 12px'>{v}</td></tr>"
        for k, v in rows
    )

    top_leads_html = ""
    if summary.get("top_leads"):
        lead_rows = "".join(
            f"<tr><td style='padding:4px 8px'>{l['name']}</td>"
            f"<td style='padding:4px 8px'>{l['company']}</td>"
            f"<td style='padding:4px 8px'>{l['title']}</td>"
            f"<td style='padding:4px 8px'>{l['score']}</td>"
            f"<td style='padding:4px 8px'>{l['topic']}</td></tr>"
            for l in summary["top_leads"]
        )
        top_leads_html = f"""
        <h3>Top Leads</h3>
        <table border='1' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>
        <tr style='background:#f0f0f0'>
            <th style='padding:4px 8px'>Name</th>
            <th style='padding:4px 8px'>Company</th>
            <th style='padding:4px 8px'>Title</th>
            <th style='padding:4px 8px'>Score</th>
            <th style='padding:4px 8px'>Topic</th>
        </tr>
        {lead_rows}
        </table>"""

    budget_note = ""
    if summary.get("budget_exceeded"):
        budget_note = "<p style='color:red;font-weight:bold'>Budget exceeded — pipeline skipped.</p>"

    no_results_note = ""
    if summary.get("contacts_exported", 0) == 0 and not summary.get("budget_exceeded"):
        no_results_note = ("<p>No new leads found. This may be because all matching companies "
                           "were previously exported, or no companies showed intent signals "
                           f"for topics: {topics}.</p>")

    return f"""<html><body>
    <h2>HADES Intent Pipeline Report</h2>
    {budget_note}
    {no_results_note}
    <table border='1' cellpadding='0' cellspacing='0' style='border-collapse:collapse'>
    {table_rows}
    </table>
    {top_leads_html}
    <p style='color:#888;font-size:12px'>Generated by HADES automated pipeline</p>
    </body></html>"""


def send_email(msg: MIMEMultipart, creds: dict) -> None:
    """Send email via Gmail SMTP with STARTTLS."""
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(creds["SMTP_USER"], creds["SMTP_PASSWORD"])
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HADES Automated Intent Pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate config and credentials, no API calls")
    parser.add_argument("--no-email", action="store_true",
                        help="Run pipeline but skip email delivery")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--trigger", default="scheduled",
                        help="Run trigger source (scheduled, manual)")
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load credentials
    from _credentials import load_credentials
    try:
        creds = load_credentials()
    except ValueError as e:
        logger.error("Credential error: %s", e)
        sys.exit(1)

    # Load automation config
    from utils import get_automation_config
    config = get_automation_config("intent")
    if not config:
        logger.error("No automation.intent config found in config/icp.yaml")
        sys.exit(1)

    logger.info("Starting intent pipeline (dry_run=%s, no_email=%s)",
                args.dry_run, args.no_email)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Run pipeline
    try:
        result = run_pipeline(config, creds, dry_run=args.dry_run, trigger=args.trigger)
    except Exception:
        logger.exception("Pipeline failed")

        # Try to send error notification
        if not args.no_email and _has_smtp_creds(creds):
            try:
                error_result = {
                    "summary": {**config, "contacts_exported": 0, "budget_exceeded": False},
                    "batch_id": None,
                    "csv_content": None,
                }
                msg = build_email(error_result, creds, date_str)
                msg.replace_header("Subject",
                                   f"[HADES] Intent Pipeline FAILED — {date_str}")
                send_email(msg, creds)
            except Exception:
                logger.exception("Failed to send error notification email")

        sys.exit(1)

    if not result["success"]:
        logger.error("Pipeline returned failure: %s", result.get("error"))
        sys.exit(1)

    # Log summary
    s = result["summary"]
    logger.info("Summary: %d intent → %d scored → %d selected → %d contacts → %d exported",
                s.get("intent_results", 0), s.get("scored_results", 0),
                s.get("companies_selected", 0), s.get("contacts_found", 0),
                s.get("contacts_exported", 0))

    # Email delivery
    if args.dry_run or args.no_email:
        if result.get("csv_content"):
            logger.info("CSV ready: %s (%d bytes)",
                        result["csv_filename"], len(result["csv_content"]))
        return

    if not _has_smtp_creds(creds):
        logger.warning("SMTP credentials not configured — skipping email")
        if result.get("csv_content"):
            logger.info("CSV ready: %s (%d bytes)",
                        result["csv_filename"], len(result["csv_content"]))
        return

    try:
        msg = build_email(result, creds, date_str)
        send_email(msg, creds)
        logger.info("Email sent to %s", creds.get("EMAIL_RECIPIENTS", ""))
    except Exception:
        logger.exception("Email delivery failed")
        sys.exit(1)


def _has_smtp_creds(creds: dict) -> bool:
    return bool(creds.get("SMTP_USER") and creds.get("SMTP_PASSWORD")
                and creds.get("EMAIL_RECIPIENTS"))


if __name__ == "__main__":
    main()
