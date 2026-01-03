# AdPortal Endpoint list

## Base URL
`https://localhost:8000/api`

---

## Account Management

| Method | Endpoint                               | Description                     | Auth Required |
|--------|----------------------------------------|---------------------------------|---------------|
| POST   | /accounts/register/                    | Register a new user             | No            |
| POST   | /accounts/verify-email/                | Verify user email               | No            |
| POST   | /accounts/login/                       | User login                      | No            |
| POST   | /accounts/token/refresh/               | Refresh authentication token    | Yes           |
| POST   | /accounts/logout/                      | User logout                     | Yes           |
| GET    | /accounts/profile/                     | Get user profile information    | Yes           |
| PUT    | /accounts/profile/update/              | Update user profile information | Yes           |
| POST   | /accounts/change-password/             | Change user password            | Yes           |
| POST   | /accounts/password-reset/              | Reset user password             | No            |
| POST   | /accounts/password-reset-confirm/      | Confirm password reset          | No            |
