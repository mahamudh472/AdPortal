from django.db.models import QuerySet, Model
from django.utils import timezone
from datetime import timedelta
from accounts.models import User

def get_percentage(new:int, old:int) -> str:
    if old == 0:
        return "100%"
    return f"{((new-old)/old)*100}%"

def get_last_month_objects_count(queryset) -> int:
    past_date = timezone.now() - timedelta(days=7)
    if queryset.model is User:
        return queryset.filter(joined_at__gte=past_date).count()
    return queryset.filter(created_at__gte=past_date).count()


def get_second_last_month_objects_count(queryset):
    start_date = timezone.now() - timedelta(days=14)
    end_date = timezone.now() - timedelta(days=7)
    if queryset.model is User:
        return queryset.filter(joined_at__gte=start_date, joined_at__lte=end_date).count()
    return queryset.filter(created_at__gte=start_date, created_at__lte=end_date).count()

if __name__ == "__main__":
    val = get_percentage(120, 100)
    print(val)