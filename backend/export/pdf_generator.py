"""
export/pdf_generator.py — Generate stylized PDF startup plan using ReportLab
"""
from backend.context import RunContext
from backend.agents.investor_metrics import investor_metrics
from html import escape
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Preformatted
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# Brand Colors
DARK_BG = HexColor("#0f172a")
ACCENT = HexColor("#6366f1")
ACCENT_LIGHT = HexColor("#818cf8")
LIGHT_TEXT = HexColor("#e2e8f0")
MUTED = HexColor("#64748b")
SUCCESS = HexColor("#22c55e")
CARD_BG = HexColor("#1e293b")


def create_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="Title1",
        fontSize=28, fontName="Helvetica-Bold",
        textColor=white, spaceAfter=6, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="Subtitle",
        fontSize=13, fontName="Helvetica",
        textColor=MUTED, spaceAfter=20, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader",
        fontSize=16, fontName="Helvetica-Bold",
        textColor=ACCENT_LIGHT, spaceAfter=8, spaceBefore=16
    ))
    styles.add(ParagraphStyle(
        name="BodyText2",
        fontSize=10, fontName="Helvetica",
        textColor=LIGHT_TEXT, spaceAfter=5, leading=16
    ))
    styles.add(ParagraphStyle("ArtifactText", parent=styles["BodyText2"], textColor=DARK_BG))
    styles.add(ParagraphStyle(
        name="BulletItem",
        fontSize=10, fontName="Helvetica",
        textColor=LIGHT_TEXT, spaceAfter=3, leftIndent=15,
        bulletIndent=5
    ))
    styles.add(ParagraphStyle(
        name="MetricLabel",
        fontSize=9, fontName="Helvetica-Bold",
        textColor=MUTED, spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name="MetricValue",
        fontSize=14, fontName="Helvetica-Bold",
        textColor=SUCCESS, spaceAfter=8
    ))
    return styles


