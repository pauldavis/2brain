## 2brain Viewer (SvelteKit)

This front-end consumes the FastAPI document service and presents a side-by-side
document browser with segment-level navigation.

### Prerequisites

- Node.js 22.12.0+ (or 20.19.0+ if you stay on the 20.x LTS line) — required by Vite 7 and the Svelte 5 toolchain
- The FastAPI service running locally (default `http://localhost:8100`)

### Install & run

```bash
cd viewer
npm install
npm run dev -- --open
```

The development server reads `PUBLIC_API_BASE` from `.env` (defaults to the FastAPI
dev URL). Adjust it if your API runs elsewhere. Styling is powered by Tailwind CSS 4.1
plus DaisyUI 5 — configuration lives directly in `src/app.css` via the new
`@import`, `@plugin`, and `@layer` directives, so there is no separate Tailwind config file.
Vite loads Tailwind through the official `@tailwindcss/vite` plugin defined in `vite.config.ts`.

### Features

- Document list with instant client-side title filtering.
- Metadata header summarizing source system, timestamps, and keywords.
- Segment viewer with previous/next navigation and block/attachment display.

Future enhancements (search integration, branch visualization, exports) can
build on the `DocumentView` contract defined in `docs/design/document-view.md`.
