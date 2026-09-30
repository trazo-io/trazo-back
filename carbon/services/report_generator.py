import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common.specimen import is_specimen, specimen_page_callback

# Get the path to the font files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
font_path = os.path.join(BASE_DIR, "static", "fonts")
if not os.path.exists(font_path):
    font_path = os.path.join(BASE_DIR, "fonts")

# Register fonts
try:
    pdfmetrics.registerFont(TTFont("Roboto", os.path.join(font_path, "Roboto-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Roboto-Bold", os.path.join(font_path, "Roboto-Bold.ttf")))
except:
    # Fallback to built-in fonts if Roboto is not available
    pass


class CarbonReportGenerator:
    """
    Generate a PDF report for carbon emissions and offsets.
    """

    def generate_report(self, report):
        """
        Generate a PDF report for a CarbonReport instance.

        Args:
            report: CarbonReport instance

        Returns:
            str: URL path to the generated PDF
        """
        # Generate a unique filename
        filename = f"carbon_reports/{uuid.uuid4()}.pdf"
        filepath = os.path.join(settings.MEDIA_ROOT, filename) if hasattr(settings, "MEDIA_ROOT") else filename

        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # Create PDF document
        doc = SimpleDocTemplate(filepath, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)

        # Get styles
        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        title_style.fontName = "Roboto-Bold"

        heading_style = styles["Heading1"]
        heading_style.fontName = "Roboto-Bold"

        normal_style = styles["Normal"]
        normal_style.fontName = "Roboto"

        # Create elements for the PDF
        elements = []

        # Title
        elements.append(Paragraph("Carbon Footprint Report", title_style))
        elements.append(Spacer(1, 0.25 * inch))

        # Report details
        entity_name = (
            report.establishment.name
            if report.establishment
            else report.production.name if report.production else "Unknown"
        )
        elements.append(Paragraph(f"Entity: {entity_name}", heading_style))
        elements.append(Spacer(1, 0.1 * inch))

        period = f"Period: {report.period_start.strftime('%B %d, %Y')} to {report.period_end.strftime('%B %d, %Y')}"
        elements.append(Paragraph(period, normal_style))
        elements.append(Paragraph(f"Generated: {report.generated_at.strftime('%B %d, %Y')}", normal_style))
        elements.append(Spacer(1, 0.5 * inch))

        # Summary section
        elements.append(Paragraph("Carbon Footprint Summary", heading_style))
        elements.append(Spacer(1, 0.25 * inch))

        # Summary table
        summary_data = [
            ["Metric", "Value", "Unit"],
            ["Total Emissions", f"{report.total_emissions:.2f}", "kg CO₂e"],
            ["Total Offsets", f"{report.total_offsets:.2f}", "kg CO₂e"],
            ["Net Footprint", f"{report.net_footprint:.2f}", "kg CO₂e"],
            # NEVER: no score row. `CarbonReport.carbon_score` was dropped in migration 0039
            # because a self-assigned 0-100 grade is retired as a CONCEPT. This function has no
            # callers, which is the only reason the AttributeError was never hit; a dormant path
            # is still a path.
        ]

        # Create table
        table = Table(summary_data, colWidths=[2 * inch, 1.5 * inch, 1 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgreen),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Roboto-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )

        elements.append(table)
        elements.append(Spacer(1, 0.5 * inch))

        # Recommendations section (if available)
        if hasattr(report, "recommendations") and report.recommendations:
            elements.append(Paragraph("Recommendations", heading_style))
            elements.append(Spacer(1, 0.25 * inch))

            for i, recommendation in enumerate(report.recommendations):
                rec_text = recommendation if isinstance(recommendation, str) else str(recommendation)
                elements.append(Paragraph(f"{i+1}. {rec_text}", normal_style))
                elements.append(Spacer(1, 0.1 * inch))

        # Footer
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph(f"Report ID: {report.id}", normal_style))
        elements.append(Paragraph("This report was generated by Trazo Carbon Management System", normal_style))
        if report.usda_factors_used:
            # 2026-08-21 — was "✓ USDA Verified". `.claude/rules/compliance.md` puts that
            # exact phrase on the UNSAFE list: it asserts third-party verification of the
            # FARM, when all that is true is where the emission factors came from. FTC
            # 16 CFR 260.6, and the Truly Organic consent order ($1.76M) is the precedent.
            #
            # Dormant when found — `CarbonReportGenerator.generate_report` has no callers,
            # it is only exported from carbon/services/__init__.py. Fixed rather than left,
            # because a banned claim sitting in a revivable code path is how the phantom
            # "14-day free trial" got back onto a live pricing page.
            elements.append(Paragraph("Emission factors: EPA/USDA-sourced", normal_style))

        # Build PDF
        _furniture = specimen_page_callback(letter, specimen=is_specimen(getattr(report, "establishment", None)))
        doc.build(elements, onFirstPage=_furniture, onLaterPages=_furniture)

        # Return the URL
        url = default_storage.url(filename) if hasattr(default_storage, "url") else f"/media/{filename}"
        return url


report_generator = CarbonReportGenerator()
