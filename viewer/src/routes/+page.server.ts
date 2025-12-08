import type { PageServerLoad } from "./$types";
import { env } from "$env/dynamic/private";
import type { DocumentSummary, DocumentView } from "$lib/types";
const RAW_API_BASE = env.API_URL ?? "http://localhost:8100";
const API_BASE = RAW_API_BASE.endsWith("/")
  ? RAW_API_BASE.slice(0, -1)
  : RAW_API_BASE;

const RAW_PUBLIC_API_BASE = env.PUBLIC_API_BASE ?? "http://localhost:8100";
const PUBLIC_API_BASE = RAW_PUBLIC_API_BASE.endsWith("/")
  ? RAW_PUBLIC_API_BASE.slice(0, -1)
  : RAW_PUBLIC_API_BASE;

const DEFAULT_LIMIT = 50;

export const load = (async ({ fetch, url }) => {
  let documentsPayload: DocumentSummary[] = [];

  try {
    const documentsRes = await fetch(
      `${API_BASE}/documents?limit=${DEFAULT_LIMIT}`,
    );
    if (!documentsRes.ok) {
      console.error(
        `[load] Failed to fetch documents: ${documentsRes.status} ${documentsRes.statusText}`,
      );
      const text = await documentsRes.text();
      console.error("[load] Response body:", text);
      return {
        apiBase: PUBLIC_API_BASE,
        documents: [],
        initialDocument: null,
        initialSegmentId: null,
        error: `Backend error: ${documentsRes.status}`,
      };
    }
    documentsPayload = await documentsRes.json();
  } catch (e) {
    console.error("[load] Network/Fetch error:", e);
    return {
      apiBase: PUBLIC_API_BASE,
      documents: [],
      initialDocument: null,
      initialSegmentId: null,
      error: "Connection failed",
    };
  }

  const targetDocumentId = url.searchParams.get("document");
  const targetSegmentId = url.searchParams.get("segment");

  let initialDocument: DocumentView | null = null;
  let initialSegmentId: string | null = null;

  if (targetDocumentId) {
    const docRes = await fetch(`${API_BASE}/documents/${targetDocumentId}`);
    if (docRes.ok) {
      initialDocument = await docRes.json();
      initialSegmentId = targetSegmentId;
    }
  }

  if (!initialDocument && documentsPayload.length > 0) {
    try {
      const docRes = await fetch(
        `${API_BASE}/documents/${documentsPayload[0].id}`,
      );
      if (docRes.ok) {
        initialDocument = await docRes.json();
      } else {
        console.warn("[load] Failed to fetch default document", docRes.status);
      }
    } catch (e) {
      console.error("[load] Error fetching default document:", e);
    }
  }

  const documents = [...documentsPayload];
  if (initialDocument) {
    const docId = initialDocument.document.id;
    const exists = documents.some((doc) => doc.id === docId);
    if (!exists) {
      const fallbackCharCount = initialDocument.segments.reduce(
        (total, segment) => total + (segment.content_markdown?.length ?? 0),
        0,
      );
      documents.unshift({
        id: docId,
        title: initialDocument.document.title,
        source_system: initialDocument.document.source_system,
        created_at: initialDocument.document.created_at,
        updated_at: initialDocument.document.updated_at,
        segment_count: initialDocument.segments.length,
        char_count: fallbackCharCount,
      });
    }
  }

  return {
    apiBase: PUBLIC_API_BASE,
    documents,
    initialDocument,
    initialSegmentId,
  };
}) satisfies PageServerLoad;
