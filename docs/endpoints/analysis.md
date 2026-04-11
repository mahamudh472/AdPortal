# Analysis Endpoints

## Prefix
`/api/v1/analysis/`

## `GET /api/v1/analysis/reports/`
- Purpose: List generated reports for an organization.
- Query params:
	- `org_id` (required)
	- `page`, `page_size` (optional)
- Request body: none.
- Response shape: DRF pagination with `results` containing:

```json
{"id": 15, "name": "April Performance", "created_at": "2026-04-10T10:00:00Z", "report_type": "monthly", "file": "/media/reports/report-15.pdf"}
```

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
