import type { PageLoad } from './$types';
import type { DocumentSummary, DocumentView } from '$lib/types';
import { env } from '$env/dynamic/public';

const API_BASE = env.PUBLIC_API_BASE || 'http://localhost:8000';
const DEFAULT_LIMIT = 50;

export const load = (async ({ fetch }) => {
	const documentsRes = await fetch(`${API_BASE}/documents?limit=${DEFAULT_LIMIT}`);
	const documents: DocumentSummary[] = await documentsRes.json();

	let initialDocument: DocumentView | null = null;
	if (documents.length > 0) {
		const docRes = await fetch(`${API_BASE}/documents/${documents[0].id}`);
		initialDocument = await docRes.json();
	}

	return {
		apiBase: API_BASE,
		documents,
		initialDocument
	};
}) satisfies PageLoad;
