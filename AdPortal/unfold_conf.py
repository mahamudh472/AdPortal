from django.conf import settings

UNFOLD = {
    "SITE_TITLE": "AdPortal Admin",
    "SITE_HEADER": "AdPortal Administration",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "ENVIRONMENT": "development" if settings.DEBUG else "production",
    "COLORS": {
        "primary": {
            "50": "#eff6ff",
            "100": "#dbeafe",
            "200": "#bfdbfe",
            "300": "#93c5fd",
            "400": "#60a5fa",
            "500": "#3b82f6",
            "600": "#2563eb",
            "700": "#1d4ed8",
            "800": "#1e40af",
            "900": "#1e3a8a",
        },
    },
    "TABS": [
        {
            "models": ["accounts.user"],
            "items": [
                {
                    "title": "Users",
                    "icon": "people",
                    "link": "admin:accounts_user_changelist",
                },
            ],
        },
        {
            "models": ["admin_dashboard.campaign"],
            "items": [
                {
                    "title": "Campaigns",
                    "icon": "rocket_launch",
                    "link": "admin:admin_dashboard_campaign_changelist",
                },
            ],
        },
        {
            "models": ["main.integration"],
            "items": [
                {
                    "title": "Integrations",
                    "icon": "hub",
                    "link": "admin:main_integration_changelist",
                },
            ],
        },
        {
            "models": ["finance.transaction"],
            "items": [
                {
                    "title": "Transactions",
                    "icon": "attach_money",
                    "link": "admin:finance_transaction_changelist",
                },
            ],
        },
        {
            "models": ["analysis.report"],
            "items": [
                {
                    "title": "Reports",
                    "icon": "assessment",
                    "link": "admin:analysis_report_changelist",
                },
            ],
        },
    ],
}
