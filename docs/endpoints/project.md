# Project and OAuth Endpoints

## Base
- API base: `/api/v1`

## `GET /admin/`
- Purpose: Django admin panel.
- Auth: Django admin session auth.
- Response: HTML page.

## `GET /api/schema/`
- Purpose: OpenAPI schema endpoint.
- Response: OpenAPI JSON document.

## `GET /api/schema/swagger-ui/`
- Purpose: Swagger UI for API exploration.
- Response: HTML page.

## OAuth Connect Endpoints

### `GET /api/v1/auth/meta/connect/`
### `GET /api/v1/auth/tiktok/connect/`
### `GET /api/v1/auth/google/connect/`
- Purpose: Generate provider-specific OAuth consent URL.
- Query params:
	- `org_id` (required)
- Request body: none.
- Response example:

```json
{"redirect_url": "https://provider.example/oauth?..."}
```

## OAuth Callback Endpoints

### `GET /api/v1/auth/meta/callback/`
### `GET /api/v1/auth/tiktok/callback/`
### `GET /api/v1/auth/google/callback/`
- Purpose: Provider callback to exchange code and save integration tokens.
- Query params from provider:
	- `code` (required)
	- `state` (required)
- Request body: none.
- Success response:
	- Meta callback redirects to frontend callback path.
	- TikTok/Google callbacks return JSON success payload.

## Notes
- `state` is validated server-side and carries user+organization context.
- These endpoints are part of OAuth flow and should be called via browser/provider redirects.

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
