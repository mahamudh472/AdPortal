from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = 'apps.finance'

    def ready(self):
        from django.core.cache import cache
        from django.db.models.signals import post_delete, post_save
        from .models import Plan, PlanFeature

        def _invalidate(**kwargs):
            cache.delete('finance:plans:list')

        for model in (Plan, PlanFeature):
            post_save.connect(_invalidate, sender=model, weak=False, dispatch_uid=f'plans_cache_{model.__name__}_s')
            post_delete.connect(_invalidate, sender=model, weak=False, dispatch_uid=f'plans_cache_{model.__name__}_d')
