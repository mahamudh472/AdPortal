# Admin Dashboard Endpoints

## Prefix
`/api/v1/admin/`

## Authentication
- All endpoints in this file require admin authentication (`IsAdminUser`).

## `GET /api/v1/admin/dashboard/`
- Purpose: Global admin summary (users, campaigns, chart data, recent campaigns).
- Query params: none.
- Request body: none.
- Example response:

```json
{
	"users": {"value": 120, "past_month": 25, "percentage": 18.5},
	"campaings": {"value": 540, "last_month": 90, "percentage": 12.0},
	"revenue": {"value": 0, "percentage": 0},
	"chart_data": [{"month": "Jan", "users": 2000, "revenue": 2400}],
	"campaings_by_platform": {"meta": 200, "google": 190, "tiktok": 150},
	"recent_campaigns": []
}
```

## `GET /api/v1/admin/campaigns/`
- Purpose: List all campaigns for admins.
- Query params: `page`, `page_size`.
- Request body: none.
- Example response: DRF paginated campaign payload (`count`, `next`, `previous`, `results`).

## `GET /api/v1/admin/user-management/`
- Purpose: User management KPIs.
- Query params: none.
- Request body: none.
- Example response:

```json
{
	"total_users": {"value": 500, "last_week": 12},
	"active_users": 430,
	"suspended_users": 8,
	"trial_users": 0
}
```

## `GET /api/v1/admin/user-management-list/`
- Purpose: Paginated user list.
- Query params:
	- `search` (optional): email/full name search.
	- `page`, `page_size`.
- Request body: none.
- Example item in `results`:

```json
{"id": "uuid", "full_name": "Jane", "email": "jane@example.com", "status": "active", "joined_at": "...", "last_login": "..."}
```

## `PUT/PATCH /api/v1/admin/user-management/<uuid:id>/`
- Purpose: Change user account status.
- Path params: `id` (user UUID).
- Request body:

```json
{"status": "active"}
```

- Allowed statuses: `active`, `inactive`, `suspended`.
- Example success response:

```json
{"message": "User status updated to active."}
```

- Common errors:
	- `400`: invalid status.
	- `400`: attempting to change superuser status.

## `GET /api/v1/admin/organizations/stats/`
- Purpose: Retrieve statistics and metrics for organizations by status.
- Query params: none.
- Request body: none.
- Example response:

```json
{
	"total_organizations": 10,
	"active_organizations": {
		"value": 5,
		"previous_period": 4,
		"trend_percentage": "+25.0%",
		"trend_direction": "up"
	},
	"suspended_organizations": {
		"value": 2,
		"previous_period": 3,
		"trend_percentage": "-25.0%",
		"trend_direction": "down"
	},
	"trial_organizations": {
		"value": 3,
		"previous_period": 3,
		"trend_percentage": "0%",
		"trend_direction": "neutral"
	}
}
```

## `GET /api/v1/admin/organizations/`
- Purpose: List organizations.
- Query params: `search` (optional), `status` (optional), `page`, `page_size`.
- Request body: none.
- Example response: DRF paginated organization list.

## `PATCH /api/v1/admin/organizations/<str:snowflake_id>/`
- Purpose: Update the status of a specific organization.
- Path params: `snowflake_id` (string).
- Request body:
```json
{
	"status": "suspended"
}
```
- Allowed statuses: `active`, `suspended`, `trial` (case-insensitive).
- Example success response:
```json
{
	"message": "Organization status updated to SUSPENDED successfully.",
	"status": "SUSPENDED"
}
```

## `DELETE /api/v1/admin/organizations/<str:snowflake_id>/`
- Purpose: Delete a specific organization.
- Path params: `snowflake_id` (string).
- Request body: none.
- Example response: `204 No Content`.


## `GET /api/v1/admin/transactions/`
- Purpose: List payments/transactions.
- Query params: `page`, `page_size`.
- Request body: none.
- Example response: DRF paginated `PaymentSerializer` list.

## `GET /api/v1/admin/notification-settings/`
- Purpose: Get current admin notification settings.
- Query params: none.
- Request body: none.
- Example response: `AdminNotificationSettings` object.

## `PUT/PATCH /api/v1/admin/notification-settings/`
- Purpose: Update admin notification settings.
- Query params: none.
- Request body: partial `AdminNotificationSettings` fields.
- Example success response: updated settings object.

## `GET /api/v1/admin/reports/`
- Purpose: List generated admin reports.
- Query params: `page`, `page_size`.
- Request body: none.
- Example response item:

```json
{
	"id": 12,
	"name": "Q1 Report",
	"report_type": "quarterly",
	"status": "COMPLETED",
	"included_metrics": ["revenue_overview"],
	"start_date": "2026-01-01",
	"end_date": "2026-03-31",
	"file": "...",
	"file_size": 14520,
	"download_count": 3,
	"generated_by": "b8f6c5e2-76a1-432a-92bc-02198d5e12f0"
}
```

## `POST /api/v1/admin/reports/<int:report_id>/download/`
- Purpose: Increment the download count for a specific admin report when downloaded.
- Path params: `report_id` (integer).
- Query params: none.
- Request body: none.
- Example success response:

```json
{
	"message": "Download count incremented.",
	"download_count": 4
}
```

## `POST /api/v1/admin/generate-report/`
- Purpose: Queue async generation of admin analytics report.
- Query params: none.
- Request body:

```json
{
	"report_type": "weekly",
	"included_metrics": ["revenue_overview", "user_growth"],
	"start_date": "2026-01-01",
	"end_date": "2026-01-31"
}
```

- Notes:
	- `report_type` allowed: `weekly`, `monthly`, `quarterly`, `custom`.
	- `start_date` and `end_date` required only when `report_type=custom`.
- Example success response:

```json
{"message": "Admin report is being generated. Check back shortly.", "report_id": 42}
```

## `GET /api/v1/admin/finance/`
- Purpose: Finance overview and revenue analytics.
- Query params: none.
- Request body: none.
- Example response:

```json
{
	"monthly_revenue": 999.0,
	"mrr_growth": 15.2,
	"total_transactions": 340,
	"failed_payments": 5,
	"revenue_overview": {"Nov": 300.0, "Dec": 350.0},
	"revenue_by_plan": {"Starter": {"subscribers": 12, "revenue": 1200.0}}
}
```

## `GET /api/v1/admin/platform-analysis/`
- Purpose: Platform-wide feature usage and user growth.
- Query params: none.
- Request body: none.
- Example response:

```json
{
	"user_growth": [{"month": "Jan", "new_users": 20, "active_users": 130}],
	"feature_usage": [{"feature": "Campaign Creation", "usage": 78.2}]
}
```

## `GET /api/v1/admin/contact-messages/`
- Purpose: List contact-us messages.
- Query params: `search`, `page`.
- Request body: none.
- Example response: DRF paginated contact messages.

## `POST /api/v1/admin/contact-messages/`
- Purpose: Create contact message record via admin API.
- Query params: none.
- Request body: ContactUsMessage fields.
- Example response: created message object.

## `GET /api/v1/admin/contact-messages/<id>/`
- Purpose: Retrieve one contact message.
- Path params: `id`.
- Request body: none.
- Example response: contact message object.

## `PUT/PATCH /api/v1/admin/contact-messages/<id>/`
- Purpose: Update one contact message.
- Path params: `id`.
- Request body: partial ContactUsMessage fields.
- Example response: updated message object.

## `DELETE /api/v1/admin/contact-messages/<id>/`
- Purpose: Delete one contact message.
- Path params: `id`.
- Request body: none.
- Example response: HTTP `204` no body.

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
