"""
api/routes/export.py — PDF and Markdown export endpoints
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
import io

from backend.api.routes.run import active_runs
from backend.db.session import build_context_from_db
from backend.export.pdf_generator import generate_pdf
from backend.export.markdown_writer import generate_markdown
from backend.export.pptx_generator import generate_pptx

router = APIRouter()


async def _get_context(run_id: str):
    """Get RunContext from memory or rebuild from DB."""
    ctx = active_runs.get(run_id)
    if not ctx:
        ctx = await build_context_from_db(run_id)
    return ctx


@router.get("/api/run/{run_id}/export/pdf")
async def export_pdf(run_id: str):
    """Generate and download a PDF report."""
    ctx = await _get_context(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found or not completed yet")

    pdf_bytes = await generate_pdf(ctx)
    filename = f"startup-plan-{ctx.startup_idea.get('startup_name', run_id[:8]).replace(' ', '-').lower()}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/api/run/{run_id}/export/markdown")
async def export_markdown(run_id: str):
    """Generate and download a Markdown report."""
    ctx = await _get_context(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found or not completed yet")

    md_content = await generate_markdown(ctx)
    filename = f"startup-plan-{ctx.startup_idea.get('startup_name', run_id[:8]).replace(' ', '-').lower()}.md"

    return Response(
        content=md_content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/api/run/{run_id}/export/pptx")
async def export_pptx(run_id: str):
    """Generate and download a PPTX pitch deck."""
    ctx = await _get_context(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found or not completed yet")

    pptx_bytes = generate_pptx(ctx)
    filename = f"startup-plan-{ctx.startup_idea.get('startup_name', run_id[:8]).replace(' ', '-').lower()}.pptx"

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/api/run/{run_id}/result")
async def get_full_result(run_id: str):
    """Get the full structured result as JSON."""
    ctx = await _get_context(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found or not completed yet")

    return {
        "run_id": ctx.run_id,
        "startup_idea": ctx.startup_idea,
        "market_research": ctx.market_research,
        "competitor_analysis": ctx.competitor_analysis,
        "customer_personas": ctx.customer_personas,
        "product_design": ctx.product_design,
        "mvp_roadmap": ctx.mvp_roadmap,
        "business_model": ctx.business_model,
        "pricing_strategy": ctx.pricing_strategy,
        "financial_projections": ctx.financial_projections,
        "risk_register": ctx.risk_register,
        "tech_architecture": ctx.tech_architecture,
        "database_schema": ctx.database_schema,
        "security_compliance": ctx.security_compliance,
        "pitch_deck": ctx.pitch_deck,
        "executive_summary": ctx.executive_summary,
        "problem_refined": ctx.problem_refined,
        "status": ctx.status,
        "completed_at": ctx.completed_at.isoformat() if ctx.completed_at else None,
    }
