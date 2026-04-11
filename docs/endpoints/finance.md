# Finance Endpoints

## Prefix
`/api/v1/finance/`

## `GET /api/v1/finance/get-plans/`
- Purpose: List active subscription plans.
- Query params: none.
- Request body: none.
- Response example:

```json
[
	{
		"id": 1,
		"name": "Starter",
		"price": "29.00",
		"description": "Starter plan",
		"interval": "month",
		"features": [{"key": "campaign_limit", "value": "10 campaigns"}]
	}
]
```

## `POST /api/v1/finance/buy-plan/`
- Purpose: Create Stripe checkout session for selected plan.
- Query params:
	- `org_id` (required)
- Request body:

```json
{"plan_id": 1}
```

- Response example:

```json
{"checkout_session_id": "cs_test_...", "client_secret": "seti_..._secret_..."}
```

- Common cases:
	- If active subscription already exists, returns message instead of session.

## `GET /api/v1/finance/get-current-plan/`
- Purpose: Return current active plan and usage summary.
- Query params:
	- `org_id` (required)
- Request body: none.
- Response example:

```json
{"plan_name": "Starter", "campaign_limit": 10, "campaign_used": 3}
```

## `GET /api/v1/finance/billing-history/`
- Purpose: Return organization payment history.
- Query params:
	- `org_id` (required)
- Request body: none.
- Response example:

```json
[
	{"amount": "29.00", "status": "paid", "paid_at": "2026-04-01T06:00:00Z", "invoice_url": "https://billing.example.com/invoices/123"}
]
```

## `POST /api/v1/finance/stripe/webhook/`
- Purpose: Stripe server-to-server webhook receiver.
- Query params: none.
- Headers:
	- `Stripe-Signature` (required)
- Request body: raw Stripe event payload.
- Response: HTTP `200` on successful processing.

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
