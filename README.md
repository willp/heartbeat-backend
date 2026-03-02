# heartbeat-backend

Heartbeat Server Backend


## 🔐 Configuration & Secrets

This application requires a few environment variables to run securely. You can provide these via a .env file or directly to your container engine.

| Variable | Description | Default |
| :--- | :--- | :--- |
| DJANGO_SECRET_KEY | (Required) A unique, unpredictable value used for signing. | insecure-dev-only |
| DJANGO_ALLOWED_HOSTS | Comma-separated list of domains/IPs allowed to reach the server. | localhost |
| HEARTBEAT_DB_PATH | Absolute path to your SQLite database. | ./hbdb.sqlite3 |

### Example .env setup:

1. Copy the template: cp .env.example .env
2. Generate a key: `python3 -c 'import secrets; print(secrets.token_urlsafe(50))'`
3. Paste that key into your .env file.

