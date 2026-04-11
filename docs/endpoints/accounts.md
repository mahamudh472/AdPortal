# Accounts Endpoints

## Prefix
`/api/v1/accounts/`

## Authentication
- Public endpoints: `register`, `verify-email`, `resend-otp`, `password-reset`, `check-otp`, `password-reset-confirm`, `contact-us`, `login`, `token/refresh`.
- Auth required: remaining endpoints.

## Auth and Registration

### `POST /api/v1/accounts/register/`
- Request body:

```json
{"full_name": "John Doe", "email": "john@example.com", "password": "Secret123!", "timezone": "Asia/Dhaka"}
```

- Response:

```json
{"message": "Otp sent successfully"}
```

### `POST /api/v1/accounts/verify-email/`
- Request body:

```json
{"email": "john@example.com", "otp": "123456"}
```

- Response:

```json
{"message": "Email john@example.com successfully verified"}
```

### `POST /api/v1/accounts/login/`
- Request body:

```json
{"email": "john@example.com", "password": "Secret123!"}
```

- Response: SimpleJWT payload (`access`, `refresh`) plus user/org context from custom serializer.

### `POST /api/v1/accounts/token/refresh/`
- Request body:

```json
{"refresh": "<refresh_token>"}
```

- Response:

```json
{"access": "<new_access_token>"}
```

### `POST /api/v1/accounts/logout/`
- Request body:

```json
{"refresh_token": "<refresh_token>"}
```

- Response:

```json
{"message": "Successfully logged out"}
```

## Password Recovery and Security

### `POST /api/v1/accounts/resend-otp/`
### `POST /api/v1/accounts/password-reset/`
- Request body:

```json
{"email": "john@example.com"}
```

- Response:

```json
{"message": "Otp sent successfully"}
```

### `POST /api/v1/accounts/check-otp/`
- Request body:

```json
{"email": "john@example.com", "otp": "123456"}
```

- Response:

```json
{"message": "OTP is valid"}
```

### `POST /api/v1/accounts/password-reset-confirm/`
- Request body:

```json
{"email": "john@example.com", "otp": "123456", "new_password": "NewPass123!"}
```

- Response:

```json
{"message": "Password successfully reset for john@example.com"}
```

### `POST /api/v1/accounts/change-password/`
- Request body:

```json
{"old_password": "OldPass123!", "new_password": "NewPass123!", "confirm_password": "NewPass123!"}
```

- Response:

```json
{"message": "Password changed successfully"}
```

## Profile

### `GET /api/v1/accounts/profile/`
- Request body: none.
- Response: current user object (id, full_name, email, phone_number, is_admin).

### `PATCH /api/v1/accounts/profile/update/`
- Request body: partial user fields.
- Example request:

```json
{"full_name": "John Updated", "phone_number": "+8801..."}
```

- Response:

```json
{"success": "Profile updated successfully"}
```

## Notifications

### `GET /api/v1/accounts/notifications/`
- Query params:
	- `read=true|false` (optional)
	- `page`, `page_size` (optional)
- Response: paginated notifications with extra `unread_count`.

### `POST /api/v1/accounts/read-notification/`
### `POST /api/v1/accounts/delete-notification/`
- Request body:

```json
{"notification_ids": [1, 2, 3]}
```

- Response examples:

```json
{"message": "3 notifications marked as read"}
```

```json
{"message": "3 notifications deleted"}
```

### `POST /api/v1/accounts/read-all-notifications/`
### `POST /api/v1/accounts/delete-all-notifications/`
- Request body: none.
- Response examples:

```json
{"message": "All 8 notifications marked as read"}
```

```json
{"message": "All 8 notifications deleted"}
```

### `POST /api/v1/accounts/test-notifications/`
- Request body: none.
- Response:

```json
{"message": "Test notification created"}
```

## Notification Settings

### `GET /api/v1/accounts/notification-settings/`
- Response:

```json
{"campaign_performance": true, "budget_alerts": true, "weekly_performance_summary": true, "ai_recommendations": true, "team_activity": true}
```

### `PATCH /api/v1/accounts/notification-settings/`
- Request body: any subset of the same fields.
- Response: updated settings object.

## Account Removal

### `DELETE /api/v1/accounts/delete-account/`
- Request body: none.
- Response:

```json
{"message": "Account deleted successfully"}
```

## Contact

### `POST /api/v1/accounts/contact-us/`
- Request body:

```json
{"name": "John", "email": "john@example.com", "subject": "Need help", "message": "Please contact me."}
```

- Response:

```json
{"message": "Your message has been received. We'll get back to you shortly."}
```

## Back
- [Return to endpoint index](../ENDPOINT_LIST.md)
