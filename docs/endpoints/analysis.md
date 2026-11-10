# Analysis Endpoints

## Prefix
`/api/v1/analysis/`

## `GET /api/v1/analysis/reports/`
- Purpose: List generated reports for an organization.
- Query params:
	- `org_id` (required)
	- `page`, `page_size` (optional)
	- `report_type` (`weekly|monthly|custom`) and `search` (name contains) — optional filters
- Request body: none.
- Response shape: DRF pagination with `results` containing:

```json
{"id": 15, "name": "April Performance", "created_at": "2026-04-10T10:00:00Z", "report_type": "monthly", "file": "/media/reports/report-15.pdf", "status": "COMPLETED", "start_date": "2026-04-01", "end_date": "2026-04-30", "included_platforms": [], "included_metrics": ["spend"]}
```

## `GET /api/v1/analysis/report-insights/`
- Purpose: Highlights for the Reports sidebar.
- Query params: `org_id` (required), `start_date`, `end_date` (optional, `YYYY-MM-DD`; default last 30 days).
- Response:

```json
{"period": {"start_date": "2026-10-12", "end_date": "2026-11-10"}, "top_campaign": {"name": "Summer Sale", "roas": 4.62}, "total_spend": 11506.5, "conversion_rate": 2.35, "total_impressions": 2450000}
```

- `top_campaign` is `null` when nothing has been spent in the period.

## `GET /api/v1/analysis/scheduled-reports/`
- Purpose: Recurring reports for the organization. The three default schedules are created on first request.
- Query params: `org_id` (required).
- Response: `{"count": 3, "results": [{"id": 1, "title": "Weekly Performance Report", "schedule": "Every Monday at 9:00 AM", "frequency": "weekly", "enabled": true, "included_metrics": []}]}`

## `PATCH /api/v1/analysis/scheduled-reports/<id>/`
- Purpose: Toggle a schedule (`{"enabled": false}`). Requires `OWNER`/`ADMIN`.
- Query params: `org_id` (required).
- TODO: nothing generates scheduled reports yet — only the setting is stored.

## `POST /api/v1/analysis/generate-report/`
- Purpose: Queue async report generation task.
- Query params:
	- `org_id` (required)
- Request body:

```json
{
	"report_type": "custom",
	"included_platforms": ["META", "TIKTOK"],
	"included_metrics": ["spend", "impressions", "roas"],
	"start_date": "2026-04-01",
	"end_date": "2026-04-10"
}
```

- Response:

```json
{"message": "Generating report, you will get a notification when completed.", "report_id": 42}
```

- Validation rules:
	- `report_type` must be one of `weekly`, `monthly`, `custom`.
	- `start_date` and `end_date` are required only for `custom`.
	- platforms must be in `META`, `TIKTOK`, `GOOGLE`.
	- metrics must be in `spend`, `impressions`, `clicks`, `ctr`, `cpc`, `cpm`, `conversions`, `cpa`, `roas`.

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
