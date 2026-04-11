# Main Endpoints

## Prefix
`/api/v1/main/`

## Common Requirements
- Authentication: `Authorization: Bearer <access_token>`.
- Most endpoints require query param `org_id`.

## Organization and Dashboard

### `GET /api/v1/main/dashboard/`
- Query params: `org_id`.
- Request body: none.
- Response: dashboard summary object.

### `GET /api/v1/main/organization/`
- Query params: `org_id`.
- Response example:

```json
{"snowflake_id": "org_123", "name": "Acme", "website": "https://acme.com", "industry": "SaaS", "company_size": "11-50"}
```

### `PUT/PATCH /api/v1/main/organization/`
- Query params: `org_id`.
- Request body: any updatable organization fields.
- Response: updated organization object.

## Campaign Lifecycle

### `GET /api/v1/main/campaigns/`
- Query params: `org_id`, `search`, `status`, `page`, `page_size`.
- Response: paginated campaign list.

### `GET /api/v1/main/campaign/<int:id>/`
### `PUT/PATCH /api/v1/main/campaign/<int:id>/`
### `DELETE /api/v1/main/campaign/<int:id>/`
- Query params: `org_id`.
- Path params: `id`.
- Request body for update: campaign serializer fields.
- Delete response: HTTP `204`.

### `POST /api/v1/main/campaign/<int:id>/toggle-status/`
- Query params: `org_id`.
- Request body: none.
- Response example:

```json
{"campaign_id": 12, "status": "PAUSED", "message": "Campaign is now paused. Platform changes are being applied in the background."}
```

### `POST /api/v1/main/create-ad/`
### `POST /api/v1/main/update-ad/`
- Query params: `org_id`.
- Request body: `CreateAdSerializer` payload (JSON or multipart with `ad_file`).
- Example payload:

```json
{
  "campaign_id": 123,
  "platforms": ["META", "TIKTOK"],
  "campaign_name": "Summer Promo",
  "objective": "TRAFFIC",
  "budgets": [{"platform": "META", "budget_type": "DAILY", "start_date": "2026-04-10", "end_date": "2026-04-30", "budget": 5000, "run_continuously": false}],
  "min_age": 18,
  "max_age": 45,
  "gender": "all",
  "locations": ["BD"],
  "keywords": "marketing, ecommerce",
  "ad_name": "Promo Ad 1",
  "headline": "Boost Your Sales",
  "primary_text": "Run better ads with AI.",
  "description": "Try now",
  "call_to_action": "LEARN_MORE",
  "destination_url": "https://example.com",
  "draft": true
}
```

- Response: campaign state object including `campaign_id`, `status`, and campaign fields.

## Integrations

### `GET /api/v1/main/integrations-status/`
- Query params: `org_id`.
- Response:

```json
{"integrations": [{"platform": "META", "status": true, "created_at": "..."}, {"platform": "GOOGLE", "status": false, "created_at": null}]}
```

### `GET /api/v1/main/get-ad-profiles/`
- Query params: `org_id`, `platform` (`META|TIKTOK|GOOGLE`).
- Response: external ad account profile list from provider API.

### `POST /api/v1/main/select-ad-profile/`
- Query params: `org_id`.
- Request body:

```json
{"platform": "META", "acc_id": "act_123456"}
```

- Response:

```json
{"success": "Ad account selected."}
```

### `GET /api/v1/main/get-meta-pages/`
- Query params: `org_id`.
- Response: managed page list.

### `POST /api/v1/main/select-meta-page/`
- Query params: `org_id`.
- Request body:

```json
{"page_id": "123456789"}
```

- Response:

```json
{"success": "Facebook Page selected.", "page_id": "123456789"}
```

### `POST /api/v1/main/disconnect-integration/`
- Query params: `org_id`.
- Request body:

```json
{"platform": "META"}
```

- Response:

```json
{"success": "META integration disconnected."}
```

## AI Tools

### `POST /api/v1/main/generate-ai-copy/`
- Query params: `org_id`.
- Request body:

```json
{"product": "CRM", "audience": "SMB owners", "benefits": "Automation", "tone": "Professional", "copy_type": "Headlines"}
```

- Response:

```json
{"generated_copies": ["..."]}
```

### `POST /api/v1/main/generate-ad-copy/`
- Query params: `org_id`.
- Request body:

```json
{"product_service": "CRM", "target_audience": "SMB owners", "key_benefits": "Automation", "tone": "Professional"}
```

- Response:

```json
{"Ad copy": "..."}
```

### `GET /api/v1/main/ai-insights/`
- Query params: `org_id`, `page`, `page_size`.
- Response: paginated AI insight objects.

## Analytics and Sync

### `GET /api/v1/main/analytics/`
- Query params: `org_id`.
- Response: organization analytics payload.

### `POST /api/v1/main/sync-ads/`
- Query params: `org_id`.
- Request body: none.
- Response:

```json
{"message": "Ad sync initiated successfully"}
```

### `POST /api/v1/main/sync-analytics/`
- Query params: `org_id`.
- Request body (optional filters):

```json
{"platform": "META", "start_date": "2026-04-01", "end_date": "2026-04-10"}
```

- Response:

```json
{"message": "Analytics sync initiated for 1 integration(s)."}
```

## Team Management

### `GET /api/v1/main/team/`
- Query params: `org_id`.
- Response:

```json
{"total_members": 8, "active_members": 7, "inactive_members": 1, "pending_invitations": 2}
```

### `GET /api/v1/main/team-members/`
- Query params: `org_id`.
- Response: list of team members.

### `GET/PUT/PATCH/DELETE /api/v1/main/team-member/<str:id>/`
- Query params: `org_id`.
- Path params: `id`.
- Update request body example:

```json
{"role": "ADMIN"}
```

### `POST /api/v1/main/invite-team-member/`
- Query params: `org_id`.
- Request body:

```json
{"email": "newmember@example.com", "role": "MEMBER"}
```

- Response:

```json
{"message": "Invitation sent successfully"}
```

### `POST /api/v1/main/accept-invitation/<str:token>/`
- Path params: `token`.
- Request body: none.
- Response:

```json
{"message": "You have successfully joined the organization ..."}
```

## Platform Test Endpoints (Meta)

### `POST /api/v1/main/meta/create-ad/`
- Query params: `org_id`.
- Request body:

```json
{"campaign_id": 123, "ad_asset_id": 9}
```

- Response:

```json
{"message": "Meta ad created successfully.", "ad_id": 456, "platform_ad_id": "...", "ad_name": "..."}
```

### `POST /api/v1/main/meta/update-campaign/`
- Query params: `org_id`.
- Request body:

```json
{"campaign_id": 123, "ad_asset_id": 9}
```

- Response:

```json
{"message": "Meta campaign updated successfully."}
```

### `POST /api/v1/main/meta/delete-ad/`
- Query params: `org_id`.
- Request body:

```json
{"campaign_id": 123, "delete_level": "CAMPAIGN"}
```

- Response:

```json
{"message": "Meta campaign deleted successfully."}
```

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
