# Frontend

Frontend for the _Detection of Architectural Degradation during the Maintenance Phase_ research system.

The frontend communicates with the backend **exclusively via HTTP/REST**. It must never access PostgreSQL, Neo4j, Git repositories, extraction tools, or LLM providers directly.

## Stack

| Concern | Choice |
| ------- | ------ |
| Build tool | [Vite](https://vite.dev/) 8 |
| UI library | [React](https://react.dev/) 19 + TypeScript |
| Styling | [Tailwind CSS](https://tailwindcss.com/) 4 (via `@tailwindcss/vite`) |
| Routing | [React Router](https://reactrouter.com/) 8 — `createBrowserRouter` |
| Linting | [Oxlint](https://oxc.rs/) |

> **Requirement:** Node `>=22.22.0` (enforced by React Router 8's `engines` field). Developed on Node 24 LTS.

## Getting started

```bash
cd frontend
npm install
npm run dev
```

The app runs at <http://localhost:5173>.

## Backend connection

In development, Vite proxies `/api/*` to the FastAPI backend at `http://127.0.0.1:8000`
(configured in [`vite.config.ts`](./vite.config.ts)), so no CORS setup is needed.
`/api/` maps to the backend root `/`.

Start the backend first, from `backend/`:

```bash
uv run uvicorn app.main:app --reload
```

The base URL is configurable through `VITE_API_BASE_URL` (default `/api`). Copy
[`.env.example`](./.env.example) to `.env.local` to override it.

## Scripts

| Command | Purpose |
| ------- | ------- |
| `npm run dev` | Start the dev server with HMR. |
| `npm run build` | Type-check (`tsc -b`) and build for production. |
| `npm run preview` | Preview the production build. |
| `npm run lint` | Run Oxlint. |

## Structure

```
src/
├── layouts/
│   └── RootLayout.tsx     # app shell (header + <Outlet />)
├── lib/
│   └── api.ts             # typed HTTP client for the backend
├── pages/
│   ├── Home.tsx           # calls the backend root, shows message + environment
│   └── NotFound.tsx       # 404 route
├── index.css              # Tailwind entry point
├── main.tsx               # entry point (RouterProvider)
└── router.tsx             # createBrowserRouter route config
```

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
