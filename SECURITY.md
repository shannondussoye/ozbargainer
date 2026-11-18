# Security

## Secrets

Runtime secrets live in `.env` (git-ignored) and are injected into the container via `env_file`:

| Variable | What it grants |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Full control of the notification bot (send/read messages) |
| `TELEGRAM_CHAT_ID` | Target chat for alerts |
| `HEALTHCHECK_PING_URL` | Capability URL; anyone with it can spoof/disable heartbeat monitoring |
| `LOGTAIL_TOKEN` / `LOGTAIL_SOURCE_TOKEN` | Write access to the log ingest source |

Rules:

- **Never commit `.env`.** It is listed in `.gitignore`; keep it that way.
- **Keep it private.** The file must be mode `600` (`chmod 600 .env`, or `make secure-env`). Do not place it on a world-readable mount.
- `.env.example` contains placeholders only — never put real values in it.

## Rotating credentials

Rotate immediately if a secret was printed to a terminal, written to a log, pasted into an issue, or committed.

### Telegram bot token
1. In Telegram, open **@BotFather** → `/revoke` → select the bot (or `/token` to regenerate).
2. Put the new token in `.env` (`TELEGRAM_BOT_TOKEN`).
3. `make secure-env`
4. Restart so the container picks it up: `docker compose up -d --force-recreate`
5. Confirm alerts still arrive (and that the old token is rejected).

### Healthchecks.io ping URL
1. In the Healthchecks project, regenerate/replace the ping key so the old UUID is invalid.
2. Update `HEALTHCHECK_PING_URL` in `.env`, then `make secure-env` and recreate the container.

### Logtail source token
1. Rotate the source token in Better Stack / Logtail.
2. Update `LOGTAIL_SOURCE_TOKEN`, `make secure-env`, recreate the container.

## If a secret was exposed

1. Rotate every credential that may have been seen (assume all of them in `.env`).
2. Remove the value from any logs/artifacts that captured it.
3. Re-scan the repo: `detect-secrets scan --baseline .secrets.baseline`.
4. Review access logs for the affected service (Telegram/Healthchecks/Logtail).

## Related hardening

- `CHROME_CDP_URL` is validated to bind only to `localhost`/`127.0.0.1` in `ozbargain/config.py` to prevent remote-code-execution via the DevTools endpoint.
- The Chrome bridge listens on `127.0.0.1:9228` only.
