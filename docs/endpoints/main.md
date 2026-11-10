# Main Endpoints

## Prefix
`/api/v1/main/`

## Common Requirements
- Authentication: `Authorization: Bearer <access_token>`.
- Most endpoints require query param `org_id`.

## Organization and Dashboard

### `GET /api/v1/main/dashboard/`
- Query params: `org_id` (required), `time_range` (`last_7_days`, `last_30_days`, `this_month`, `last_month`, `all_time`), `start_date`, `end_date`.
- Request body: none.
- Response: comprehensive dynamic dashboard payload containing `date_range`, `platform_cards`, `overview_metrics`, `chart_data`, `top_campaigns`, `ai_insights`, `budget_recommendation`, as well as legacy summary fields.

### `POST /api/v1/main/apply-budget-recommendation/`
- Query params: `org_id` (required).
- Request body:
```json
{
  "campaign_id": 12,
  "increase_amount": 50.0
}
```
- Response:
```json
{
  "status": "success",
  "message": "Budget recommendation applied successfully for 'Summer Sale 2024'!",
  "campaign_id": 12,
  "campaign_name": "Summer Sale 2024",
  "increase_amount": 50.0,
  "new_daily_budget": 550.0
}
```

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
- Response: paginated campaign list. Besides the campaign fields and totals (`total_budget`, `total_spent`, `impressions`, `clicks`, `conversions`, `ctr`, `roas`) each row has:
  - `ctr_trend`, `conversions_trend`, `roas_trend`: last 7 days vs the 7 days before, formatted like `"↑ 12.5%"` / `"↓ 2.1%"`; `null` when neither period has data.
  - `sparkline_data`: daily clicks for the last 7 days (oldest first).

### `GET /api/v1/main/campaign/<int:id>/`
### `PUT/PATCH /api/v1/main/campaign/<int:id>/`
### `DELETE /api/v1/main/campaign/<int:id>/`
- Query params: `org_id`.
- Path params: `id`.
- Request body for update: campaign serializer fields.
- Delete response: HTTP `204`.
- The GET response also includes `placements`: spend share per platform, `[{"platform": "META", "label": "Meta", "spend": 75.0, "impressions": 1000, "clicks": 50, "percent": 75.0}]` (empty until analytics have synced).

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
- Send `{"campaign_id": 123, "draft": false}` to publish a draft campaign (all required fields must already be saved). The campaign wizard's final step does this.

## Integrations

### `GET /api/v1/main/integrations-status/`
- Query params: `org_id`.
- Response:

```json
{"integrations": [{"platform": "META", "status": true, "created_at": "..."}, {"platform": "GOOGLE", "status": false, "created_at": null}]}
```

### `GET /api/v1/main/get-ad-profiles/`
- Query params: `org_id`, `platform` (`META|TIKTOK|GOOGLE`).
- Meta-only required query param: `page_id`.
- Response: external ad account profile list from provider API.

Meta example:

`GET /api/v1/main/get-ad-profiles/?org_id=<ORG_ID>&platform=META&page_id=123456789`

### `POST /api/v1/main/select-ad-profile/`
- Query params: `org_id`.
- Request body:

```json
{"platform": "META", "acc_id": "act_123456", "page_id": "123456789"}
```

- Response:

```json
{"success": "Ad account selected.", "ad_account_id": "act_123456", "page_id": "123456789"}
```

- For `META`, the selected `acc_id` must belong to the provided `page_id`.

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
- Query params: `org_id`, `page`, `page_size` (max 20).
- Response: paginated insights plus page-level summary data used by AI Tools → Optimization:

```json
{
  "count": 2, "next": null, "previous": null,
  "last_optimization": "2026-11-10T08:30:00Z",
  "summary": {"active_insights": 2, "high_priority": 1, "applied_today": 0, "est_savings": 0.0},
  "potential_impact": {"conversions": "+25%", "cost_per_result": "-15%", "roas": "+18%"},
  "results": [{
    "id": 1, "campaign": 4, "campaign_name": "Summer Sale", "title": "...", "description": "...",
    "impact": "HIGH", "created_at": "...",
    "metrics": [{"label": "CTR", "value": "3.40%"}, {"label": "CPC", "value": "$0.45"}],
    "campaigns_count": 1, "action_text": "Apply Suggestion", "action_type": "apply"
  }]
}
```

