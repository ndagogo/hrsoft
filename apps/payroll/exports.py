"""Payslip PDF and bank schedule exports."""

import io
from decimal import Decimal

from django.http import HttpResponse

from apps.core.exports import build_csv_response, build_excel_response


def payslip_pdf_response(payslip):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=18, spaceAfter=12)
    from apps.system_settings.services import branding
    brand = branding()
    currency = brand["COMPANY_CURRENCY_SYMBOL"]
    company = brand["COMPANY_NAME"]
    emp = payslip.employee
    period = payslip.period

    elements = [
        Paragraph(company, title_style),
        Paragraph(f"Payslip — {period.name}", styles["Normal"]),
        Spacer(1, 0.5 * cm),
        Paragraph(f"<b>Employee:</b> {emp.full_name} ({emp.employee_id})", styles["Normal"]),
        Paragraph(f"<b>Department:</b> {emp.department.name if emp.department else '—'}", styles["Normal"]),
        Paragraph(f"<b>Period:</b> {period.start_date} to {period.end_date}", styles["Normal"]),
        Paragraph(f"<b>Attendance:</b> {payslip.days_present} present · {payslip.days_late} late · {payslip.days_absent} absent", styles["Normal"]),
        Spacer(1, 0.8 * cm),
    ]

    def money(val):
        return f"{currency}{Decimal(val):,.2f}"

    data = [
        ["Earnings", "Amount", "Deductions", "Amount"],
        ["Basic salary", money(payslip.basic_salary), "Tax", money(payslip.tax_deduction)],
        ["Housing", money(payslip.housing_allowance), "Pension", money(payslip.pension_deduction)],
        ["Transport", money(payslip.transport_allowance), "Late penalty", money(payslip.late_penalty_deduction)],
        ["Other", money(payslip.other_allowance), "Other", money(payslip.other_deduction)],
        ["Gross pay", money(payslip.gross_pay), "Total deductions", money(payslip.total_deductions)],
        ["", "", "NET PAY", money(payslip.net_pay)],
    ]
    table = Table(data, colWidths=[4 * cm, 3.5 * cm, 4 * cm, 3.5 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (2, -1), (3, -1), "Helvetica-Bold"),
        ("BACKGROUND", (2, -1), (3, -1), colors.HexColor("#f5f5f5")),
    ]))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="payslip_{emp.employee_id}_{period.name.replace(" ", "_")}.pdf"'
    return response


def bank_schedule_response(period, fmt="csv"):
    headers = [
        "employee_id", "employee_name", "bank_name", "account_number",
        "net_pay", "department",
    ]
    rows = []
    for slip in period.payslips.select_related("employee__user", "employee__department").order_by("employee__employee_id"):
        emp = slip.employee
        rows.append([
            emp.employee_id,
            emp.full_name,
            emp.bank_name or "",
            emp.bank_account_number or "",
            str(slip.net_pay),
            emp.department.name if emp.department else "",
        ])
    prefix = f"bank_schedule_{period.name.replace(' ', '_')}"
    if fmt == "xlsx":
        return build_excel_response(f"{prefix}.xlsx", headers, rows)
    return build_csv_response(f"{prefix}.csv", headers, rows)
