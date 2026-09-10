"""
FEATURE (small polish item): PDF export of a pathway result.

Takes the dict returned by pathway_engine.build_pathway() and renders a
clean, print-friendly PDF: matched scheme, eligibility checklist, financial
breakdown, document checklist, and application steps - something a user can
literally carry to a bank/office instead of screenshotting a phone.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
)


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SectionHeader", parent=styles["Heading2"],
                               textColor=colors.HexColor("#1b4332"), spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle(name="SchemeTitle", parent=styles["Title"],
                               textColor=colors.HexColor("#1b4332")))
    return styles


def export_pathway_pdf(pathway_result, output_path, user_display_name=None):
    """
    pathway_result: the dict from pathway_engine.build_pathway()
    output_path: where to write the .pdf
    user_display_name: optional, printed at the top ("Prepared for: ...")
    """
    styles = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                             topMargin=18 * mm, bottomMargin=18 * mm,
                             leftMargin=18 * mm, rightMargin=18 * mm)
    story = []

    story.append(Paragraph("Your Government Benefit Pathway", styles["SchemeTitle"]))
    if user_display_name:
        story.append(Paragraph(f"Prepared for: {user_display_name}", styles["Normal"]))
    story.append(Spacer(1, 6))

    goal = pathway_result.get("goal") or {}
    if goal.get("raw_text"):
        story.append(Paragraph(f"<b>Your goal:</b> {goal['raw_text']}", styles["Normal"]))
        if goal.get("parsed", {}).get("target_amount"):
            story.append(Paragraph(
                f"<b>Target amount:</b> Rs.{goal['parsed']['target_amount']:,.0f}", styles["Normal"]))
    story.append(Spacer(1, 10))

    best = pathway_result.get("best_match")
    if not best:
        story.append(Paragraph("No fully-eligible scheme was found for this profile.", styles["SectionHeader"]))
        note = pathway_result.get("alternative_note", "")
        if note:
            story.append(Paragraph(note, styles["Normal"]))

        near_misses = pathway_result.get("near_misses", [])
        if near_misses:
            story.append(Paragraph("What's blocking you", styles["SectionHeader"]))
            for nm in near_misses:
                story.append(Paragraph(f"<b>{nm['scheme_name']}</b>", styles["Normal"]))
                items = [ListItem(Paragraph(g["message"], styles["Normal"])) for g in nm["blocking_requirements"]]
                story.append(ListFlowable(items, bulletType="bullet"))
                story.append(Spacer(1, 4))

        alts = pathway_result.get("fallback_alternatives", [])
        if alts:
            story.append(Paragraph("Schemes you can apply for right now", styles["SectionHeader"]))
            items = [ListItem(Paragraph(a["scheme_name"], styles["Normal"])) for a in alts]
            story.append(ListFlowable(items, bulletType="bullet"))

        doc.build(story)
        return output_path

    # --- Best match section ---
    story.append(Paragraph(best["scheme_name"], styles["SectionHeader"]))
    story.append(Paragraph(f"<b>Eligibility:</b> {best['eligibility_summary']}", styles["Normal"]))
    story.append(Spacer(1, 4))

    checklist = best.get("eligibility_checklist", [])
    if checklist:
        rows = [["Requirement", "Status", "Detail"]]
        for c in checklist:
            mark = "PASS" if c["status"] == "pass" else "FAIL"
            rows.append([c["label"], mark, c["detail"]])
        t = Table(rows, colWidths=[100, 45, 300])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b4332")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    # --- Financial breakdown ---
    fin = best.get("financial_breakdown", {})
    story.append(Paragraph("What you can get", styles["SectionHeader"]))
    if fin.get("available"):
        story.append(Paragraph(
            f"Loan amount: Rs.{fin['principal']:,.0f} | Interest rate: {fin['applicable_rate_percent']}% p.a. "
            f"| Tenure: {fin['tenure_years']} years", styles["Normal"]))
        story.append(Paragraph(
            f"Estimated monthly EMI: <b>Rs.{fin['monthly_emi']:,.0f}</b> | "
            f"Total interest over the loan: Rs.{fin['total_interest']:,.0f}", styles["Normal"]))
        if fin.get("gender_rebate_applied"):
            story.append(Paragraph("A gender-based interest rebate has been applied.", styles["Normal"]))
        if fin.get("rate_note"):
            story.append(Paragraph(f"<i>{fin['rate_note']}</i>", styles["Normal"]))
    else:
        story.append(Paragraph(fin.get("reason", "Financial terms not available for this scheme."), styles["Normal"]))
    story.append(Spacer(1, 10))

    # --- Documents ---
    docs = best.get("document_readiness", {})
    story.append(Paragraph(
        f"Before applying: {docs.get('ready_count', 0)}/{docs.get('total_required', 0)} documents ready",
        styles["SectionHeader"]))
    for d in docs.get("ready", []):
        story.append(Paragraph(f"[Have] {d['label']}", styles["Normal"]))
    for d in docs.get("missing", []):
        story.append(Paragraph(f"[Missing] {d['label']}", styles["Normal"]))
    story.append(Spacer(1, 10))

    # --- Application steps ---
    steps = best.get("application_steps", {}).get("steps", [])
    if steps:
        story.append(Paragraph("Your next steps", styles["SectionHeader"]))
        items = [ListItem(Paragraph(s, styles["Normal"])) for s in steps]
        story.append(ListFlowable(items, bulletType="1"))

    doc.build(story)
    return output_path
