import type { PageLoad } from './$types';
import type { DocumentSummary, DocumentView } from '$lib/types';
import { env } from '$env/dynamic/public';

const API_BASE = env.PUBLIC_API_BASE || 'http://localhost:8000';
const DEFAULT_LIMIT = 50;

export const load = (async ({ fetch, url }) => {
	const documentsRes = await fetch(`${API_BASE}/documents?limit=${DEFAULT_LIMIT}`);
	const documentsPayload: DocumentSummary[] = await documentsRes.json();

	const targetDocumentId = url.searchParams.get('document');
	const targetSegmentId = url.searchParams.get('segment');

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
		const docRes = await fetch(`${API_BASE}/documents/${documentsPayload[0].id}`);
		initialDocument = await docRes.json();
	}

	const documents = [...documentsPayload];
	if (initialDocument) {
		const docId = initialDocument.document.id;
		const exists = documents.some((doc) => doc.id === docId);
		if (!exists) {
			documents.unshift({
				id: docId,
				title: initialDocument.document.title,
				source_system: initialDocument.document.source_system,
				created_at: initialDocument.document.created_at,
				updated_at: initialDocument.document.updated_at,
				segment_count: initialDocument.segments.length
			});
		}
	}

	return {
		apiBase: API_BASE,
		documents,
		initialDocument,
		initialSegmentId
	};
}) satisfies PageLoad;
