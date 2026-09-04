"""Leave approval letter PDF with QR verification."""

import io
import secrets

import qrcode
from django.http import HttpResponse
from django.urls import reverse

from .models import LeaveApprovalDocument, LeaveApprovalStage, LeaveRequest, LeaveStepStatus


def ensure_approval_document(leave_request: LeaveRequest) -> LeaveApprovalDocument:
    doc, created = LeaveApprovalDocument.objects.get_or_create(
        leave_request=leave_request,
        defaults={
            "reference_number": LeaveApprovalDocument.build_reference(leave_request),
            "verification_code": secrets.token_urlsafe(24),
        },
    )
    if not created and not doc.verification_code:
        doc.verification_code = secrets.token_urlsafe(24)
        doc.save(update_fields=["verification_code"])
    return doc


def approval_letter_pdf_response(leave_request: LeaveRequest, request=None) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    doc_record = ensure_approval_document(leave_request)
    from apps.system_settings.services import branding
    company = branding()["COMPANY_NAME"]
    emp = leave_request.employee
    stand_in = leave_request.stand_in_employee

    verify_url = ""
    if request:
        verify_url = request.build_absolute_uri(
            reverse("leave:verify", kwargs={"ref": doc_record.reference_number})
        )

    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16, alignment=1, spaceAfter=6)
    subtitle = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=11, alignment=1, spaceAfter=14)
    label = ParagraphStyle("Label", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    value = ParagraphStyle("Value", parent=styles["Normal"], fontSize=10, spaceAfter=4)

    elements = [
        Paragraph(company.upper(), title),
        Paragraph("LEAVE APPROVAL LETTER", subtitle),
        Paragraph(f"<b>Reference No:</b> {doc_record.reference_number}", value),
        Spacer(1, 0.4 * cm),
    ]

    def row(label_text, val):
        return [Paragraph(label_text, label), Paragraph(str(val or "—"), value)]

    info = [
        row("Employee", f"{emp.full_name}"),
        row("Employee ID", emp.employee_id),
        row("Department", emp.department.name if emp.department else "—"),
        row("Designation", emp.designation.title if emp.designation else "—"),
        row("Leave Type", leave_request.leave_type.name),
        row("Duration", f"{leave_request.days_requested} day(s)"),
        row("Start Date", leave_request.start_date.strftime("%d %B %Y")),
        row("End Date", leave_request.end_date.strftime("%d %B %Y")),
        row("Resumption Date", leave_request.resumption_date.strftime("%d %B %Y")),
        row("Stand-in Officer", stand_in.full_name if stand_in else "—"),
        row("Stand-in Department", stand_in.department.name if stand_in and stand_in.department else "—"),
    ]

    for step in leave_request.approval_steps.filter(status=LeaveStepStatus.APPROVED):
        actor = step.acted_by.get_full_name() if step.acted_by else "Approved"
        info.append(row(step.get_stage_display(), f"Approved — {actor}"))

    info.append(row("Approval Date", leave_request.reviewed_at.strftime("%d %B %Y") if leave_request.reviewed_at else "—"))

    table = Table(info, colWidths=[5 * cm, 11 * cm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.6 * cm))

    if leave_request.handover_notes:
        elements.append(Paragraph("<b>Handover Notes</b>", value))
        elements.append(Paragraph(leave_request.handover_notes.replace("\n", "<br/>"), styles["Normal"]))
        elements.append(Spacer(1, 0.4 * cm))

    elements.append(Paragraph(
        "This letter confirms that the above leave has been fully approved in accordance with company policy.",
        styles["Italic"],
    ))
    elements.append(Spacer(1, 0.8 * cm))
    elements.append(Paragraph("<b>Authorized Signature — HR Manager</b>", value))
    elements.append(Spacer(1, 0.3 * cm))

    if verify_url:
        qr_img = qrcode.make(verify_url, box_size=4, border=1)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        elements.append(Image(qr_buf, width=3 * cm, height=3 * cm))
        elements.append(Paragraph("Scan to verify authenticity", label))

    pdf.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="leave_approval_{doc_record.reference_number}.pdf"'
    )
    return response
