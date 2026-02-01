from django.db import models
from django.conf import settings

from main.models import Organization

User = settings.AUTH_USER_MODEL


class Plan(models.Model):
    PLAN_CHOICES = (
        ("starter", "Starter"),
        ("growth", "Growth"),
        ("scale", "Scale"),
    )

    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    interval = models.CharField(
        max_length=10,
        choices=(("month", "Monthly"), ("year", "Yearly")),
        default="month",
    )

    stripe_price_id = models.CharField(
        max_length=255, blank=True, null=True
    )

    is_active = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (${self.price}/{self.interval})"
    
    def get_campaign_limit(self):
        if self.name == "starter":
            return self.features.filter(key="feature_1").first().value.split()[0]
        elif self.name == "growth":
            return self.features.filter(key="feature_2").first().value.split()[0]
        elif self.name == "scale":
            return 'Unlimited'

class PlanFeature(models.Model):
    plan = models.ForeignKey(
        Plan, related_name="features", on_delete=models.CASCADE
    )

    key = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.plan.name} | {self.key} = {self.value}"

class Subscription(models.Model):
    STATUS_CHOICES = (
        ("active", "Active"),
        ("trialing", "Trialing"),
        ("past_due", "Past Due"),
        ("canceled", "Canceled"),
        ("incomplete", "Incomplete"),
    )

    organization = models.ForeignKey(
        Organization, related_name="subscriptions", on_delete=models.CASCADE
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT
    )

    stripe_subscription_id = models.CharField(
        max_length=255, blank=True, null=True
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="trialing"
    )

    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)

    cancel_at_period_end = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.organization} → {self.plan.name} ({self.status})"

    @property
    def is_active(self):
        return self.status == "active"
class Payment(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    )

    organization = models.ForeignKey(
        Organization, related_name="payments", on_delete=models.CASCADE
    )

    subscription = models.ForeignKey(
        Subscription,
        related_name="payments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    stripe_payment_intent_id = models.CharField(
        max_length=255, blank=True, null=True
    )
    stripe_invoice_id = models.CharField(
        max_length=255, blank=True, null=True
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES
    )

    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    raw_payload = models.JSONField(blank=True, null=True)

    def __str__(self):
        return f"{self.organization} | {self.amount} {self.currency} | {self.status}"

class UsageRecord(models.Model):
    organization = models.ForeignKey(
        Organization, related_name="usage_records", on_delete=models.CASCADE
    )

    subscription = models.ForeignKey(
        Subscription,
        related_name="usage_records",
        on_delete=models.CASCADE
    )

    feature_key = models.CharField(max_length=100)
    used = models.PositiveIntegerField(default=0)

    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    class Meta:
        unique_together = (
            "organization",
            "feature_key",
            "period_start",
            "period_end",
        )

    def __str__(self):
        return f"{self.organization} | {self.feature_key} = {self.used}"