- `metrics` are the campaign's real CTR/CPC for the last 30 days.
- TODO: `summary.applied_today`, `summary.est_savings`, `potential_impact` and the `action_*` fields are placeholders (action is derived from `impact`) until applied optimizations are tracked.

### `GET/PATCH /api/v1/main/ai-optimization/settings/`
- Query params: `org_id`. PATCH requires an `OWNER`/`ADMIN`.
- Body / response:

```json
{"auto_optimization": true, "optimization_mode": "balanced", "optimization_frequency": "Daily Optimization", "last_optimization": null}
```

- `optimization_mode`: `conservative` | `balanced` | `aggressive`. `optimization_frequency`: `Daily Optimization` | `Weekly Optimization` | `Real-time Optimization`.

### `GET /api/v1/main/ai-optimization/history/`
- Query params: `org_id`.
- Response: `{"count": 3, "results": [{"id": "h-1", "title": "...", "time": "...", "impact": "...", "status": "Applied"}]}`
- TODO: illustrative entries (only for organizations that have campaigns) until optimizations are logged.

### `POST /api/v1/main/ai-optimization/run/`
- Query params: `org_id`. Powers the "Optimize Now" button.
- Response: the settings object above plus a `message`.
- TODO: currently only records `last_optimization`; the analysis itself still needs to be dispatched as a Celery task.

### `POST /api/v1/main/audience-reach-estimate/`
- Query params: `org_id`.
- Request body (all optional): `min_age`, `max_age` (13-65), `gender` (`all|male|female`), `locations` (list), `keywords`.
- Response: `{"min_reach": 630000, "max_reach": 960000, "min_label": "630K", "max_label": "960K", "progress": 63, "is_estimate": true}`
- TODO: heuristic; replace with the platforms' reach-estimate APIs.

## Analytics and Sync

### `GET /api/v1/main/analytics/`
- Query params: `org_id`, `range` (`7D`, `30D`, `3M`, `6M` default, `1Y`; only changes `monthly_performance`).
- Response:

```json
{
  "top_metrics": {"total_spend": {"value": 0, "change_percent": 0, "sparkline": [0,0,0,0,0,0]}, "impressions": {...}, "click_rate": {...}, "conversions": {...}},
  "monthly_performance": {"Nov": {"clicks": 0, "conversions": 0, "impressions": 0}},
  "spend_by_platform": {"META": 0, "GOOGLE": 0, "TIKTOK": 0},
  "device_performance": {"mobile": {"clicks": 0, "impressions": 0}},
  "insights_summary": {
    "top_performing_platform": {"platform": "TIKTOK", "label": "TikTok", "value": "4.00x ROAS"},
    "most_conversions_platform": null, "best_click_rate_platform": null, "lowest_cost_per_conversion": null
  }
}
```

- `top_metrics` compare the current calendar month with the previous one; `sparkline` is the last 6 calendar months (oldest first).
- `monthly_performance` is bucketed daily for `7D`/`30D` and monthly otherwise.
- `insights_summary` covers the last 6 months; an entry is `null` when no platform qualifies.

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

## Testing Endpoints

### `POST /api/v1/main/test/create-ad-on-platform/`
- Query params: `org_id`.
- Purpose: trigger provider-side ad creation for one existing unified campaign on one platform.
- Request body:

```json
{"platform": "META", "campaign_id": 123, "ad_asset_id": 45}
```

- Notes:
- `platform` must be `META`, `TIKTOK`, or `GOOGLE`.
- `ad_asset_id` is optional (currently used by META/GOOGLE handlers).
- For `TIKTOK`, local `PlatformCampaign` and `AdGroup` must already exist for that campaign.

- Success response examples:

```json
{"message": "Meta ad creation triggered successfully.", "platform": "META", "campaign_id": 123, "ad_id": 998, "platform_ad_id": "1201234567890"}
```

```json
{"message": "Google ad creation triggered successfully.", "platform": "GOOGLE", "campaign_id": 123, "ad_id": 1002, "platform_ad_id": "customers/1234567890/adGroupAds/111~222"}
```

```json
{"message": "TikTok campaign/adgroup creation triggered successfully.", "platform": "TIKTOK", "campaign_id": 123, "platform_campaign_id": "1851326442807426", "platform_adgroup_id": "1851326442807427"}
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
- Response: list of team members: `{"id", "user", "role", "status", "joined_at", "last_active_at"}` (`joined_at` = account creation, `last_active_at` = last login; either may be `null`).
- `pending_invitations` in `GET /team/` counts open (non-expired) `TeamInvitation` rows.

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
