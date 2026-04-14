# Frontend

Telegram Mini App frontend for the `/char` flow.

## Commands

```bash
npm install
npm run dev
npm run build
```

The production build is emitted into `frontend/build`, which FastAPI serves at `/webapp`.

## Telegram setup

Point your bot's main Mini App URL to:

```text
https://<your-domain>/webapp
```

The bot opens the Mini App with a `startapp=char_<session_id>` payload so the backend can resolve the current group session.
