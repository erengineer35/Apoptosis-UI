#!/usr/bin/env python3
"""
Professional Medical-Grade PDF Report Generator for ApoptosisUI
Creates clinical laboratory-style analysis reports with AI-generated interpretations.

Based on medical laboratory report standards and best practices.
References:
- Clinical Laboratory Improvement Amendments (CLIA) guidelines
- College of American Pathologists (CAP) standards
- ISO 15189 Medical Laboratory Accreditation

Authors: Atalay ŞAHAN & Gülce Nur Evren
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm, inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak, HRFlowable, KeepTogether,
    ListFlowable, ListItem, Flowable
)
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF

# For image handling
from PIL import Image as PILImage
import io

# Chat handler for AI interpretations
try:
    from chat_handler import ChatHandler
    CHAT_AVAILABLE = True
except ImportError:
    CHAT_AVAILABLE = False

# Configuration
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# Professional Medical Color Palette
COLORS = {
    # Primary colors
    'primary': colors.HexColor('#1E3A5F'),       # Deep Medical Blue
    'primary_light': colors.HexColor('#2E5A8F'),  # Light Medical Blue
    'secondary': colors.HexColor('#2C3E50'),      # Professional Gray

    # Status colors
    'healthy': colors.HexColor('#27AE60'),        # Clinical Green
    'affected': colors.HexColor('#E74C3C'),       # Alert Red
    'warning': colors.HexColor('#F39C12'),        # Warning Orange
    'irrelevant': colors.HexColor('#95A5A6'),     # Neutral Gray

    # Accent colors
    'accent': colors.HexColor('#3498DB'),         # Accent Blue
    'gold': colors.HexColor('#D4AF37'),           # Professional Gold

    # Background colors
    'background': colors.HexColor('#F8FAFC'),     # Light Background
    'light_blue': colors.HexColor('#EBF5FB'),     # Light Blue Background
    'light_green': colors.HexColor('#E8F8F5'),    # Light Green Background
    'light_red': colors.HexColor('#FDEDEC'),      # Light Red Background

    # Border and text
    'border': colors.HexColor('#BDC3C7'),         # Border Gray
    'text': colors.HexColor('#2C3E50'),           # Dark Text
    'text_light': colors.HexColor('#7F8C8D'),     # Light Text
    'white': colors.white,
    'black': colors.black,
}


class RoundedRect(Flowable):
    """Custom flowable for rounded rectangles."""
    def __init__(self, width, height, radius=10, fill_color=None, stroke_color=None, stroke_width=1):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.radius = radius
        self.fill_color = fill_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width

    def draw(self):
        self.canv.saveState()
        if self.fill_color:
            self.canv.setFillColor(self.fill_color)
        if self.stroke_color:
            self.canv.setStrokeColor(self.stroke_color)
            self.canv.setLineWidth(self.stroke_width)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius,
                           fill=1 if self.fill_color else 0,
                           stroke=1 if self.stroke_color else 0)
        self.canv.restoreState()


class StatusIndicator(Flowable):
    """Custom flowable for status indicator circles."""
    def __init__(self, status='normal', size=12):
        Flowable.__init__(self)
        self.status = status
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        colors_map = {
            'normal': COLORS['healthy'],
            'elevated': COLORS['affected'],
            'low': COLORS['warning'],
            'critical': COLORS['affected'],
        }
        color = colors_map.get(self.status, COLORS['irrelevant'])

        self.canv.saveState()
        self.canv.setFillColor(color)
        self.canv.circle(self.size/2, self.size/2, self.size/2 - 1, fill=1, stroke=0)
        self.canv.restoreState()


def get_medical_styles():
    """Create professional medical report paragraph styles."""
    styles = getSampleStyleSheet()

    # Main Title
    styles.add(ParagraphStyle(
        name='MainTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=COLORS['primary'],
        alignment=TA_CENTER,
        spaceAfter=2*mm,
        fontName='Helvetica-Bold',
        leading=26
    ))

    # Report Subtitle
    styles.add(ParagraphStyle(
        name='Subtitle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
        spaceAfter=4*mm,
        fontName='Helvetica'
    ))

    # Section Header (main sections)
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=COLORS['white'],
        spaceBefore=6*mm,
        spaceAfter=0,
        fontName='Helvetica-Bold',
        leading=18
    ))

    # Subsection Header
    styles.add(ParagraphStyle(
        name='SubsectionHeader',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=COLORS['primary'],
        spaceBefore=4*mm,
        spaceAfter=2*mm,
        fontName='Helvetica-Bold',
        leading=14
    ))

    # Body Text (use MedicalBody to avoid conflict with default BodyText)
    styles.add(ParagraphStyle(
        name='MedicalBody',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COLORS['text'],
        alignment=TA_JUSTIFY,
        spaceAfter=2*mm,
        leading=13,
        fontName='Helvetica'
    ))

    # Small Text (for captions, notes)
    styles.add(ParagraphStyle(
        name='SmallText',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLORS['text_light'],
        alignment=TA_LEFT,
        leading=10,
        fontName='Helvetica'
    ))

    # Caption
    styles.add(ParagraphStyle(
        name='Caption',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
        spaceBefore=1*mm,
        spaceAfter=2*mm,
        fontName='Helvetica-Oblique'
    ))

    # Key Value Label
    styles.add(ParagraphStyle(
        name='KeyLabel',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLORS['text_light'],
        fontName='Helvetica'
    ))

    # Key Value Data
    styles.add(ParagraphStyle(
        name='KeyValue',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['text'],
        fontName='Helvetica-Bold'
    ))

    # Clinical Finding - Normal
    styles.add(ParagraphStyle(
        name='FindingNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['healthy'],
        fontName='Helvetica-Bold'
    ))

    # Clinical Finding - Abnormal
    styles.add(ParagraphStyle(
        name='FindingAbnormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['affected'],
        fontName='Helvetica-Bold'
    ))

    # Footer
    styles.add(ParagraphStyle(
        name='Footer',
        parent=styles['Normal'],
        fontSize=7,
        textColor=COLORS['text_light'],
        alignment=TA_CENTER,
        fontName='Helvetica'
    ))

    # Disclaimer
    styles.add(ParagraphStyle(
        name='Disclaimer',
        parent=styles['Normal'],
        fontSize=7,
        textColor=COLORS['text_light'],
        alignment=TA_JUSTIFY,
        leading=9,
        fontName='Helvetica-Oblique'
    ))

    # Large Number (for key metrics)
    styles.add(ParagraphStyle(
        name='LargeNumber',
        parent=styles['Normal'],
        fontSize=28,
        textColor=COLORS['primary'],
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))

    # Interpretation Text
    styles.add(ParagraphStyle(
        name='Interpretation',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COLORS['text'],
        alignment=TA_JUSTIFY,
        spaceAfter=2*mm,
        leading=13,
        fontName='Helvetica',
        leftIndent=5*mm,
        rightIndent=5*mm
    ))

    return styles


class MedicalReportGenerator:
    """Generates professional medical-grade PDF reports for cell analysis."""

    def __init__(self):
        self.styles = get_medical_styles()
        self.chat_handler = ChatHandler() if CHAT_AVAILABLE else None
        self.results_path = SCRIPT_DIR / "results.json"
        self.report_id = f"CMA-{datetime.now().strftime('%Y%m%d')}-{datetime.now().strftime('%H%M%S')}"
        self.page_width, self.page_height = A4
        self.margin = 1.5*cm
        self.content_width = self.page_width - 2*self.margin

    def load_analysis_data(self) -> Optional[Dict[str, Any]]:
        """Load the latest analysis results."""
        try:
            if self.results_path.exists():
                with open(self.results_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading results: {e}", file=sys.stderr)
        return None

    def get_ai_interpretation(self) -> str:
        """Get AI-generated clinical interpretation."""
        if self.chat_handler and self.chat_handler.is_available():
            try:
                return self.chat_handler.generate_report_interpretation()
            except Exception as e:
                print(f"AI interpretation error: {e}", file=sys.stderr)
        return "AI clinical interpretation is currently unavailable. Please ensure the Groq API is properly configured."

    def resize_image_for_report(self, image_path: Path, max_width: float, max_height: float) -> Optional[str]:
        """Resize and optimize image for report inclusion."""
        try:
            if not image_path.exists():
                return None

            with PILImage.open(image_path) as img:
                if img.mode in ('RGBA', 'P'):
                    background = PILImage.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')

                width_ratio = max_width / img.width
                height_ratio = max_height / img.height
                ratio = min(width_ratio, height_ratio)

                new_width = int(img.width * ratio)
                new_height = int(img.height * ratio)

                img_resized = img.resize((new_width, new_height), PILImage.LANCZOS)

                temp_path = SCRIPT_DIR / f"_temp_report_{image_path.stem}.jpg"
                img_resized.save(temp_path, 'JPEG', quality=90, optimize=True)
                return str(temp_path)

        except Exception as e:
            print(f"Error processing image {image_path}: {e}", file=sys.stderr)
            return None

    def create_section_header(self, title: str, icon: str = "") -> Table:
        """Create a styled section header with background."""
        header_text = f"{icon}  {title}" if icon else title
        para = Paragraph(header_text, self.styles['SectionHeader'])

        table = Table([[para]], colWidths=[self.content_width])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['primary']),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('ROUNDEDCORNERS', [6, 6, 0, 0]),
        ]))
        return table

    def create_header_section(self, elements: list):
        """Create professional report header with institution info."""
        # Top decorative line
        elements.append(HRFlowable(
            width="100%", thickness=3, color=COLORS['primary'],
            spaceAfter=3*mm
        ))

        # Institution header table
        header_data = [
            [
                Paragraph("<b>CELL MORPHOLOGY LABORATORY</b>", ParagraphStyle(
                    'InstName', fontSize=14, textColor=COLORS['primary'],
                    fontName='Helvetica-Bold', leading=16
                )),
                Paragraph(f"<b>Report ID:</b> {self.report_id}", ParagraphStyle(
                    'ReportID', fontSize=9, textColor=COLORS['text'],
                    alignment=TA_RIGHT, fontName='Helvetica'
                ))
            ],
            [
                Paragraph("Apoptosis Detection & Analysis System", ParagraphStyle(
                    'InstSub', fontSize=9, textColor=COLORS['text_light'],
                    fontName='Helvetica'
                )),
                Paragraph(f"<b>Date:</b> {datetime.now().strftime('%d %B %Y, %H:%M')}", ParagraphStyle(
                    'ReportDate', fontSize=9, textColor=COLORS['text'],
                    alignment=TA_RIGHT, fontName='Helvetica'
                ))
            ]
        ]

        header_table = Table(header_data, colWidths=[10*cm, 7*cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 4*mm))

        # Main title
        elements.append(Paragraph(
            "CELL MORPHOLOGY ANALYSIS REPORT",
            self.styles['MainTitle']
        ))
        elements.append(Paragraph(
            "Automated Apoptosis Detection and Quantification",
            self.styles['Subtitle']
        ))

        # Decorative separator
        elements.append(HRFlowable(
            width="60%", thickness=1.5, color=COLORS['gold'],
            spaceBefore=2*mm, spaceAfter=5*mm, hAlign='CENTER'
        ))

    def create_sample_info_section(self, elements: list, data: Dict[str, Any]):
        """Create sample and analysis information section."""
        elements.append(self.create_section_header("SAMPLE INFORMATION", "📋"))

        input_file = data.get('input_file', 'Unknown')
        status = data.get('status', 'completed').upper()

        # Create info cards layout
        info_data = [
            [
                self._create_info_card("Sample ID", self.report_id.split('-')[1] + "-" + self.report_id.split('-')[2][:4], COLORS['light_blue']),
                self._create_info_card("Analysis Date", datetime.now().strftime('%Y-%m-%d'), COLORS['light_blue']),
                self._create_info_card("Analysis Time", datetime.now().strftime('%H:%M:%S'), COLORS['light_blue']),
                self._create_info_card("Status", status, COLORS['light_green'] if status == 'COMPLETED' else COLORS['light_red']),
            ]
        ]

        info_table = Table(info_data, colWidths=[4.25*cm]*4)
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))

        # Wrap in container with background
        container = Table([[info_table]], colWidths=[self.content_width])
        container.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(container)

        # File information
        file_info = Table([
            [
                Paragraph("<b>Input File:</b>", self.styles['SmallText']),
                Paragraph(str(input_file), self.styles['MedicalBody'])
            ]
        ], colWidths=[2.5*cm, 14.5*cm])
        file_info.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (0, 0), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(file_info)
        elements.append(Spacer(1, 3*mm))

    def _create_info_card(self, label: str, value: str, bg_color) -> Table:
        """Create a small info card with label and value."""
        card_data = [
            [Paragraph(label, self.styles['KeyLabel'])],
            [Paragraph(f"<b>{value}</b>", self.styles['KeyValue'])]
        ]
        card = Table(card_data, colWidths=[3.8*cm])
        card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_color),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))
        return card

    def create_executive_summary(self, elements: list, data: Dict[str, Any]):
        """Create executive summary with key metrics."""
        elements.append(self.create_section_header("EXECUTIVE SUMMARY", "📊"))

        stats = data.get('statistics', {})
        cell_counts = stats.get('cell_counts_by_class', {})
        total = stats.get('total_cells', 0)

        healthy = cell_counts.get('healthy', 0)
        affected = cell_counts.get('affected', 0)
        irrelevant = cell_counts.get('irrelevant', 0)

        # Calculate percentages
        healthy_pct = round(healthy / max(total, 1) * 100, 1)
        affected_pct = round(affected / max(total, 1) * 100, 1)
        irrelevant_pct = round(irrelevant / max(total, 1) * 100, 1)

        # Key metrics cards
        metrics_data = [[
            self._create_metric_card("TOTAL CELLS", str(total), COLORS['primary'], "Analyzed"),
            self._create_metric_card("HEALTHY", str(healthy), COLORS['healthy'], f"{healthy_pct}%"),
            self._create_metric_card("AFFECTED", str(affected), COLORS['affected'], f"{affected_pct}%"),
            self._create_metric_card("IRRELEVANT", str(irrelevant), COLORS['irrelevant'], f"{irrelevant_pct}%"),
        ]]

        metrics_table = Table(metrics_data, colWidths=[4.25*cm]*4)
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))

        container = Table([[metrics_table]], colWidths=[self.content_width])
        container.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(container)

        # Clinical Assessment
        elements.append(Spacer(1, 3*mm))
        assessment = self._get_clinical_assessment(healthy_pct, affected_pct)
        assessment_box = self._create_assessment_box(assessment)
        elements.append(assessment_box)
        elements.append(Spacer(1, 3*mm))

    def _create_metric_card(self, label: str, value: str, color, subtitle: str) -> Table:
        """Create a large metric display card."""
        card_data = [
            [Paragraph(f'<font color="#{color.hexval()[2:]}">{label}</font>',
                      ParagraphStyle('MetricLabel', fontSize=8, alignment=TA_CENTER,
                                    fontName='Helvetica-Bold', textColor=color))],
            [Paragraph(f'<font color="#{color.hexval()[2:]}" size="24"><b>{value}</b></font>',
                      ParagraphStyle('MetricValue', fontSize=24, alignment=TA_CENTER,
                                    fontName='Helvetica-Bold', textColor=color))],
            [Paragraph(subtitle, ParagraphStyle('MetricSub', fontSize=9, alignment=TA_CENTER,
                                               textColor=COLORS['text_light']))],
        ]
        card = Table(card_data, colWidths=[4*cm])
        card.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['white']),
            ('BOX', (0, 0), (-1, -1), 1, COLORS['border']),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ]))
        return card

    def _get_clinical_assessment(self, healthy_pct: float, affected_pct: float) -> Dict:
        """Determine clinical assessment based on cell percentages."""
        if affected_pct < 10:
            return {
                'level': 'NORMAL',
                'color': COLORS['healthy'],
                'bg': COLORS['light_green'],
                'message': 'Cell population appears within normal parameters. Low apoptosis activity detected.',
                'icon': '✓'
            }
        elif affected_pct < 30:
            return {
                'level': 'MODERATE',
                'color': COLORS['warning'],
                'bg': colors.HexColor('#FEF9E7'),
                'message': 'Moderate apoptosis activity detected. Further monitoring may be recommended.',
                'icon': '⚠'
            }
        else:
            return {
                'level': 'ELEVATED',
                'color': COLORS['affected'],
                'bg': COLORS['light_red'],
                'message': 'Elevated apoptosis activity detected. Clinical correlation is advised.',
                'icon': '!'
            }

    def _create_assessment_box(self, assessment: Dict) -> Table:
        """Create clinical assessment display box."""
        content = [
            [
                Paragraph(f"<b>{assessment['icon']}  CLINICAL ASSESSMENT: {assessment['level']}</b>",
                         ParagraphStyle('AssessTitle', fontSize=11, textColor=assessment['color'],
                                       fontName='Helvetica-Bold')),
            ],
            [
                Paragraph(assessment['message'],
                         ParagraphStyle('AssessMsg', fontSize=9, textColor=COLORS['text'],
                                       fontName='Helvetica', leading=12))
            ]
        ]

        box = Table(content, colWidths=[self.content_width - 20])
        box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), assessment['bg']),
            ('BOX', (0, 0), (-1, -1), 2, assessment['color']),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ]))
        return box

    def create_detailed_results(self, elements: list, data: Dict[str, Any]):
        """Create detailed results table section."""
        elements.append(self.create_section_header("DETAILED ANALYSIS RESULTS", "🔬"))

        stats = data.get('statistics', {})
        cell_counts = stats.get('cell_counts_by_class', {})
        area_stats = stats.get('area_stats', {})
        total = stats.get('total_cells', 0)

        healthy = cell_counts.get('healthy', 0)
        affected = cell_counts.get('affected', 0)
        irrelevant = cell_counts.get('irrelevant', 0)

        # Cell Distribution Table
        elements.append(Paragraph("<b>Cell Classification Results</b>", self.styles['SubsectionHeader']))

        dist_header = ['Classification', 'Count', 'Percentage', 'Reference Range', 'Assessment']
        dist_data = [
            dist_header,
            ['Healthy Cells', str(healthy), f"{healthy/max(total,1)*100:.1f}%", '> 60%',
             self._assess_range(healthy/max(total,1)*100, 60, 100)],
            ['Affected Cells (Apoptotic)', str(affected), f"{affected/max(total,1)*100:.1f}%", '< 20%',
             self._assess_range(affected/max(total,1)*100, 0, 20)],
            ['Irrelevant/Debris', str(irrelevant), f"{irrelevant/max(total,1)*100:.1f}%", '< 25%',
             self._assess_range(irrelevant/max(total,1)*100, 0, 25)],
            ['Total Analyzed', str(total), '100%', '—', '—'],
        ]

        dist_table = Table(dist_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 3.5*cm, 3.5*cm])
        dist_table.setStyle(self._get_results_table_style(len(dist_data)))
        elements.append(dist_table)
        elements.append(Spacer(1, 5*mm))

        # Morphological Statistics Table
        elements.append(Paragraph("<b>Morphological Statistics</b>", self.styles['SubsectionHeader']))

        morph_header = ['Parameter', 'Value', 'Unit', 'Interpretation']
        morph_data = [
            morph_header,
            ['Mean Cell Area', f"{area_stats.get('mean', 0):,.1f}", 'px²', 'Average cell size'],
            ['Median Cell Area', f"{area_stats.get('median', 0):,.1f}", 'px²', 'Central tendency'],
            ['Standard Deviation', f"{area_stats.get('std', 0):,.1f}", 'px²', 'Size variability'],
            ['Coefficient of Variation', f"{area_stats.get('cv_percent', 0):.1f}", '%',
             'High' if area_stats.get('cv_percent', 0) > 100 else 'Normal'],
            ['Minimum Area', f"{area_stats.get('min', 0):,.1f}", 'px²', 'Smallest cell'],
            ['Maximum Area', f"{area_stats.get('max', 0):,.1f}", 'px²', 'Largest cell'],
        ]

        morph_table = Table(morph_data, colWidths=[5*cm, 4*cm, 2*cm, 6*cm])
        morph_table.setStyle(self._get_results_table_style(len(morph_data)))
        elements.append(morph_table)
        elements.append(Spacer(1, 3*mm))

    def _assess_range(self, value: float, min_ref: float, max_ref: float) -> str:
        """Return assessment string based on reference range."""
        if min_ref <= value <= max_ref:
            return '✓ Within Range'
        elif value < min_ref:
            return '↓ Below Range'
        else:
            return '↑ Above Range'

    def _get_results_table_style(self, num_rows: int) -> TableStyle:
        """Get consistent table style for results tables."""
        style_commands = [
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), COLORS['primary']),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['white']),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),

            # Data styling
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),

            # Borders
            ('BOX', (0, 0), (-1, -1), 1, COLORS['primary']),
            ('LINEBELOW', (0, 0), (-1, 0), 2, COLORS['primary']),
            ('LINEBELOW', (0, 1), (-1, -2), 0.5, COLORS['border']),

            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLORS['white'], COLORS['background']]),
        ]
        return TableStyle(style_commands)

    def create_visual_analysis(self, elements: list):
        """Create visual analysis section with images."""
        elements.append(self.create_section_header("VISUAL ANALYSIS", "🖼️"))

        # Main visualization - Overlay
        overlay_path = SCRIPT_DIR / "overlay_predict.png"
        if overlay_path.exists():
            resized = self.resize_image_for_report(overlay_path, 14*cm, 10*cm)
            if resized:
                elements.append(Spacer(1, 3*mm))

                # Image with border
                img = RLImage(resized, width=14*cm, height=10*cm)
                img_table = Table([[img]], colWidths=[14.5*cm])
                img_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('BOX', (0, 0), (-1, -1), 1, COLORS['border']),
                    ('BACKGROUND', (0, 0), (-1, -1), COLORS['white']),
                    ('TOPPADDING', (0, 0), (-1, -1), 5),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ]))

                container = Table([[img_table]], colWidths=[self.content_width])
                container.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ]))
                elements.append(container)

                elements.append(Paragraph(
                    "<b>Figure 1:</b> Segmentation overlay showing cell classification. "
                    "<font color='#27AE60'>Green: Healthy</font>, "
                    "<font color='#E74C3C'>Red: Affected/Apoptotic</font>, "
                    "<font color='#F39C12'>Yellow: Irrelevant/Debris</font>",
                    self.styles['Caption']
                ))

        # Statistical charts grid
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("<b>Statistical Distribution Analysis</b>", self.styles['SubsectionHeader']))

        chart_images = [
            ('1_cell_area_distribution_kde.png', 'Cell Area Distribution (KDE)'),
            ('2_cell_area_boxplot.png', 'Cell Area Boxplot'),
            ('3_cumulative_distribution.png', 'Cumulative Distribution'),
            ('4_cell_size_categories.png', 'Size Category Distribution'),
        ]

        image_row = []
        caption_row = []

        for img_name, caption in chart_images:
            img_path = SCRIPT_DIR / img_name
            if img_path.exists():
                resized = self.resize_image_for_report(img_path, 4*cm, 3.2*cm)
                if resized:
                    img = RLImage(resized, width=4*cm, height=3.2*cm)
                    img_cell = Table([[img]], colWidths=[4.1*cm])
                    img_cell.setStyle(TableStyle([
                        ('BOX', (0, 0), (-1, -1), 0.5, COLORS['border']),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ]))
                    image_row.append(img_cell)
                    caption_row.append(Paragraph(caption, self.styles['Caption']))

        if image_row:
            charts_table = Table([image_row, caption_row], colWidths=[4.25*cm]*len(image_row))
            charts_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            container = Table([[charts_table]], colWidths=[self.content_width])
            container.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), COLORS['background']),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ]))
            elements.append(container)

        elements.append(Spacer(1, 3*mm))

    def create_interpretation_section(self, elements: list):
        """Create AI clinical interpretation section."""
        elements.append(self.create_section_header("CLINICAL INTERPRETATION", "🧠"))

        interpretation = self.get_ai_interpretation()

        # Format interpretation in a nice box
        interp_box = Table([
            [Paragraph(f"<i>{interpretation}</i>", self.styles['Interpretation'])]
        ], colWidths=[self.content_width - 10])

        interp_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), COLORS['light_blue']),
            ('BOX', (0, 0), (-1, -1), 1, COLORS['accent']),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
        ]))
        elements.append(interp_box)
        elements.append(Spacer(1, 3*mm))


    def create_disclaimer_section(self, elements: list):
        """Create legal disclaimer and notes section."""
        disclaimer_text = """
        <b>DISCLAIMER:</b> This report is generated by an automated analysis system and is intended for research
        purposes only. Results should be interpreted by qualified personnel in conjunction with clinical findings
        and other diagnostic information. This analysis does not constitute a medical diagnosis. The accuracy of
        automated cell classification may vary based on image quality and sample preparation. All measurements
        are in pixel units unless otherwise specified. For clinical decision-making, please consult with qualified
        healthcare professionals.
        """

        disclaimer_box = Table([
            [Paragraph(disclaimer_text, self.styles['Disclaimer'])]
        ], colWidths=[self.content_width])

        disclaimer_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FDF2E9')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#E59866')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(disclaimer_box)
        elements.append(Spacer(1, 5*mm))

    def create_footer_section(self, elements: list):
        """Create professional footer with signatures."""
        elements.append(HRFlowable(
            width="100%", thickness=1, color=COLORS['border'],
            spaceBefore=5*mm, spaceAfter=3*mm
        ))

        # Signature area
        sig_data = [
            [
                Paragraph("<b>Analyzed By:</b>", self.styles['SmallText']),
                Paragraph("Automated System", self.styles['SmallText']),
                Paragraph("<b>Reviewed By:</b>", self.styles['SmallText']),
                Paragraph("_____________________", self.styles['SmallText']),
            ],
            [
                Paragraph("<b>Date:</b>", self.styles['SmallText']),
                Paragraph(datetime.now().strftime('%Y-%m-%d'), self.styles['SmallText']),
                Paragraph("<b>Date:</b>", self.styles['SmallText']),
                Paragraph("_____________________", self.styles['SmallText']),
            ]
        ]

        sig_table = Table(sig_data, colWidths=[3*cm, 5*cm, 3*cm, 6*cm])
        sig_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(sig_table)
        elements.append(Spacer(1, 5*mm))

        # Final footer
        footer_text = f"""
        <b>Cell Morphology Analysis System v1.0</b> | Designed by Atalay ŞAHAN &amp; Gülce Nur Evren<br/>
        Report ID: {self.report_id} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
        © 2024 Apoptosis Detection System. For research use only.
        """
        elements.append(Paragraph(footer_text, self.styles['Footer']))

        # Bottom decorative line
        elements.append(Spacer(1, 2*mm))
        elements.append(HRFlowable(
            width="100%", thickness=3, color=COLORS['primary']
        ))

    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Generate the complete professional PDF report."""
        # Load data
        data = self.load_analysis_data()
        if not data:
            raise ValueError("No analysis data available. Please run an analysis first.")

        # Output path
        if output_path is None:
            output_path = str(SCRIPT_DIR / f"CellMorphology_Report_{self.report_id}.pdf")

        # Create document with custom page setup
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=self.margin,
            leftMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin
        )

        # Build elements
        elements = []

        self.create_header_section(elements)
        self.create_sample_info_section(elements, data)
        self.create_executive_summary(elements, data)
        self.create_detailed_results(elements, data)

        # Page break before visuals
        elements.append(PageBreak())

        self.create_visual_analysis(elements)
        self.create_interpretation_section(elements)
        self.create_disclaimer_section(elements)
        self.create_footer_section(elements)

        # Build PDF
        doc.build(elements)

        # Cleanup temp images
        for temp_file in SCRIPT_DIR.glob("_temp_report_*.jpg"):
            try:
                temp_file.unlink()
            except:
                pass

        print(f"Report saved to: {output_path}")
        return output_path


# Backward compatibility alias
ReportGenerator = MedicalReportGenerator


def main():
    """Generate a report from the command line."""
    print("=" * 60)
    print("  Cell Morphology Analysis - Professional Report Generator")
    print("=" * 60)
    print()

    generator = MedicalReportGenerator()

    try:
        output_path = generator.generate_report()
        print(f"\n[OK] Report successfully generated!")
        print(f"  Location: {output_path}")
    except Exception as e:
        print(f"\n[ERROR] Error generating report: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
