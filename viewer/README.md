## 2brain Viewer (SvelteKit)

This front-end consumes the FastAPI document service and presents a side-by-side
document browser with segment-level navigation.

### Prerequisites

- Node.js 18+
- The FastAPI service running locally (default `http://localhost:8000`)

### Install & run

```bash
cd viewer
npm install
npm run dev -- --open
```

The development server reads `PUBLIC_API_BASE` from `.env` (defaults to the FastAPI
dev URL). Adjust it if your API runs elsewhere.

### Features

- Document list with instant client-side title filtering.
- Metadata header summarizing source system, timestamps, and keywords.
- Segment viewer with previous/next navigation and block/attachment display.

Future enhancements (search integration, branch visualization, exports) can
build on the `DocumentView` contract defined in `docs/design/document-view.md`.
