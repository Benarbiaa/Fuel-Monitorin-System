from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from ..database.database import get_db
from ..database import models
from ..services.report_services import generate_report
import markdown
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import cm
import io, re

router = APIRouter()


def _persist_report(db: Session, station_id: str, content: str) -> models.Report:
    """Save a generated report so it can be listed/searched later."""
    record = models.Report(station_id=station_id, content=content)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/report")
def get_report(
    station_id: str = Query(...),
    db: Session = Depends(get_db)
):
    report = generate_report(db, station_id)
    _persist_report(db, station_id, report)
    return {"station_id": station_id, "report": report}


@router.get("/reports")
def list_reports(
    station_id: str | None = Query(None, description="Filter by station. Omit for all stations."),
    limit: int = Query(20, le=200),
    db: Session = Depends(get_db)
):
    """List previously generated reports, most recent first."""
    query = db.query(models.Report)
    if station_id:
        query = query.filter(models.Report.station_id == station_id)
    results = query.order_by(models.Report.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "station_id": r.station_id,
            "timestamp": r.timestamp,
            "content": r.content,
        }
        for r in results
    ]


@router.get("/report/pdf")
def get_report_pdf(
    station_id: str = Query(...),
    db: Session = Depends(get_db)
):
    report_md = generate_report(db, station_id)
    _persist_report(db, station_id, report_md)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    story = []
    
    # Custom styles
    h1_style = ParagraphStyle('H1', parent=styles['Heading1'],
                               textColor=HexColor('#003366'), fontSize=18, spaceAfter=12)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                               textColor=HexColor('#0066cc'), fontSize=14, spaceAfter=8)
    h3_style = ParagraphStyle('H3', parent=styles['Heading3'],
                               textColor=HexColor('#444444'), fontSize=12, spaceAfter=6)
    body_style = ParagraphStyle('Body', parent=styles['Normal'],
                                 fontSize=10, spaceAfter=6, leading=16)
    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'],
                                   fontSize=10, spaceAfter=4, leftIndent=20, leading=14)

    # Parse markdown lines
    for line in report_md.split('\n'):
        if line.startswith('# '):
            story.append(Paragraph(line[2:], h1_style))
            story.append(Spacer(1, 6))
        elif line.startswith('## '):
            story.append(Spacer(1, 8))
            story.append(Paragraph(line[3:], h2_style))
        elif line.startswith('### '):
            story.append(Paragraph(line[4:], h3_style))
        elif line.startswith('- ') or line.startswith('* '):
            text = line[2:].replace('**', '<b>').replace('**', '</b>')
            story.append(Paragraph(f"• {text}", bullet_style))
        elif line.strip() == '':
            story.append(Spacer(1, 6))
        else:
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            story.append(Paragraph(text, body_style))
    
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{station_id}.pdf"}
    )