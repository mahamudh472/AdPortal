# AdPortal API Endpoint Index

## Base URL
`/api/v1`

## Quick Navigation
- [Project and OAuth Endpoints](#project-and-oauth-endpoints)
- [Accounts Endpoints](#accounts-endpoints)
- [Main Endpoints](#main-endpoints)
- [Analysis Endpoints](#analysis-endpoints)
- [Finance Endpoints](#finance-endpoints)
- [Admin Dashboard Endpoints](#admin-dashboard-endpoints)

## Project and OAuth Endpoints

| Method | Full Path | Details |
|---|---|---|
| GET | `/admin/` | [Project details](./endpoints/project.md) |
| GET | `/api/schema/` | [Project details](./endpoints/project.md) |
| GET | `/api/schema/swagger-ui/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/meta/connect/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/meta/callback/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/tiktok/connect/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/tiktok/callback/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/google/connect/` | [Project details](./endpoints/project.md) |
| GET | `/api/v1/auth/google/callback/` | [Project details](./endpoints/project.md) |

## Accounts Endpoints

| Method | Full Path | Details |
|---|---|---|
| POST | `/api/v1/accounts/login/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/logout/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/token/refresh/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/register/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/verify-email/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/resend-otp/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/password-reset/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/check-otp/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/password-reset-confirm/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/change-password/` | [Accounts details](./endpoints/accounts.md) |
| GET | `/api/v1/accounts/profile/` | [Accounts details](./endpoints/accounts.md) |
| PATCH | `/api/v1/accounts/profile/update/` | [Accounts details](./endpoints/accounts.md) |
| GET | `/api/v1/accounts/notifications/` | [Accounts details](./endpoints/accounts.md) |
| GET, PATCH | `/api/v1/accounts/notification-settings/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/read-notification/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/read-all-notifications/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/delete-notification/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/delete-all-notifications/` | [Accounts details](./endpoints/accounts.md) |
| DELETE | `/api/v1/accounts/delete-account/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/test-notifications/` | [Accounts details](./endpoints/accounts.md) |
| POST | `/api/v1/accounts/contact-us/` | [Accounts details](./endpoints/accounts.md) |

## Main Endpoints

| Method | Full Path | Details |
|---|---|---|
| GET | `/api/v1/main/dashboard/` | [Main details](./endpoints/main.md) |
| GET, PUT, PATCH | `/api/v1/main/organization/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/integrations-status/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/campaigns/` | [Main details](./endpoints/main.md) |
| GET, PUT, PATCH, DELETE | `/api/v1/main/campaign/<int:id>/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/campaign/<int:id>/toggle-status/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/create-ad/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/update-ad/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/get-ad-profiles/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/select-ad-profile/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/get-meta-pages/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/select-meta-page/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/disconnect-integration/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/generate-ai-copy/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/generate-ad-copy/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/ai-insights/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/analytics/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/create-platform-campaign/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/team/` | [Main details](./endpoints/main.md) |
| GET | `/api/v1/main/team-members/` | [Main details](./endpoints/main.md) |
| GET, PUT, PATCH, DELETE | `/api/v1/main/team-member/<str:id>/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/invite-team-member/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/accept-invitation/<str:token>/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/sync-ads/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/sync-analytics/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/meta/create-ad/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/meta/update-campaign/` | [Main details](./endpoints/main.md) |
| POST | `/api/v1/main/meta/delete-ad/` | [Main details](./endpoints/main.md) |

## Analysis Endpoints

| Method | Full Path | Details |
|---|---|---|
| GET | `/api/v1/analysis/reports/` | [Analysis details](./endpoints/analysis.md) |
| POST | `/api/v1/analysis/generate-report/` | [Analysis details](./endpoints/analysis.md) |

## Finance Endpoints

| Method | Full Path | Details |
|---|---|---|
| GET | `/api/v1/finance/get-plans/` | [Finance details](./endpoints/finance.md) |
| POST | `/api/v1/finance/buy-plan/` | [Finance details](./endpoints/finance.md) |
| GET | `/api/v1/finance/get-current-plan/` | [Finance details](./endpoints/finance.md) |
| GET | `/api/v1/finance/billing-history/` | [Finance details](./endpoints/finance.md) |
| POST | `/api/v1/finance/stripe/webhook/` | [Finance details](./endpoints/finance.md) |

## Admin Dashboard Endpoints

| Method | Full Path | Details |
|---|---|---|
| GET | `/api/v1/admin/dashboard/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/campaigns/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/user-management/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/user-management-list/` | [Admin details](./endpoints/admin_dashboard.md) |
| PUT, PATCH | `/api/v1/admin/user-management/<uuid:id>/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/organizations/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/transactions/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET, PUT, PATCH | `/api/v1/admin/notification-settings/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/reports/` | [Admin details](./endpoints/admin_dashboard.md) |
| POST | `/api/v1/admin/reports/<int:report_id>/download/` | [Admin details](./endpoints/admin_dashboard.md) |
| POST | `/api/v1/admin/generate-report/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/finance/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET | `/api/v1/admin/platform-analysis/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET, POST | `/api/v1/admin/contact-messages/` | [Admin details](./endpoints/admin_dashboard.md) |
| GET, PUT, PATCH, DELETE | `/api/v1/admin/contact-messages/<id>/` | [Admin details](./endpoints/admin_dashboard.md) |

## Notes
- This file is the consolidated endpoint list for the entire project.
- Detailed per-app documentation remains available in `docs/endpoints/`.
