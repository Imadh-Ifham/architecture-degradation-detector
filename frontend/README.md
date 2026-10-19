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

## Working on the frontend

**Read [`docs/frontend-guide.html`](./docs/frontend-guide.html) first.** It is the
reference for everyone adding a screen: the branch model, the layout, what is
reserved for which area, and the rules. Open it in a browser.

The short version: `feature/frontend-layout` is the develop branch of the
frontend. Branch from it, build your screen in your own folder under
`src/features/`, and merge back into it.

## Structure

```
src/
├── components/
│   ├── ui/               # the shared primitives every screen is built from
│   ├── ConnectionBadge   # backend reachability, in the instrument bar
│   └── ReservedPage      # the placeholder a screen stands behind until it is built
├── features/             # one folder per screen; nothing outside imports into one
│   ├── pipeline/         # the home screen: the flow, and the stages inside a phase
│   ├── repositories/     # adding a system, and what the analysis found
│   ├── architecture/     # the diagram, the elements, the dependencies
│   ├── decisions/        # what the architecture is judged against
│   └── reserved/         # the screens nobody has built yet
├── layouts/
│   ├── AppLayout.tsx     # rail, instrument bar, work surface
│   └── navigation.ts     # the pages, and the phases of the analysis
├── lib/
│   ├── api/              # one module per area of the backend; the only place a URL lives
│   └── useRequest.ts     # loading, error and retry, once rather than per screen
├── styles/
│   └── tokens.css        # every colour, radius and font. The re-skin point
├── workspace/            # which repository and release the application is looking at
├── index.css             # Tailwind entry, base styles, the pipeline's keyframes
├── main.tsx
└── router.tsx            # one route per page, including the reserved ones
```

See the root [`ARCHITECTURE.md`](../ARCHITECTURE.md) for the intended future architecture.
