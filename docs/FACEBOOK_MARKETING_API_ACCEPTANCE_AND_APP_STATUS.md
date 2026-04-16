# Facebook (Meta) Marketing API: Accepted Values, Phase Flow, and AdPortal Status Audit

Date: 2026-04-17

## Scope and source links
This guide is based on Meta Marketing API reference pages (Graph API v25 docs), plus an audit of this repository.

Primary docs used:
- https://developers.facebook.com/docs/marketing-api/
- https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group
- https://developers.facebook.com/docs/marketing-api/reference/ad-campaign
- https://developers.facebook.com/docs/marketing-api/reference/ad-creative

Note:
- The URL provided originally (`/documentation/ads-commerce`) is currently not a valid docs page.
- Meta constraints can vary by objective, destination type, account setup, and policy region.

---

## 1. What is acceptable in Meta (practical rules)

### 1.1 Campaign-level
Required and important fields:
- `name`
- `objective`
- `status`
- `special_ad_categories` (required; use `[]` or `NONE` if not special)

Modern objective family (ODAX):
- `OUTCOME_APP_PROMOTION`
- `OUTCOME_AWARENESS`
- `OUTCOME_ENGAGEMENT`
- `OUTCOME_LEADS`
- `OUTCOME_SALES`
- `OUTCOME_TRAFFIC`

Key constraints:
- `special_ad_categories` is mandatory for campaign creation.
- If category is Housing/Employment/Credit, targeting restrictions apply.
- Objective selection limits allowed ad set optimization goals and promoted object shape.

### 1.2 Ad Set-level
Required baseline fields:
- `name`
- `campaign_id`
- `optimization_goal`
- `billing_event`
- budget (`daily_budget` or `lifetime_budget`)
- `targeting`
- often `promoted_object` (depends on objective/destination)

Budget and bidding:
- `bid_strategy` commonly one of:
  - `LOWEST_COST_WITHOUT_CAP`
  - `LOWEST_COST_WITH_BID_CAP`
  - `COST_CAP`
  - `LOWEST_COST_WITH_MIN_ROAS`
- Minimum budgets are validated by Meta and vary by currency/account country.

Common optimization goals (not exhaustive):
- `LINK_CLICKS`
- `LANDING_PAGE_VIEWS`
- `OFFSITE_CONVERSIONS`
- `LEAD_GENERATION`
- `REACH`
- `POST_ENGAGEMENT`
- `APP_INSTALLS`

Common billing events (not exhaustive):
- `IMPRESSIONS`
- `LINK_CLICKS`
- `CLICKS`
- `THRUPLAY`
- `APP_INSTALLS`
- `POST_ENGAGEMENT`

Important policy/region constraints:
- EU-targeted ads require `dsa_payor` and `dsa_beneficiary` at ad set level.
- If defaults are not configured on ad account and these fields are missing, requests fail.

### 1.3 Creative-level
Common requirements:
- `object_story_spec` with `page_id`
- `link_data` for link ads
- CTA type must be valid Meta enum

Common valid CTA examples:
- `LEARN_MORE`, `SHOP_NOW`, `SIGN_UP`, `CONTACT_US`, `BOOK_NOW`, `DOWNLOAD`, `APPLY_NOW`, `GET_QUOTE`, `ORDER_NOW`

Special category note:
- Political/issues/elections require campaign special category + creative authorization settings.

---

## 2. Recommended phase flow for Facebook ads

### Phase A: Pre-flight validation (before Meta API calls)
Validate in your backend before create/update:
- Objective is supported.
- Platform is connected and ad account/page are selected.
- Special ad category is chosen (empty array if none).
- Budget type and amount are valid.
- Targeting has valid countries/ages.
- CTA maps to valid Meta CTA enum.
- For SALES/CONVERSIONS: required `promoted_object` pieces (pixel/custom conversion/page/etc) are present.
- For EU targeting: include `dsa_payor` and `dsa_beneficiary`.

### Phase B: Create campaign
- Create campaign with ODAX objective and `special_ad_categories`.
- Save Meta campaign id.

### Phase C: Create ad set
- Build objective-compatible set of:
  - `optimization_goal`
  - `billing_event`
  - `promoted_object`
  - `targeting`
  - `budget`
- Use a strict compatibility map, not only fallback retries.

### Phase D: Create creative
- Build creative from normalized ad fields.
- Enforce CTA mapping and required URL/page fields.

### Phase E: Create ad
- Create ad under ad set with creative.
- Keep `PAUSED` for first publish if desired.

### Phase F: Update and status management
- Update only editable fields by level.
- If immutable ad set fields conflict (for example promoted_object incompatibility), recreate ad set and relink.

### Phase G: Post-flight and diagnostics
- Persist full Meta error payload (`code`, `error_subcode`, `error_data.blame_field_specs`, `fbtrace_id`).
- Use that payload to return user-friendly validation errors in UI.

---

## 3. AdPortal current status (what is happening now)

### 3.1 Strong points
- ODAX objective mapping exists in backend (`main/utils/meta_engine/manage_ad.py:64`).
- Optimization-goal fallback strategy exists (`main/utils/meta_engine/manage_ad.py:93`).
- `special_ad_categories` is being sent as empty list on campaign create (`main/utils/meta_engine/manage_ad.py:159`).
- `promoted_object` with `page_id` is included for ad set create (`main/utils/meta_engine/manage_ad.py:206`, `main/utils/meta_engine/manage_ad.py:487`).
- CTA normalization exists (`main/utils/meta_engine/manage_ad.py:220`).
- Recreate logic exists if legacy ad set lacks `promoted_object` (`main/utils/meta_engine/manage_ad.py:544`).

