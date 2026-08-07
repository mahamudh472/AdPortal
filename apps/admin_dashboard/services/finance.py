from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from apps.finance.models import Payment, Subscription, Plan
from django.utils.dateparse import parse_date

def get_finance_overview_data(start_date=None, end_date=None):
    now = timezone.now()

    # Parse dates if they are strings
    if start_date and isinstance(start_date, str):
        start_date = parse_date(start_date)
    if end_date and isinstance(end_date, str):
        end_date = parse_date(end_date)

    # If start_date and end_date are not provided, default to the last 6 months
    # (so we have a complete 6 months span as default)
    if not start_date or not end_date:
        # Default start date is 5 months ago replacement day=1 (making 6 calendar months in total)
        current_year = now.year
        current_month = now.month
        first_month_num = current_month - 5
        first_year = current_year
        while first_month_num <= 0:
            first_month_num += 12
            first_year -= 1
        
        default_start = now.replace(
            year=first_year, month=first_month_num, day=1,
            hour=0, minute=0, second=0, microsecond=0
        )
        if not start_date:
            start_date = default_start.date()
        if not end_date:
            end_date = now.date()

    # ── Selected Period Calculations ──────────────────────────────────────
    # Convert dates to datetimes for timezone-aware filters
    start_dt = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end_dt = timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))

    # Monthly revenue (revenue for the selected period, paid payments)
    monthly_revenue = (
        Payment.objects.filter(status='paid', paid_at__gte=start_dt, paid_at__lte=end_dt)
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )

    # ── MRR growth (%) vs previous period of same duration ─────────────────
    duration = end_date - start_date
    prev_end_date = start_date - timedelta(days=1)
    prev_start_date = prev_end_date - duration
    
    prev_start_dt = timezone.make_aware(timezone.datetime.combine(prev_start_date, timezone.datetime.min.time()))
    prev_end_dt = timezone.make_aware(timezone.datetime.combine(prev_end_date, timezone.datetime.max.time()))

    last_month_revenue = (
        Payment.objects.filter(
            status='paid',
            paid_at__gte=prev_start_dt,
            paid_at__lte=prev_end_dt,
        )
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )

    if last_month_revenue == 0:
        mrr_growth = 100.0 if monthly_revenue > 0 else 0.0
    else:
        mrr_growth = round(
            float((monthly_revenue - last_month_revenue) / last_month_revenue * 100), 2
        )

    # ── Total transactions & failed payments in selected period ────────────────
    total_transactions = Payment.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt).count()
    failed_payments = Payment.objects.filter(status='failed', created_at__gte=start_dt, created_at__lte=end_dt).count()

    # ── Revenue overview & sparklines – last 6 calendar months or 6 intervals ──
    revenue_overview = {}
    spark_monthly_revenue = []
    spark_mrr_growth = []
    spark_total_transactions = []
    spark_failed_payments = []

    # We split the selected period into 6 sub-intervals
    step = duration / 5
    for i in range(6):
        current_point_date = start_date + step * i
        label = current_point_date.strftime('%b %d')
        
        # Window start/end
        window_size = max(timedelta(days=1), step)
        sub_start_date = current_point_date - window_size
        sub_end_date = current_point_date
        
        sub_start_dt = timezone.make_aware(timezone.datetime.combine(sub_start_date, timezone.datetime.min.time()))
        sub_end_dt = timezone.make_aware(timezone.datetime.combine(sub_end_date, timezone.datetime.max.time()))

        # Window metrics
        win_revenue = Payment.objects.filter(
            status='paid',
            paid_at__gte=sub_start_dt,
            paid_at__lte=sub_end_dt
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        revenue_overview[label] = float(win_revenue)
        spark_monthly_revenue.append(float(win_revenue))

        win_transactions = Payment.objects.filter(
            created_at__gte=sub_start_dt,
            created_at__lte=sub_end_dt
        ).count()
        spark_total_transactions.append(win_transactions)

        win_failed = Payment.objects.filter(
            status='failed',
            created_at__gte=sub_start_dt,
            created_at__lte=sub_end_dt
        ).count()
        spark_failed_payments.append(win_failed)

        # Window growth vs previous window
        prev_sub_start_date = sub_start_date - window_size
        prev_sub_end_date = sub_start_date
        prev_sub_start_dt = timezone.make_aware(timezone.datetime.combine(prev_sub_start_date, timezone.datetime.min.time()))
        prev_sub_end_dt = timezone.make_aware(timezone.datetime.combine(prev_sub_end_date, timezone.datetime.max.time()))
        
        prev_win_revenue = Payment.objects.filter(
            status='paid',
            paid_at__gte=prev_sub_start_dt,
            paid_at__lte=prev_sub_end_dt
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        if prev_win_revenue == 0:
            win_growth = 100.0 if win_revenue > 0 else 0.0
        else:
            win_growth = round(float((win_revenue - prev_win_revenue) / prev_win_revenue * 100), 2)
        spark_mrr_growth.append(win_growth)

    sparklines = {
        'monthly_revenue': spark_monthly_revenue,
        'mrr_growth': spark_mrr_growth,
        'total_transactions': spark_total_transactions,
        'failed_payments': spark_failed_payments,
    }

    # ── Payment Summary Breakdown in selected period ───────────────────────
    successful_pmts = Payment.objects.filter(status='paid', paid_at__gte=start_dt, paid_at__lte=end_dt)
    successful_count = successful_pmts.count()
    successful_total = successful_pmts.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    failed_pmts = Payment.objects.filter(status='failed', created_at__gte=start_dt, created_at__lte=end_dt)
    failed_count = failed_pmts.count()
    failed_total = failed_pmts.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    refunded_pmts = Payment.objects.filter(status='refunded', created_at__gte=start_dt, created_at__lte=end_dt)
    refunded_count = refunded_pmts.count()
    refunded_total = refunded_pmts.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    payment_summary = {
        'successful': { 'count': successful_count, 'total': float(successful_total) },
        'failed': { 'count': failed_count, 'total': float(failed_total) },
        'refunded': { 'count': refunded_count, 'total': float(refunded_total) },
    }

    # ── Revenue by plan in selected period ──────────────────────────────────
    revenue_by_plan = {}
    for plan in Plan.objects.filter(is_active=True):
        subscribers = Subscription.objects.filter(
            plan=plan, status__in=['active', 'trialing']
        ).count()

        plan_revenue = (
            Payment.objects.filter(
                status='paid', 
                subscription__plan=plan,
                paid_at__gte=start_dt,
                paid_at__lte=end_dt
            )
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        revenue_by_plan[plan.name] = {
            'subscribers': subscribers,
            'revenue': float(plan_revenue),
        }

    return {
        'monthly_revenue': float(monthly_revenue),
        'mrr_growth': mrr_growth,
        'total_transactions': total_transactions,
        'failed_payments': failed_payments,
        'sparklines': sparklines,
        'payment_summary': payment_summary,
        'revenue_overview': revenue_overview,
        'revenue_by_plan': revenue_by_plan,
    }
