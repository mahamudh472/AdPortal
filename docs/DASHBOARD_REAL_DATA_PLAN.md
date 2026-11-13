# Plan: replace placeholder data in the user dashboard with real data

Status: implemented (backend + dashboard frontend) on 2026-11-13. See section 8 for deviations.
Scope: the logged-in user's pages (Dashboard, Analytics, Campaign list/details, AI Optimization, Reports).
Out of scope for now (per product decision): the campaign-wizard guidance panels and the audience-reach estimate.

## 1. Inventory of what is not real today

### 1.1 `get_dashboard_data` (`apps/main/utils/helper.py`)
| # | Field(s) | Today | Real source |
|---|---|---|---|
| D1 | Whole dashboard when the org has no analytics rows | Demo numbers: platform cards, sparklines, metrics, chart, 5 fake campaigns, 3 fake insights | Nothing to show -> return `has_data=false` and empty arrays; frontend renders an empty/connect-your-accounts state |
| D2 | Facebook vs Instagram split | Meta spend x 0.77 / x 0.23 | Meta Insights `publisher_platform` breakdown |
| D3 | Sparklines + `chart_data` | Samples ~7 points, 3 queries per point, skips days | One grouped query per range, every day (or weekly/monthly buckets for long ranges) |
| D4 | `% change` when previous period is 0 | Returns +100% | Return `null` ("new") so the UI shows "-" |
| D5 | `all_time` | Last 365 days | Min(date) of the org's data -> today |
| D6 | `ai_insights[].confidence`, `roi_impact`, `icon_type` | Constants chosen by HIGH/MEDIUM/LOW | Stored on the insight by the AI engine (see 3.1) |
| D7 | `budget_recommendation` | "32% better", "+$1,250", 75% progress, +$50 are literals; campaign = highest spender | Computed from campaign-vs-peer performance (see 3.2) |
| D8 | `spend_overview` months | `today - i*30 days`, month label only | Real calendar months |
| D9 | Currency | "$" hard-coded in strings | `AdIntegration.currency` / `UnifiedCampaign.currency`; do not sum different currencies |

### 1.2 AI Optimization (`apps/main/services/ai.py`, serializers)
| # | Field | Today | Real source |
|---|---|---|---|
| A1 | `applied_today`, `est_savings` | Always 0 | New `AppliedOptimization` log |
| A2 | `potential_impact` (+25% / -15% / +18%) | Literal | Sum of the open insights' projected deltas |
| A3 | `optimization history` | 3 invented entries for any org with a campaign | The `AppliedOptimization` log |
| A4 | `run_optimization` | Only stamps `last_optimization_at` | Celery task running the analysis and persisting insights |
| A5 | Insight `action_text/action_type` | Derived from impact level | Stored recommendation type (BUDGET_SHIFT, PAUSE_AD, REFRESH_CREATIVE, ...) |
| A6 | `apply-budget-recommendation` | Edits the local `CampaignBudget` only | Also pushed to Meta/Google/TikTok (TODO in code) |

### 1.3 Gaps in ingested analytics (they make real data impossible today)
| # | Gap | Where |
|---|---|---|
| G1 | `device_breakdown` is always `{}` in all three ingestors, so Analytics -> device performance is always empty | `meta_engine/analysis.py`, `google_engine/analysis.py`, `tiktok_engine/analysis.py` |
| G2 | No revenue/conversion value column; ROAS is stored and revenue is reverse-engineered as `roas x spend` | `AnalysisDaily` |
| G3 | Meta conversions count only `action_type == "purchase"`; leads, app installs, registrations are ignored, so non-sales objectives always show 0 | `meta_engine/analysis.py` |
| G4 | No `reach` / `frequency`, no video metrics | `AnalysisDaily` |
| G5 | No hour-of-day, age, gender, country, or placement data, so "Best time to advertise", demographics, placements cannot be real | none |
| G6 | One currency assumed everywhere | dashboard strings, sums across integrations |
| G7 | No guarantee of freshness: need to confirm the beat schedule that calls the sync and how far back it re-pulls (not verified in this review) | `apps/main/tasks.py` |

## 2. Data layer (the foundation everything else depends on)

### 2.1 Schema
- `AnalysisDaily` (campaign x day): add `reach` (int, nullable), `frequency` (float, nullable), `conversion_value` (float, revenue), `currency` (char 3), `video_views` (int, nullable), `synced_at`. Keep `roas` but compute it as `conversion_value / spend` at write time.
- New `AnalysisBreakdownDaily`: `organization, unified_campaign, platform, account_id, campaign_id, date, dimension, key, impressions, clicks, spend, conversions, conversion_value`, unique on `(platform, account_id, campaign_id, date, dimension, key)`.
  - `dimension` is one of `publisher_platform | placement | device | hour | age | gender | country`, `key` is the value (for example `instagram`, `mobile`, `14`, `25-34`, `US`).
  - One generic table avoids a new column or table per breakdown, and every new chart becomes a query.
