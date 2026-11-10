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
- Purpose: Return organization payment history (requires `OWNER`/`ADMIN`).
- Query params:
	- `org_id` (required)
- Request body: none.
- Response example:

```json
[
	{"id": 7, "date": "2026-04-01T06:00:00Z", "description": "Starter Plan - Monthly Subscription", "period": {"start": "2026-04-01T06:00:00Z", "end": "2026-05-01T06:00:00Z"}, "amount": "79.00", "currency": "USD", "status": "Paid", "paid_at": "2026-04-01T06:00:00Z", "has_invoice": true}
]
```

- `status` is one of `Paid`, `Pending`, `Failed`, `Refunded`. `has_invoice` is true when a Stripe invoice exists for the payment.

## `GET /api/v1/finance/invoices/<payment_id>/download/`
- Purpose: Resolve the Stripe-hosted PDF for one payment (requires `OWNER`/`ADMIN`).
- Query params: `org_id` (required).
- Response: `{"url": "https://pay.stripe.com/invoice/.../pdf"}`; `404` when the payment has no invoice.

## `GET /api/v1/finance/invoices/download-all/`
- Purpose: ZIP archive of every available invoice PDF (requires `OWNER`/`ADMIN`).
- Query params: `org_id` (required).
- Response: `application/zip` (`invoices.zip`); `404` when there is nothing to download.

## `POST /api/v1/finance/stripe/webhook/`
- Purpose: Stripe server-to-server webhook receiver.
- Query params: none.
- Headers:
	- `Stripe-Signature` (required)
- Request body: raw Stripe event payload.
- Response: HTTP `200` on successful processing.

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