def add_section(story, styles, title, entries):
    if not entries:
        return
    story.append(Paragraph(title, styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    for entry in entries:
        story.append(Paragraph(escape(entry), styles["ArtifactText"]))
    story.append(Spacer(1, 0.15 * inch))


def add_pitch_deck(story, styles, slides):
    if not slides:
        return
    story.append(Paragraph("Pitch Deck", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    text_style = styles["ArtifactText"]
    heading_style = ParagraphStyle("PitchSlide", parent=text_style, fontName="Helvetica-Bold", keepWithNext=True)
    bullet_style = ParagraphStyle("PitchBullet", parent=styles["BulletItem"], textColor=DARK_BG)
    for position, slide in enumerate(slides, start=1):
        heading = f"Slide {slide.get('slide_number') or position}"
        if title := slide.get("title"):
            heading += f": {title}"
        story.append(Paragraph(escape(heading), heading_style))
        if headline := slide.get("headline"):
            story.append(Paragraph(escape(headline), text_style))
        for bullet in slide.get("bullet_points") or []:
            story.append(Paragraph(escape(bullet), bullet_style, bulletText="•"))
        if notes := slide.get("speaker_notes"):
            story.append(Paragraph(escape(f"Speaker notes: {notes}"), text_style))
        story.append(Spacer(1, 0.1 * inch))


async def generate_pdf(ctx: RunContext, *, notice="") -> bytes:
    """Generate a complete PDF startup plan."""
    buffer = io.BytesIO()
    idea = ctx.startup_idea
    market = ctx.market_research
    comp = ctx.competitor_analysis
    personas = ctx.customer_personas
    product = ctx.product_design
    biz = ctx.business_model
    pricing = ctx.pricing_strategy
    fin = ctx.financial_projections
    risk = ctx.risk_register
    exec_sum = ctx.executive_summary
    estimates = investor_metrics(market, fin)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
    )

    styles = create_styles()
    story = []

    # ── Cover Page ──────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5*inch))
    story.append(Paragraph(escape(str(idea.get("startup_name", "Startup Plan"))), styles["Title1"]))
    story.append(Paragraph(escape(str(idea.get("tagline", ""))), styles["Subtitle"]))
    if notice:
        story.append(Paragraph(escape(notice), styles["Subtitle"]))
    story.append(Spacer(1, 0.3*inch))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=20))
    story.append(Paragraph("AI-Generated Investor-Ready Startup Plan", styles["Subtitle"]))
    story.append(Paragraph(f"Generated by AI Startup Co-Founder Agent • {ctx.created_at.strftime('%B %d, %Y')}", styles["Subtitle"]))

    # Metrics snapshot
    metrics = exec_sum.get("key_metrics_snapshot", {})
    if metrics:
        combined = []
        for i in range(min(6, len(metrics))):
            k = list(metrics.keys())[i]
            v = list(metrics.values())[i]
            combined.append([
                Paragraph(escape(k.replace("_", " ").upper()), styles["MetricLabel"]),
                Paragraph(escape(str(v)), styles["MetricValue"])
            ])
        t = Table(combined, colWidths=[2.5*inch, 4*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
            ("TEXTCOLOR", (0, 0), (-1, -1), LIGHT_TEXT),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [CARD_BG, DARK_BG]),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(Spacer(1, 0.5*inch))
        story.append(t)

    story.append(PageBreak())

    # ── Executive Summary ───────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    story.append(Paragraph(escape(str(exec_sum.get("executive_summary", ""))), styles["BodyText2"]))
    if ctx.problem_refined:
        story.append(Paragraph("Refined Problem", styles["SectionHeader"]))
        story.append(Paragraph(escape(ctx.problem_refined), styles["BodyText2"]))
    story.append(Spacer(1, 0.2*inch))

    # ── Startup Idea ────────────────────────────────────────────────────
    story.append(Paragraph("💡 The Startup Idea", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    idea_data = [
        ["One-liner", idea.get("one_liner", "")],
        ["Value Proposition", idea.get("value_proposition", "")],
        ["Target Customer", idea.get("target_customer", "")],
        ["Key Differentiator", idea.get("key_differentiator", "")],
        ["Unfair Advantage", idea.get("unfair_advantage", "")],
    ]
    for row in idea_data:
        story.append(Paragraph(f"<b>{row[0]}:</b> {escape(str(row[1]))}", styles["BodyText2"]))
    story.append(Spacer(1, 0.2*inch))

    # ── Market Research ─────────────────────────────────────────────────
    story.append(Paragraph("📊 Market Analysis", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    market_table = Table([
        ["Metric", "Value"],
        ["Estimated TAM", estimates["tam"]],
        ["Estimated SAM", estimates["sam"]],
        ["Estimated SOM", estimates["som"]],
        ["Estimated CAGR", estimates["cagr"]],
        ["Market Timing", market.get("market_timing", "")[:100]],
    ], colWidths=[2.5*inch, 4.5*inch])
    market_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, DARK_BG]),
        ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT_TEXT),
        ("GRID", (0, 0), (-1, -1), 0.25, MUTED),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(market_table)
    story.append(Spacer(1, 0.2*inch))

    # ── Financial Projections ───────────────────────────────────────────
    story.append(Paragraph("📈 Financial Highlights", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
    fin_table = Table([
        ["Break-even", "12-mo ARR", "LTV", "CAC", "LTV:CAC"],
        [
            Paragraph(escape(estimates["breakeven"]), styles["BodyText2"]),
            estimates["arr"], estimates["ltv"], estimates["cac"], estimates["ltv_cac"],
        ]
    ], colWidths=[1.3*inch, 1.4*inch, 1.3*inch, 1.3*inch, 1.4*inch])
    fin_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, 1), CARD_BG),
        ("TEXTCOLOR", (0, 1), (-1, 1), SUCCESS),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(fin_table)
    if fin:
        story.append(Paragraph("Financial figures are projections.", styles["BodyText2"]))
    if note := fin.get("key_assumptions_note"):
        story.append(Paragraph(escape(str(note)), styles["BodyText2"]))
    story.append(Spacer(1, 0.2*inch))

    # ── Pricing ──────────────────────────────────────────────────────────
    tiers = pricing.get("tiers", [])
    if tiers:
        story.append(Paragraph("💰 Pricing Tiers", styles["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
        tier_data = [["Tier", "Monthly", "Annual", "Target"]]
        for tier in tiers:
            tier_data.append([
                tier.get("tier_name", "?"),
                f"${tier.get('price_monthly_usd', 0)}/mo",
                f"${tier.get('price_annual_usd', 0)}/yr",
                tier.get("target_persona", "?")[:40],
            ])
        tier_table = Table(tier_data, colWidths=[1.2*inch, 1.2*inch, 1.2*inch, 3.2*inch])
        tier_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, DARK_BG]),
            ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT_TEXT),
            ("GRID", (0, 0), (-1, -1), 0.25, MUTED),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(tier_table)
        story.append(Spacer(1, 0.2*inch))

    story.append(PageBreak())

    # ── Risk Register ────────────────────────────────────────────────────
    risks = risk.get("risks", [])
    if risks:
        story.append(Paragraph("⚠️ Risk Register (Top 10)", styles["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
        risk_data = [["#", "Risk", "Prob", "Impact", "Mitigation"]]
        for r in risks[:10]:
            risk_data.append([
                r.get("risk_id", "?"),
                r.get("title", "?")[:30],
                r.get("probability", "?"),
                r.get("impact", "?"),
                r.get("mitigation_strategy", "")[:50],
            ])
        risk_table = Table(risk_data, colWidths=[0.5*inch, 1.6*inch, 0.7*inch, 0.7*inch, 3.3*inch])
        risk_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, DARK_BG]),
            ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT_TEXT),
            ("GRID", (0, 0), (-1, -1), 0.25, MUTED),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(risk_table)

    story.append(PageBreak())

    # ── Competitors ──────────────────────────────────────────────────────
    competitors = comp.get("competitors", [])
    if competitors:
        story.append(Paragraph("🥊 Competitive Landscape", styles["SectionHeader"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=ACCENT, spaceAfter=10))
        comp_data = [["Company", "Funding", "Price/mo", "Weakness"]]
        for c in competitors[:5]:
            comp_data.append([
                c.get("name", "?")[:20],
                c.get("funding_stage", "?"),
                f"${c.get('starting_price_monthly', '?')}",
                " / ".join(c.get("weaknesses", [])[:2])[:50],
            ])
        comp_table = Table(comp_data, colWidths=[1.5*inch, 1.2*inch, 1*inch, 3.1*inch])
        comp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, DARK_BG]),
            ("TEXTCOLOR", (0, 1), (-1, -1), LIGHT_TEXT),
            ("GRID", (0, 0), (-1, -1), 0.25, MUTED),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 0.2*inch))
        market_gaps = comp.get("market_gaps", [])
        if market_gaps:
            story.append(Paragraph("Our Opportunities:", styles["BodyText2"]))
            for gap in market_gaps:
                story.append(Paragraph(f"• {escape(str(gap))}", styles["BulletItem"]))
        story.append(Spacer(1, 0.2*inch))

    add_section(story, styles, "Customer Personas", [
        f"{item['name']} ({item['job_title']}). {' / '.join(item['pain_points'])}" for item in personas
    ])
    add_section(story, styles, "Product Design", [
        f"{item['feature']} — {item['description']}" for item in product.get("must_have_features", [])
    ] + [
        f"{item['flow_name']}: {' → '.join(item['steps'])}" for item in product.get("core_ux_flows", [])
    ])
    add_section(story, styles, "MVP Roadmap", [
        f"Sprint {item['sprint_number']} ({item['duration_weeks']} weeks). {item['sprint_goal']} Deliverable: {item['deliverable']}"
        for item in ctx.mvp_roadmap.get("sprints", [])
    ])
    add_section(story, styles, "Business Model", [
        f"{item['stream']} ({item['model']}). {item['description']}" for item in biz.get("revenue_streams", [])
    ] + [
        f"{item['phase']} — {item['strategy']} Target: {item['target']}" for item in biz.get("gtm_phases", [])
    ])
    architecture = ctx.tech_architecture
    if architecture:
        add_section(story, styles, "Technical Architecture", [architecture["architecture_description"],
                    f"Frontend: {architecture['frontend_stack']['framework']}. Backend: {architecture['backend_stack']['framework']}."])
    schema = ctx.database_schema
    if schema:
        add_section(story, styles, "Database Schema", [
            f"{item['entity']} — {item['purpose']}" for item in schema["entities"]
        ])
        sql_style = ParagraphStyle("SchemaSQL", parent=styles["BodyText2"], fontName="Courier",
                                   fontSize=9, leading=12, textColor=DARK_BG)
        story.append(Preformatted(schema["sql_schema"], sql_style, maxLineLength=90))
    add_section(story, styles, "Security and Compliance", ctx.security_compliance.get("security_launch_checklist", []))
    add_pitch_deck(story, styles, ctx.pitch_deck.get("slides", []))

    # ── Footer note ──────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED, spaceBefore=20, spaceAfter=10))
    story.append(Paragraph(
        f"Generated by AI Startup Co-Founder Agent | {ctx.created_at.strftime('%Y-%m-%d')} | Run ID: {ctx.run_id}",
        styles["Subtitle"]
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
