# Order Supervisor UI

Next.js App Router operator console for the Order Supervisor API. The UI
proxies `/api/*` through the Next.js server to `API_URL`; use
`http://localhost:8000` for local development or `http://api:8000` in Docker
Compose.

## Local development

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. The FastAPI service must be running at
`API_URL`.

## Validation

```bash
npm run lint
npm run build
```