### 3.2 Current mismatch and risk areas

1) Frontend default values are generic and not Meta-specific.
- Frontend stores defaults like `biddingStrategy:"lowest_cost"` and `optimizationGoal:"conversions"` in campaign-builder state (`frontend/assets/index-BTntfLV_.js:14`).
- These are UI-level values and not guaranteed to map to valid Meta objective+adset constraints.

2) Backend serializer validates generic business fields, not Meta compatibility matrix.
- Objective validity is only against internal enum (`main/serializers.py:381`).
- No strict Meta matrix check for objective + optimization_goal + billing_event + promoted_object.

3) Ad set creation uses fixed billing/bid defaults across objectives.
- Ad set create uses fixed `billing_event="IMPRESSIONS"` and `bid_strategy="LOWEST_COST_WITHOUT_CAP"` (`main/utils/meta_engine/manage_ad.py:482`, `main/utils/meta_engine/manage_ad.py:483`).
- This is safe for many cases, but not guaranteed across all objective/destination combinations.

4) SALES/CONVERSIONS promoted_object specifics are not explicitly enforced.
- Current promoted object helper returns only `{ "page_id": ... }` (`main/utils/meta_engine/manage_ad.py:206`).
- Many conversion flows need additional promoted_object fields (for example pixel/custom conversion/app data), depending on optimization goal.

5) DSA fields are not wired in create/update flow.
- No explicit `dsa_payor` / `dsa_beneficiary` path in current Meta manage flow.
- EU targeting can fail with parameter errors if not set.

6) API version lag vs latest docs.
- Code uses `api_version="v19.0"` (`main/utils/meta_engine/manage_ad.py:55`) while docs referenced are v25.
- This can produce behavior differences and deprecations.

7) Frontend source visibility issue.
- Workspace currently exposes built/minified frontend bundle, not clean source files (`frontend/src` not present).
- This makes safe and precise UI constraint edits harder.

---

## 4. What to do in each phase (implementation checklist)

### Phase A (Validation)
Implement a Meta validation service in backend:
- Input: unified objective + destination + budget + targeting + creative + platform settings.
- Output: normalized, Meta-compatible payload or clear errors.

### Phase B/C (Campaign + AdSet build)
Replace loose defaults with mapping tables:
- Objective -> allowed optimization goals (ordered)
- Objective -> allowed billing events
- Objective -> required promoted_object schema
- Objective/region -> required regulatory fields

### Phase D (Creative)
- Normalize CTA.
- Validate destination URL and required page/app object fields.
- Validate creative text limits and placement constraints where feasible.

### Phase E/F (Publish/Update)
- Keep resumable logic.
- Preserve recreate path for immutable field conflicts.
- Add explicit branch for DSA-required regions.

### Phase G (Observability)
- Store full Meta error payload in DB/logging and expose concise UI messages.

---

## 5. Priority fixes for AdPortal

P0 (must do first):
- Add strict Meta compatibility validation before ad set creation.
- Add objective-specific promoted_object builders (especially SALES/CONVERSIONS).
- Add DSA payor/beneficiary support for EU targeting.

P1:
- Upgrade Marketing API version (test in staging first).
- Add backend-side map for billing_event by objective and destination type.

P2:
- Move frontend generic defaults to platform-aware defaults driven by backend metadata endpoint.
- Add UI-level guards so invalid combinations are not selectable.

---

## 6. Suggested compatibility map (starter)
This is a practical baseline, not full Meta matrix.

- `TRAFFIC`
  - Objective: `OUTCOME_TRAFFIC`
  - Preferred optimization goals: `LINK_CLICKS`, `LANDING_PAGE_VIEWS`
  - Common billing event: `IMPRESSIONS` or `LINK_CLICKS`
  - Promoted object: page/site compatible object

- `AWARENESS`
  - Objective: `OUTCOME_AWARENESS`
  - Preferred optimization goals: `REACH`, `IMPRESSIONS`
  - Common billing event: `IMPRESSIONS`

- `ENGAGEMENT`
  - Objective: `OUTCOME_ENGAGEMENT`
  - Preferred optimization goals: `POST_ENGAGEMENT`, `PAGE_LIKES` (depends on destination)

- `LEAD_GENERATION`
  - Objective: `OUTCOME_LEADS`
  - Preferred optimization goal: `LEAD_GENERATION`

- `CONVERSIONS`
  - Objective: `OUTCOME_SALES`
  - Preferred optimization goal: `OFFSITE_CONVERSIONS`
  - Requires stronger promoted_object validation (pixel/custom conversion/etc as required by flow)

---

## 7. Current repository references
- Meta objective and optimization mapping: `main/utils/meta_engine/manage_ad.py:64`
- Optimization fallback logic: `main/utils/meta_engine/manage_ad.py:93`
- Campaign create fields: `main/utils/meta_engine/manage_ad.py:436`
- Ad set defaults (billing/bid): `main/utils/meta_engine/manage_ad.py:482`
- Promoted object builder: `main/utils/meta_engine/manage_ad.py:206`
- Targeting builder: `main/utils/meta_engine/manage_ad.py:329`
- Ad set update path: `main/utils/meta_engine/manage_ad.py:790`
- Generic create payload builder: `main/utils/object_handlers.py:33`
- Generic serializer checks: `main/serializers.py:381`
- Frontend default campaign state (compiled bundle): `frontend/assets/index-BTntfLV_.js:14`

---

## 8. Bottom line
Your current pipeline already has good resumable Meta publish logic, but the conflict problem is real because strict objective-to-adset compatibility is not enforced as a first-class validation phase. Add a hard validation/mapping layer before Meta calls, and most recurring conflict errors should disappear.