- Keep the legacy `device_breakdown` JSON until the Analytics page reads the new table, then drop it.
- Indexes: `(organization, dimension, date)` and `(unified_campaign, dimension)`.

### 2.2 Ingestion contract (all platforms)
One normalized record shape per platform adapter: `fetch_daily(integration, start, end) -> rows` and `fetch_breakdown(integration, dimension, start, end) -> rows`, so the dashboard code never knows which platform produced a row.

- **Idempotent upserts** (already the pattern) plus a rolling **re-sync window of the last 28 days** on every run, because platforms revise conversions after the fact (attribution windows, conversion lag).
- **Backfill** management command (`sync_analytics --org X --since YYYY-MM-DD`) and a first-sync backfill on connect (up to 13 months, Meta's hourly limit).
- **Celery beat**: every N hours per active integration, staggered; per-integration lock; rate-limit/backoff handling; store `last_synced_at` and the last error on `IntegrationSyncState` and surface "last updated" in the API.
- **Large pulls** use each platform's async/report-job path rather than synchronous paging.
- **Time zone**: store the ad account's time zone on `AdIntegration` and treat `date` as account-local (all three platforms report in account time zone).
- **Currency**: store per row; the dashboard groups totals by currency and shows a banner if an org has mixed currencies (no silent conversion).

### 2.3 Per-platform API mapping
Reviewed against current docs on 2026-11-13. Items marked **(confirm)** could not be verified from the official page in this review and must be checked in the sandbox before building.

**Meta (Marketing API / Insights)**
- Library pin is `facebook-business==24.0.1`; Meta's current docs show `v27.0` in examples. Upgrade the SDK/Graph version first and re-run the sync tests.
- Daily: `level=campaign, time_increment=1`, fields `impressions, clicks, spend, reach, frequency, ctr, cpc, cpm, actions, action_values, purchase_roas`.
  - Conversions = the action types that match the campaign objective (purchase, lead, complete_registration, mobile_app_install, ...) via a mapping table, not just `purchase` (fixes G3).
  - Revenue = matching `action_values` (fixes G2).
- Breakdowns (separate requests, not all combined):
  - `publisher_platform` (+ `platform_position`) -> Facebook vs Instagram vs Audience Network, placements. No restriction noted.
  - `age`, `gender`, `country` -> demographics. No restriction noted.
  - `hourly_stats_aggregated_by_advertiser_time_zone` -> hour of day. 13-month history limit; reach/frequency return 0 with hourly breakdowns; video fields cannot be combined.
  - `impression_device` -> device. **Since 2026-08-06 may be unavailable until the account admin opts in** (Insights Feature Settings, ~24 h to take effect). Plan: detect an empty result, show "enable device data" guidance, never fabricate.
- Revenue/ROAS is only reliable for on-Meta or pixel/CAPI-tracked events; off-Meta action metrics are not returned for region/dma/hourly breakdowns. Document this limit in the UI tooltip.
- **(confirm)** exact `purchase_roas` behavior with breakdowns; the Adligator article about removed breakdowns could not be read (504).

**Google Ads API (GAQL)**
- Latest line is v26 (v26.x minor releases are now frequent); check which version `google-ads` in `requirements.txt` targets and upgrade as one task.
- Daily: existing campaign query plus `metrics.conversions_value`, `metrics.all_conversions` (decide which the dashboard means by "conversions"), `metrics.video_views`, and `segments.date`. Reach/frequency are not available on all campaign types; leave null where absent.
- Breakdowns (separate queries): `segments.device`, `segments.hour`, `segments.ad_network_type` (added in v24.2; this is the Google equivalent of "placements"), `ad_group_criterion` / `age_range_view`, `gender_view`, `geographic_view` for demographics and country. **(confirm)** each resource's metric compatibility in the field reference, since GAQL rejects incompatible segment/metric combinations.
- Money fields are in micros; divide once in the adapter.

**TikTok Business API (v1.3)**
- Endpoint `/open_api/v1.3/report/integrated/get/`; dimensions must include the entity ID for the level plus a time dimension (`stat_time_day` or `stat_time_hour`). The HTTP method differs between third-party examples **(confirm against the official reference; current code already works with one)**.
- Daily: add `reach`, `frequency`, `complete_payment` count and value metrics (`total_complete_payment_rate`, `value_per_complete_payment` appear in connector docs) **(confirm exact value metric names)**; revenue = conversions x value per payment or the platform's value metric if present.
- Hourly: `stat_time_hour` dimension.
- Audience breakdowns (age, gender, country, device/OS): use the audience report type with those dimensions **(confirm; the `platform` dimension on the BASIC report was not confirmed)**.

## 3. Values we generate ourselves

### 3.1 AI insights and their scores (D6, A1-A5)
- Extend `AIInsight`: `recommendation_type`, `params` (JSON: target campaign/ad/platform, suggested change), `expected_delta` (JSON: metric -> % change), `confidence` (0-100), `status` (OPEN/APPLIED/DISMISSED), `applied_at`, `applied_by`.
- **Confidence is computed, not asserted**: rule-based from sample size (impressions/clicks/conversions in the window), effect size vs the org's own median, and consistency across the last 3 weeks. Cap at 95; low data -> low confidence and a "needs more data" flag.
- **ROI impact** = projected change from the rule (for example moving X% of budget from the campaign with ROAS a to one with ROAS b, bounded by a diminishing-returns haircut), expressed as a range, not a point.
- The LLM (already used for copy) only writes the explanation text from the computed numbers; it does not invent figures. Keep the per-org daily cap.
- `AppliedOptimization` log (insight, before/after budget or copy, applied_by, applied_at) powers `applied_today`, `est_savings` (for example budget moved off campaigns whose CPA is above the org median, measured over the following 7 days), and the real history list.
- `run_optimization` becomes a Celery task (the per-campaign tasks already exist) that creates insights and returns a job id; the UI polls.

### 3.2 Budget recommendation card (D7, A6)
- Candidate campaigns: active, at least N days and M conversions of data.
- Score = campaign ROAS (or CPA for non-revenue objectives) relative to the org median and to its own previous 14 days; budget-limited flag (spend >= ~90% of daily budget on most days) decides whether an increase can actually deliver more.
- Display values: "X% better than your other campaigns" (real ratio), potential impact = projected extra conversions/revenue at the suggested increase using the campaign's recent marginal CPA with a haircut, increase amount = clamp(10-30% of current budget). If nothing qualifies, return `null` and the card disappears.
- Apply: write local `CampaignBudget`, then dispatch a Celery task that pushes the change through each platform adapter, with status (PENDING/APPLIED/FAILED) recorded in `AppliedOptimization`. Do not report success until the platform confirms.

### 3.3 Dashboard aggregates (D1-D5, D8, D9)
- Replace per-day loops with grouped queries (`values('date','platform').annotate(...)`), one pass for the current period and one for the previous period.
- Platform cards: Facebook/Instagram from `AnalysisBreakdownDaily(dimension='publisher_platform')`; Google/TikTok from daily rows; Total from daily rows.
- Return `has_data`, `last_synced_at`, `partial_platforms` (connected but never synced / failing) so the frontend can distinguish "no data yet" from "zero".
- Percent change: `null` when the previous period is empty.
- Delete every demo fallback and the TODO comments they carry.

### 3.4 Pages that become possible once breakdowns exist
- Analytics -> device performance, hour-of-day heat map, demographics, placements (all from `AnalysisBreakdownDaily`).
- Dashboard insight "Best time to advertise" computed from the hour breakdown (top 3-hour window by CTR/CVR with a minimum-volume check) instead of a canned sentence.
- Campaign details placements: replace "spend share per platform" with publisher platform + position.

## 4. Delivery phases
1. **Foundation** (backend only, no visible change): migrations, adapter interface, rolling re-sync, backfill command, last-synced tracking, SDK upgrades (Meta v27 line, Google v26 line). Exit: a connected sandbox account shows rows with revenue, reach and currency.
2. **Breakdown ingestion**: Meta publisher_platform, hour, age/gender/country (device behind opt-in detection); Google device/hour/network/geo; TikTok hour and audience. Exit: `AnalysisBreakdownDaily` filled and reconciled.
3. **Dashboard + Analytics on real data**: rewrite `get_dashboard_data` and `get_analytics_data`, remove demo fallbacks, add `has_data`/`last_synced_at`. **Frontend work**: empty states, "last updated", null deltas, currency formatting, device/hour/demographic widgets.
4. **Computed intelligence**: insight model changes, confidence/ROI engine, budget recommendation, optimization log, platform push for applied budgets, Celery `run_optimization`.
5. **Hardening**: data-quality checks and alerts (ingestion gaps, spend mismatch vs platform), docs.

Phases 1-2 are the long pole (external API behavior); 3 and 4 can be built against fixtures in parallel once the schema in 2.1 is agreed.

## 5. Validation
- Recorded-response fixtures per platform adapter (sanitized), unit-tested for field mapping, micros/currency, and missing-field handling.
- Sandbox/test ad accounts (a Google test-account helper already exists in the repo) for end-to-end runs.
- **Reconciliation test**: totals from our tables vs the platform's own reporting UI/API for the same account and dates; alert on drift above a small tolerance.
- Tests that the dashboard never returns demo values: an org without data returns `has_data=false` and empty lists.
- Performance: assert a fixed number of queries for the dashboard regardless of range length.

## 6. Risks and decisions needed
- **Meta device and frequency breakdowns need account-level opt-in** (since 2026-08-06): the UI must handle "not available", and a guided opt-in step may be worth building.
- **Attribution and lag**: numbers for the last ~1-4 weeks change after the fact; show "last updated" and avoid alarmist deltas for the most recent days.
- **Conversion definition differs per platform and objective**: we need an explicit mapping (and probably an org-level setting) for what counts as a conversion and revenue.
- **API/permission scope**: Meta `ads_read`, Google developer-token access level, and TikTok report permissions must cover the new reports; app review may be required.
- **Mixed currencies and time zones** across integrations: group, do not blend.
- **Sync cost/rate limits** grow with orgs x breakdowns x backfill window: schedule and cache accordingly.
- **Decisions for the owner**: (a) is "conversions" purchases only, or objective-based; (b) retain how many months of breakdown history; (c) should orgs see an opt-in prompt for Meta device data; (d) are Google `conversions` or `all_conversions` the dashboard number.

## 7. Sources checked
- Meta Insights API breakdowns (official, read in full): https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/breakdowns
- Meta changelog on ads insights metric availability: https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- Google Ads API release notes: https://developers.google.com/google-ads/api/docs/release-notes
- Google Ads API v24.2 (ad_network_type): https://ppc.land/google-ads-api-v24-2-ai-transparency-and-pmax-segmentation-finally-arrive/
- TikTok report metrics via connector documentation (secondary, official TikTok reference still to be checked): https://fivetran.com/docs/connectors/applications/tiktok-ads/prebuilt-reports


## 8. Implementation status (2026-11-13)

### Done
- **Schema** (`analysis.0005`, `main.0010`): `AnalysisDaily.conversion_value/currency/reach/frequency/video_views/synced_at`, `AnalysisBreakdownDaily`, `AdIntegration.analytics_synced_at/analytics_error/time_zone`, `AIInsight.recommendation_type/params/expected_delta/confidence/status/applied_at`, `AppliedOptimization`.
- **Ingestion**: shared `apps/analysis/ingest.py` (rolling 28-day window, idempotent upserts, breakdown replacement, sync health). Meta objective-based conversions/revenue + publisher platform, placement, age/gender, country, device (opt-in detected), hour. Google conversions value/video views + device, hour, ad network, age, gender, country (localized name). TikTok reach/frequency/video + hour, gender, age, country, device (each isolated so an unsupported report cannot fail the sync).
- **Backfill/freshness**: `python manage.py sync_analytics --org|--integration|--all [--since --until --days]`; first account selection chains `sync_ads_task` -> 395-day `sync_analytics_task`; beat fans out all active integrations every 6 hours, staggered. `analytics_synced_at`/`analytics_error` drive `last_synced_at` and `partial_platforms`.
- **Dashboard/Analytics**: demo values removed. Grouped queries, gap-free daily/weekly/monthly buckets, real calendar months, real all-time range, null percent change when the previous period is empty, per-currency grouping with `mixed_currencies`, Facebook/Instagram from the publisher-platform breakdown (Meta fallback marked estimated), `breakdowns` for every dimension, device table with legacy JSON fallback.
- **Computed intelligence**: `apps/main/services/optimization.py` computes campaign metrics, confidence, rule insights (budget shift/increase, refresh creative, targeting, schedule), real budget recommendation, potential impact ranges, optimization summary/history, and best hour window. `run_optimization` dispatches a Celery task. Apply-budget updates the local budget, logs `AppliedOptimization`, and pushes to Meta/Google/TikTok when a platform campaign exists, recording `PENDING/APPLIED/FAILED`. A daily task fills `measured_impact` (CPA/ROAS change and estimated savings) after the 7-day observation window.
- **Frontend**: null-delta styling, `has_data` / empty-range banners, "last updated", mixed-currency notice, empty AI-insight state; response types updated. `npm run build` passes.
- **Tests**: 319 backend tests pass (1 skipped), including new real-data/optimization/device-table tests; `makemigrations --check` clean.

### Deviations / still open
- Meta SDK stays pinned to `facebook-business==24.0.1`; Graph version is configurable via `META_API_VERSION` (default `v24.0`). A v27 SDK upgrade needs a sandbox regression run.
- Google Ads default API version raised to `v26` (`.env` can override; local `.env` still says `v20`).
- TikTok `AUDIENCE` + `platform` dimension and some metric names remain unconfirmed against the official reference; failures are reported through `analytics_error`, never fatal.
- Phase 5 reconciliation/alerting is not implemented: no automated spend-vs-platform drift check yet.
- Sandbox end-to-end runs against live Meta/Google/TikTok accounts have not been executed in this environment.
