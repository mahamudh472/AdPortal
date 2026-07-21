import logging
from celery import shared_task
from io import BytesIO
from django.core.files.base import ContentFile
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

logger = logging.getLogger(__name__)

HEADER_STYLE_COLOR = "4472C4"


def _style_header_row(sheet, headers):
    """Apply bold white text on blue background to the first row."""
    for col_num, header in enumerate(headers, 1):
        cell = sheet.cell(row=1, column=col_num, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=HEADER_STYLE_COLOR, end_color=HEADER_STYLE_COLOR, fill_type="solid")


def _auto_width(sheet):
    """Auto-size column widths."""
    for col in sheet.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_len:
                    max_len = len(str(cell.value))
            except Exception:
                pass
        sheet.column_dimensions[col_letter].width = min(max_len + 2, 50)


def _safe_val(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


# ── Sheet builders ────────────────────────────────────────────────────────────

def _build_revenue_overview(wb, payments_qs):
    from django.db.models import Sum, Count
    from django.db.models.functions import TruncDate

    ws = wb.create_sheet("Revenue Overview")
    headers = ["Date", "Revenue", "Transaction Count"]
    _style_header_row(ws, headers)

    rows = (
        payments_qs.filter(status="paid")
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(revenue=Sum("amount"), count=Count("id"))
        .order_by("day")
    )

    for row_num, r in enumerate(rows, 2):
        ws.cell(row=row_num, column=1, value=_safe_val(r["day"]))
        ws.cell(row=row_num, column=2, value=float(r["revenue"] or 0))
        ws.cell(row=row_num, column=3, value=r["count"])

    _auto_width(ws)


def _build_revenue_by_plan(wb, payments_qs):
    from django.db.models import Sum, Count

    ws = wb.create_sheet("Revenue by Plan")
    headers = ["Plan", "Total Revenue", "Transaction Count"]
    _style_header_row(ws, headers)

    rows = (
        payments_qs.filter(status="paid")
        .values("subscription__plan__name")
        .annotate(revenue=Sum("amount"), count=Count("id"))
        .order_by("subscription__plan__name")
    )

    for row_num, r in enumerate(rows, 2):
        plan_name = r["subscription__plan__name"] or "No Plan"
        ws.cell(row=row_num, column=1, value=plan_name)
        ws.cell(row=row_num, column=2, value=float(r["revenue"] or 0))
        ws.cell(row=row_num, column=3, value=r["count"])

    _auto_width(ws)


def _build_user_growth(wb, start_date, end_date):
    from apps.accounts.models import User
    from django.db.models import Count
    from django.db.models.functions import TruncDate

    ws = wb.create_sheet("User Growth")
    headers = ["Date", "New Users"]
    _style_header_row(ws, headers)

    rows = (
        User.objects.filter(joined_at__date__gte=start_date, joined_at__date__lte=end_date)
        .annotate(day=TruncDate("joined_at"))
        .values("day")
        .annotate(new_users=Count("id"))
        .order_by("day")
    )

    for row_num, r in enumerate(rows, 2):
        ws.cell(row=row_num, column=1, value=_safe_val(r["day"]))
        ws.cell(row=row_num, column=2, value=r["new_users"])

    _auto_width(ws)


def _build_feature_usage(wb, start_date, end_date):
    from apps.finance.models import UsageRecord

    ws = wb.create_sheet("Feature Usage")
    headers = ["Organization", "Feature Key", "Used", "Period Start", "Period End"]
    _style_header_row(ws, headers)

    records = UsageRecord.objects.filter(
        period_start__date__gte=start_date,
        period_end__date__lte=end_date,
    ).select_related("organization").order_by("organization__name", "feature_key")

    for row_num, rec in enumerate(records, 2):
        ws.cell(row=row_num, column=1, value=rec.organization.name)
        ws.cell(row=row_num, column=2, value=rec.feature_key)
        ws.cell(row=row_num, column=3, value=rec.used)
        ws.cell(row=row_num, column=4, value=_safe_val(rec.period_start))
        ws.cell(row=row_num, column=5, value=_safe_val(rec.period_end))

    _auto_width(ws)


def _build_monthly_revenue(wb, payments_qs):
    from django.db.models import Sum, Count
    from django.db.models.functions import TruncMonth

    ws = wb.create_sheet("Monthly Revenue")
    headers = ["Month", "Revenue", "Transaction Count"]
    _style_header_row(ws, headers)

    rows = (
        payments_qs.filter(status="paid")
        .annotate(month=TruncMonth("paid_at"))
        .values("month")
        .annotate(revenue=Sum("amount"), count=Count("id"))
        .order_by("month")
    )

    for row_num, r in enumerate(rows, 2):
        ws.cell(row=row_num, column=1, value=_safe_val(r["month"]))
        ws.cell(row=row_num, column=2, value=float(r["revenue"] or 0))
        ws.cell(row=row_num, column=3, value=r["count"])

    _auto_width(ws)


def _build_mrr_growth(wb, start_date, end_date):
    """
    Compute MRR per month as the sum of plan prices for subscriptions
    whose current_period_start <= first day of month <= current_period_end.
    """
    from apps.finance.models import Subscription
    from django.db.models import Sum
    import datetime

    ws = wb.create_sheet("MRR Growth")
    headers = ["Month", "MRR", "Growth %"]
    _style_header_row(ws, headers)

    # Build a list of months between start_date and end_date
    months = []
    current = start_date.replace(day=1)
    end = end_date.replace(day=1)
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    mrr_values = []
    for month_start in months:
        mrr = (
            Subscription.objects.filter(
                status__in=["active", "trialing"],
                current_period_start__date__lte=month_start,
                current_period_end__date__gte=month_start,
            )
            .aggregate(mrr=Sum("plan__price"))["mrr"] or 0
        )
        mrr_values.append((month_start, float(mrr)))

    prev_mrr = None
    for row_num, (month, mrr) in enumerate(mrr_values, 2):
        if prev_mrr is not None and prev_mrr > 0:
            growth = round(((mrr - prev_mrr) / prev_mrr) * 100, 2)
        else:
            growth = 0

        ws.cell(row=row_num, column=1, value=_safe_val(month))
        ws.cell(row=row_num, column=2, value=mrr)
        ws.cell(row=row_num, column=3, value=growth)
        prev_mrr = mrr

    _auto_width(ws)


def _build_total_transactions(wb, payments_qs):
    ws = wb.create_sheet("Total Transactions")
    headers = ["Date", "Organization", "Amount", "Currency", "Status", "Stripe Payment Intent"]
    _style_header_row(ws, headers)

    records = payments_qs.select_related("organization").order_by("-created_at")

    for row_num, rec in enumerate(records, 2):
        ws.cell(row=row_num, column=1, value=_safe_val(rec.created_at))
        ws.cell(row=row_num, column=2, value=rec.organization.name)
        ws.cell(row=row_num, column=3, value=float(rec.amount))
        ws.cell(row=row_num, column=4, value=rec.currency)
        ws.cell(row=row_num, column=5, value=rec.status)
        ws.cell(row=row_num, column=6, value=rec.stripe_payment_intent_id or "")

    _auto_width(ws)


def _build_failed_payments(wb, payments_qs):
    ws = wb.create_sheet("Failed Payments")
    headers = ["Date", "Organization", "Amount", "Currency", "Stripe Payment Intent"]
    _style_header_row(ws, headers)

    records = payments_qs.filter(status="failed").select_related("organization").order_by("-created_at")

    for row_num, rec in enumerate(records, 2):
        ws.cell(row=row_num, column=1, value=_safe_val(rec.created_at))
        ws.cell(row=row_num, column=2, value=rec.organization.name)
        ws.cell(row=row_num, column=3, value=float(rec.amount))
        ws.cell(row=row_num, column=4, value=rec.currency)
        ws.cell(row=row_num, column=5, value=rec.stripe_payment_intent_id or "")

    _auto_width(ws)


# ── Metric dispatch map ───────────────────────────────────────────────────────

METRIC_BUILDERS = {
    "revenue_overview": lambda wb, payments, start, end: _build_revenue_overview(wb, payments),
    "revenue_by_plan": lambda wb, payments, start, end: _build_revenue_by_plan(wb, payments),
    "user_growth": lambda wb, payments, start, end: _build_user_growth(wb, start, end),
    "feature_usage": lambda wb, payments, start, end: _build_feature_usage(wb, start, end),
    "monthly_revenue": lambda wb, payments, start, end: _build_monthly_revenue(wb, payments),
    "mrr_growth": lambda wb, payments, start, end: _build_mrr_growth(wb, start, end),
    "total_transactions": lambda wb, payments, start, end: _build_total_transactions(wb, payments),
    "failed_payments": lambda wb, payments, start, end: _build_failed_payments(wb, payments),
}


@shared_task(bind=True, max_retries=3)
def generate_admin_report_task(self, report_id):
    """Background task to generate an admin-level Excel analytics report."""
    from .models import AdminReport
    from apps.finance.models import Payment

    try:
        report = AdminReport.objects.get(id=report_id)
        included_metrics = [m.lower() for m in (report.included_metrics or [])]

        # If no metrics selected, include all
        if not included_metrics:
            included_metrics = list(METRIC_BUILDERS.keys())

        payments_qs = Payment.objects.filter(
            created_at__date__gte=report.start_date,
            created_at__date__lte=report.end_date,
        )

        wb = Workbook()
        # Remove default empty sheet
        default_sheet = wb.active
        wb.remove(default_sheet)

        for metric in included_metrics:
            builder = METRIC_BUILDERS.get(metric)
            if builder:
                builder(wb, payments_qs, report.start_date, report.end_date)

        # Fallback: if no sheets were added, add a blank one
        if not wb.sheetnames:
            wb.create_sheet("No Data")

        filename = (
            f"admin_{report.report_type}_report_"
            f"{report.start_date.strftime('%Y%m%d')}_"
            f"{report.end_date.strftime('%Y%m%d')}.xlsx"
        )

        excel_file = BytesIO()
        wb.save(excel_file)
        content = excel_file.getvalue()
        file_size = len(content)

        report.file.save(filename, ContentFile(content), save=False)
        report.name = filename
        report.status = AdminReport.Status.COMPLETED
        report.file_size = file_size
        report.save()

        logger.info("Admin report %s generated successfully.", report_id)

    except Exception as exc:
        logger.exception("Admin report generation failed for report_id=%s", report_id)
        try:
            report = AdminReport.objects.get(id=report_id)
            report.status = AdminReport.Status.FAILED
            report.save(update_fields=["status"])
        except AdminReport.DoesNotExist:
            pass
        raise self.retry(exc=exc, countdown=60)
