"""
Google Ads Engine
=================

Public interface for the google_engine package.

Manage (create / update / delete / toggle):
    from apps.main.utils.google_engine import (
        create_ad_on_google,
        update_campaign_on_google,
        delete_ad_on_google,
        toggle_campaign_status_on_google,
    )

Sync (pull campaigns / ad groups / ads from Google Ads):
    from apps.main.utils.google_engine import sync_google_integration

Analytics (fetch daily performance → AnalysisDaily):
    from apps.main.utils.google_engine import (
        generate_google_campaign_analysis,
        generate_google_adgroup_analysis,
    )
"""

from .manage_ad import (
    create_ad_on_google,
    update_campaign_on_google,
    delete_ad_on_google,
    toggle_campaign_status_on_google,
    GoogleAdError,
)

from .sync_ad import (
    sync_google_integration,
    fetch_google_campaigns,
    upsert_google_campaigns,
    sync_google_adgroups,
    sync_google_ads,
)

from .analysis import (
    generate_google_campaign_analysis,
    generate_google_adgroup_analysis,
)

__all__ = [
    # manage
    "create_ad_on_google",
    "update_campaign_on_google",
    "delete_ad_on_google",
    "toggle_campaign_status_on_google",
    "GoogleAdError",
    # sync
    "sync_google_integration",
    "fetch_google_campaigns",
    "upsert_google_campaigns",
    "sync_google_adgroups",
    "sync_google_ads",
    # analytics
    "generate_google_campaign_analysis",
    "generate_google_adgroup_analysis",
]
