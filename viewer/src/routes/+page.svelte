<script lang="ts">
	import type { PageData } from './$types';
	import type { DocumentSummary, DocumentTranscript, DocumentView, Segment, SegmentAsset } from '$lib/types';
	import { marked } from 'marked';

	const props = $props<{ data: PageData }>();
	const data = $state(props.data);

	const API_BASE = $derived(data.apiBase);

	const documents = $derived<DocumentSummary[]>(data.documents);
	let searchTerm = $state('');
	const filteredDocuments = $derived(
		documents.filter((doc) => doc.title.toLowerCase().includes(searchTerm.toLowerCase()))
	);

	let selectedDocument = $state<DocumentView | null>(data.initialDocument);
	const selectedDocumentId = $derived<string | null>(selectedDocument?.document.id ?? null);
	let selectedSegmentIndex = $state(0);
	let isLoadingDocument = $state(false);
	let loadError = $state('');
	type ViewMode = 'document' | 'sections';
	let viewMode = $state<ViewMode>('sections');
	let sidebarOpen = $state(true);
	const segments = $derived<Segment[]>(
		[...(selectedDocument?.segments ?? [])].sort((a, b) => {
			const aTime = a.started_at ? new Date(a.started_at).getTime() : Number.MAX_SAFE_INTEGER;
			const bTime = b.started_at ? new Date(b.started_at).getTime() : Number.MAX_SAFE_INTEGER;
			if (aTime !== bTime) {
				return aTime - bTime;
			}
			return a.sequence - b.sequence;
		})
	);
	let showEmptySegments = $state(false);
	let pendingSegmentId = $state<string | null>(data.initialSegmentId ?? null);
	const visibleSegments = $derived<Segment[]>(
		showEmptySegments
			? segments
			: segments.filter((segment) => segmentHasContent(segment))
	);
	const emptySegmentCount = $derived(
		selectedDocument ? segments.filter((segment) => !segmentHasContent(segment)).length : 0
	);
	const currentSegment = $derived<Segment | null>(visibleSegments[selectedSegmentIndex] ?? null);
	let transcript = $state<DocumentTranscript | null>(null);
	let transcriptError = $state('');
	let isTranscriptLoading = $state(false);
	const transcriptDownloadUrl = $derived<string | null>(
		selectedDocumentId ? `${API_BASE}/documents/${selectedDocumentId}/transcript?format=markdown&download=1` : null
	);

	const dateFormatter = new Intl.DateTimeFormat('en-US', {
		year: 'numeric',
		month: 'short',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit'
	});
	const shortDateFormatter = new Intl.DateTimeFormat('en-GB', {
		day: '2-digit',
		month: 'short',
		year: 'numeric'
	});
	const numberFormatter = new Intl.NumberFormat();

	function formatDate(value?: string | null) {
		if (!value) return '—';
		return dateFormatter.format(new Date(value));
	}

	function formatShortDate(value?: string | null) {
		if (!value) return '—';
		return shortDateFormatter.format(new Date(value));
	}

	function formatCharacterCount(value?: number | null) {
		if (value === null || value === undefined) return null;
		const numericValue = typeof value === 'number' ? value : Number(value);
		if (Number.isNaN(numericValue)) return null;
		return `${numberFormatter.format(numericValue)} characters`;
	}

	function formatSegmentCount(value?: number | null) {
		if (value === null || value === undefined) return null;
		const numericValue = typeof value === 'number' ? value : Number(value);
		if (Number.isNaN(numericValue)) return null;
		return `${numberFormatter.format(numericValue)} segments`;
	}

	const selectedDocumentCharCount = $derived(
		selectedDocument
			? selectedDocument.segments.reduce((total, segment) => {
					const length = typeof segment.content_markdown === 'string' ? segment.content_markdown.length : 0;
					return total + length;
			  }, 0)
			: null
	);
	const selectedDocumentCharLabel = $derived(formatCharacterCount(selectedDocumentCharCount));
	const selectedDocumentSegmentLabel = $derived(
		selectedDocument ? formatSegmentCount(selectedDocument.segments.length) : null
	);

	function sourceAccentClass(source?: string | null) {
		switch ((source ?? '').toLowerCase()) {
			case 'chatgpt':
			case 'openai':
				return 'border-l-sky-400';
			case 'slack':
				return 'border-l-amber-400';
			case 'email':
				return 'border-l-emerald-400';
			case 'teams':
				return 'border-l-fuchsia-400';
			default:
				return 'border-l-slate-400';
		}
	}

	function documentDateTooltip(doc?: DocumentView | null) {
		if (!doc) return '';
		return `Created: ${formatDate(doc.document.created_at)}\nUpdated: ${formatDate(doc.document.updated_at)}\nIngested: ${formatDate(
			doc.version.ingested_at
		)}`;
	}

	function formatBytes(value?: number | null) {
		if (!value) return null;
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		let unitIndex = 0;
		let current = value;
		while (current >= 1024 && unitIndex < units.length - 1) {
			current /= 1024;
			unitIndex += 1;
		}
		const precision = unitIndex === 0 ? 0 : 1;
		return `${current.toFixed(precision)} ${units[unitIndex]}`;
	}

	async function selectDocument(id: string, segmentId?: string | null) {
		if (id === selectedDocumentId) return;
		isLoadingDocument = true;
		loadError = '';
		try {
			const res = await fetch(`${API_BASE}/documents/${id}`);
			if (!res.ok) {
				throw new Error(`Failed to load document (${res.status})`);
			}
				const doc: DocumentView = await res.json();
				selectedDocument = doc;
				selectedSegmentIndex = 0;
				pendingSegmentId = segmentId ?? null;
				transcript = null;
				transcriptError = '';
				viewMode = 'sections';
		} catch (error) {
			console.error(error);
			loadError = error instanceof Error ? error.message : 'Unknown error while loading document.';
		} finally {
			isLoadingDocument = false;
		}
	}

	async function loadTranscript(force = false) {
		if (!selectedDocumentId || !selectedDocument) return;
		if (transcript && transcript.document.id === selectedDocumentId && !force) return;
		isTranscriptLoading = true;
		transcriptError = '';
		try {
			const res = await fetch(`${API_BASE}/documents/${selectedDocumentId}/transcript`);
			if (!res.ok) {
				throw new Error(`Failed to load transcript (${res.status})`);
			}
			const payload: DocumentTranscript = await res.json();
			transcript = payload;
		} catch (error) {
			console.error(error);
			transcriptError = error instanceof Error ? error.message : 'Unknown error while loading transcript.';
		} finally {
			isTranscriptLoading = false;
		}
	}

	function previousSegment() {
		if (!selectedDocument || visibleSegments.length === 0) return;
		selectedSegmentIndex = Math.max(0, selectedSegmentIndex - 1);
	}

	function nextSegment() {
		if (!selectedDocument || visibleSegments.length === 0) return;
		selectedSegmentIndex = Math.min(visibleSegments.length - 1, selectedSegmentIndex + 1);
	}

	function firstSegment() {
		if (!selectedDocument || visibleSegments.length === 0) return;
		selectedSegmentIndex = 0;
	}

	function lastSegment() {
		if (!selectedDocument || visibleSegments.length === 0) return;
		selectedSegmentIndex = visibleSegments.length - 1;
	}

	marked.setOptions({ breaks: true, gfm: true });
	const markdownCache = new Map<string, string>();
	function renderMarkdown(text: string) {
		if (!text) return '';
		const cached = markdownCache.get(text);
		if (cached) return cached;
		const html = marked.parse(text) as string;
		markdownCache.set(text, html);
		return html;
	}

	function roleLabel(role: string) {
		return role.charAt(0).toUpperCase() + role.slice(1);
	}

	function blockLabelType(type: string) {
		switch (type) {
			case 'code':
				return 'Code';
			case 'tool_call':
				return 'Tool Call';
			case 'tool_result':
				return 'Tool Result';
			case 'citation':
				return 'Citation';
			default:
				return type.charAt(0).toUpperCase() + type.slice(1);
		}
	}

	function segmentHasContent(segment: Segment) {
		const markdownText = segment.content_markdown?.trim() ?? '';
		if (markdownText.length > 0) return true;
		if (segment.blocks?.length) {
			return segment.blocks.some((block) => (block.body?.trim()?.length ?? 0) > 0);
		}
		return false;
	}

	function segmentAccentClass(role: string) {
		switch (role) {
			case 'assistant':
				return 'border-l-4 border-l-sky-400 pl-4';
			case 'user':
				return 'border-l-4 border-l-amber-400 pl-4';
			case 'system':
				return 'border-l-4 border-l-slate-400 pl-4';
			default:
				return 'border-l-4 border-l-emerald-300 pl-4';
		}
	}

	function downloadSegment(segmentId: string) {
		const url = `${API_BASE}/documents/segments/${segmentId}/export?format=markdown&download=1`;
		const link = document.createElement('a');
		link.href = url;
		link.target = '_blank';
		link.rel = 'noreferrer';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function attachmentUrl(asset: SegmentAsset, download = false) {
		if (!asset.attachment_id) return null;
		return `${API_BASE}/attachments/${asset.attachment_id}${download ? '?download=1' : ''}`;
	}

	function isImageAsset(asset: SegmentAsset) {
		return Boolean(asset.mime_type && asset.mime_type.startsWith('image'));
	}

	type SegmentContentPart =
		| { kind: 'markdown'; content: string }
		| { kind: 'code'; content: string; language: string | null; snippet: number };

	function normalizeFenceLanguage(language: string | null): string {
		if (!language) return 'PLAINTEXT';
		const lower = language.toLowerCase();
		if (lower === 'jsonc' || lower === 'json') return 'JSON';
		if (lower === 'mermaid') return 'MERMAID';
		return lower.toUpperCase();
	}

	function dedentCode(raw: string, language: string | null): string {
		// Drop leading/trailing blank lines first
		let text = raw.replace(/^\s*\n/, '').replace(/\s*$/, '');

		const lang = (language || '').toLowerCase();
		// For plain text-ish blocks, just strip all leading indentation on every line
		if (!lang || lang === 'text' || lang === 'plaintext') {
			return text.replace(/^[\t ]+/gm, '');
		}

		const lines = text.split('\n');
		let minIndent: number | null = null;
		for (const line of lines) {
			if (!line.trim()) continue;
			const match = line.match(/^[\s\u00a0]*/); // any whitespace, including non-breaking
			const indent = match ? match[0].length : 0;
			minIndent = minIndent === null ? indent : Math.min(minIndent, indent);
		}
		if (minIndent === null || minIndent === 0) {
			return text;
		}
		return lines
			.map((line) => {
				if (!line.trim()) return '';
				return line.length >= minIndent ? line.slice(minIndent) : line.trimStart();
			})
			.join('\n');
	}

	function splitContent(markdown?: string | null): SegmentContentPart[] {
		if (!markdown) return [];
		const parts: SegmentContentPart[] = [];
		const regex = /```([\w-]+)?\s*\n([\s\S]*?)```/g;
		let match: RegExpExecArray | null;
		let lastIndex = 0;
		let snippetCounter = 0;
		// eslint-disable-next-line no-cond-assign
		while ((match = regex.exec(markdown))) {
			const preceding = markdown.slice(lastIndex, match.index);
			if (preceding.trim()) {
				parts.push({ kind: 'markdown', content: preceding });
			}
			const language = (match[1] || '').trim() || null;
			const rawContent = match[2] || '';
			const content = dedentCode(rawContent, language);
			if (content) {
				parts.push({ kind: 'code', language, content, snippet: ++snippetCounter });
			}
			lastIndex = regex.lastIndex;
		}
		const remaining = markdown.slice(lastIndex);
		if (remaining.trim()) {
			parts.push({ kind: 'markdown', content: remaining });
		}
		if (!parts.length && markdown) {
			parts.push({ kind: 'markdown', content: markdown });
		}
		return parts;
	}

	const segmentedContent = $derived(splitContent(currentSegment?.content_markdown ?? null));
	const hasDetailedBlocks = $derived(() =>
		(currentSegment?.blocks ?? []).some((block) => block.block_type !== 'markdown')
	);

	function escapeHtml(value: string): string {
		return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
	}

function highlightCode(value: string, language: string | null): string {
	const escaped = escapeHtml(value);
	const lang = (language || '').toLowerCase();
	if (lang === 'sql') {
			const keywords =
				'SELECT|FROM|WHERE|GROUP\\s+BY|ORDER\\s+BY|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|NOT|NULL|VALUES|LIMIT|OFFSET|HAVING|DISTINCT|UNION|ALL';
			const regex = new RegExp(`\\b(${keywords})\\b`, 'gi');
			return escaped.replace(regex, '<span class="code-keyword">$1</span>');
		}
	return escaped;
}

function sanitizeSummary(raw: string): string {
	const trimmed = raw.trim();
	const overviewPrefix = /^\*\*Conversation Overview\*\*\s*/i;
	const deduped = trimmed.replace(overviewPrefix, '');
	return deduped.replace(/\*\*Tool Knowledge\*\*/, '\n\n**Tool Knowledge**');
}

	async function copyCodeToClipboard(code: string) {
		try {
			await navigator.clipboard.writeText(code);
		} catch (error) {
			console.error('Failed to copy code', error);
		}
	}

	function downloadCode(code: string, fileName = 'snippet.txt') {
		const blob = new Blob([code], { type: 'text/plain' });
		const blobUrl = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = blobUrl;
		link.download = fileName;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(blobUrl);
	}

	$effect(() => {
		if (selectedSegmentIndex >= visibleSegments.length) {
			selectedSegmentIndex = visibleSegments.length > 0 ? visibleSegments.length - 1 : 0;
		}
	});

	$effect(() => {
		if (!pendingSegmentId) return;
		const idx = visibleSegments.findIndex((segment) => segment.id === pendingSegmentId);
		if (idx >= 0) {
			selectedSegmentIndex = idx;
			pendingSegmentId = null;
		}
	});

	$effect(() => {
		if (viewMode !== 'document') return;
		if (!selectedDocumentId) return;
		if (isTranscriptLoading) return;
		if (transcript && transcript.document.id === selectedDocumentId) return;
		loadTranscript(false);
	});
</script>

<div class="flex min-h-screen flex-col bg-slate-50 text-slate-900 md:grid md:grid-cols-[320px_1fr]">
	<aside
		id="documents-sidebar"
		class={`border-b border-slate-200 bg-white/90 backdrop-blur md:border-b-0 md:border-r ${
			sidebarOpen ? 'block' : 'hidden'
		} md:block`}
	>
		<div class="flex h-full flex-col gap-4 p-6">
			<div class="flex items-start justify-between gap-3">
				<h1 class="text-2xl font-semibold tracking-tight">Documents</h1>
				<button
					type="button"
					class="btn btn-ghost btn-xs md:hidden"
					aria-controls="documents-sidebar"
					aria-expanded={sidebarOpen}
					onclick={() => (sidebarOpen = false)}
				>
					Hide
				</button>
			</div>
			<p class="text-sm text-slate-500">Filter and choose a conversation to review.</p>

			<label class="input input-bordered flex items-center gap-2 bg-white">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5 opacity-70">
					<path
						fill-rule="evenodd"
						d="M9 3.5a5.5 5.5 0 1 0 3.68 9.62l3.6 3.6a.75.75 0 1 0 1.06-1.06l-3.6-3.6A5.5 5.5 0 0 0 9 3.5ZM5 9a4 4 0 1 1 8 0 4 4 0 0 1-8 0Z"
						clip-rule="evenodd"
					/>
				</svg>
				<input
					type="search"
					class="grow bg-transparent"
					placeholder="Filter by title"
					bind:value={searchTerm}
					autocomplete="off"
				/>
			</label>

			{#if filteredDocuments.length === 0}
				<div class="alert alert-warning bg-amber-100 text-amber-900">
					<span>No documents match that filter.</span>
				</div>
			{:else}
				<div class="max-h-[60vh] overflow-y-auto pr-1 md:max-h-[calc(100vh-160px)]">
					<ul class="space-y-2">
						{#each filteredDocuments as doc}
							<li>
								<button
									type="button"
									onclick={() => selectDocument(doc.id)}
										class={`w-full rounded-lg border border-slate-200 ${doc.id === selectedDocumentId ? 'border-l-10' : 'border-l-4'} ${sourceAccentClass(
										doc.source_system
									)} bg-white p-4 text-left transition hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-sky-500/60`}
									disabled={isLoadingDocument}
								>
									<div class="flex items-start justify-between gap-3">
										<span class="line-clamp-2 text-sm font-semibold tracking-tight">{doc.title}</span>
									</div>
									<div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
										{#if formatCharacterCount(doc.char_count)}
											<span class="badge badge-sm badge-outline">{formatCharacterCount(doc.char_count)}</span>
										{/if}
										{#if formatSegmentCount(doc.segment_count)}
											<span class="badge badge-sm badge-outline">{formatSegmentCount(doc.segment_count)}</span>
										{/if}
										<span class="text-slate-500" title={`Updated ${formatDate(doc.updated_at)}`}>
											Updated {formatShortDate(doc.updated_at)}
										</span>
									</div>
								</button>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		</div>
	</aside>

	<main class="flex min-h-screen flex-col gap-6 overflow-y-auto p-6 lg:p-10">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<a class="btn btn-outline btn-sm" href="/search">
				<span aria-hidden="true">←</span>
				Back to search
			</a>
			<button
				type="button"
				class="btn btn-ghost btn-sm md:hidden"
				aria-controls="documents-sidebar"
				aria-expanded={sidebarOpen}
				onclick={() => (sidebarOpen = !sidebarOpen)}
			>
				{sidebarOpen ? 'Hide documents' : 'Show documents'}
			</button>
		</div>

		{#if isLoadingDocument}
			<div class="alert alert-info shadow-lg">
				<span>Loading document…</span>
			</div>
		{/if}
		{#if loadError}
			<div class="alert alert-error shadow-lg">
				<span>{loadError}</span>
			</div>
		{/if}

		{#if selectedDocument}
				<section
					class={`card rounded-lg border border-slate-200 bg-white shadow-xl border-l-4 ${sourceAccentClass(selectedDocument.document.source_system)}`}
			>
				<div class="card-body space-y-6">
						<div class="space-y-3">
							<div class="flex flex-wrap items-start justify-between gap-3">
								<h2 class="card-title text-3xl font-semibold">{selectedDocument.document.title}</h2>
								<div
									class="text-right text-sm text-slate-600"
									title={documentDateTooltip(selectedDocument)}
								>
									<span class="font-semibold text-slate-900">Updated:</span>
									{formatShortDate(selectedDocument.document.updated_at)}
								</div>
							</div>
						<div class="flex flex-wrap items-center justify-between gap-3">
							<div class="flex flex-wrap items-center gap-2 text-xs text-slate-600">
								{#if selectedDocumentCharLabel}
									<span class="badge badge-outline">{selectedDocumentCharLabel}</span>
								{/if}
								{#if selectedDocumentSegmentLabel}
									<span class="badge badge-outline">{selectedDocumentSegmentLabel}</span>
								{/if}
							</div>
							<div class="flex flex-wrap items-center gap-3 text-xs text-slate-600">
								<span class="font-semibold text-slate-500">
									{emptySegmentCount} empty segment{emptySegmentCount === 1 ? '' : 's'}
								</span>
								<div class="join">
									<button
										type="button"
										class={`btn btn-sm join-item ${showEmptySegments ? 'btn-primary' : 'btn-ghost'}`}
										onclick={() => (showEmptySegments = true)}
										disabled={emptySegmentCount === 0}
									>
										Show
									</button>
									<button
										type="button"
										class={`btn btn-sm join-item ${showEmptySegments ? 'btn-ghost' : 'btn-primary'}`}
										onclick={() => (showEmptySegments = false)}
										disabled={emptySegmentCount === 0}
									>
										Hide
									</button>
								</div>
							</div>
						</div>
					</div>

			{#if selectedDocument.document.summary}
				<section class="rounded-lg border border-slate-200 bg-slate-50 p-4">
					<header class="mb-3 flex items-center justify-between gap-2">
						<span class="text-sm font-semibold uppercase tracking-wide text-slate-500">Conversation overview</span>
						<span class="text-xs text-slate-400">scrollable summary (Markdown)</span>
					</header>
					<div class="markdown max-h-60 overflow-y-auto text-slate-700">
						{@html renderMarkdown(sanitizeSummary(selectedDocument.document.summary))}
					</div>
				</section>
			{/if}

					{#if selectedDocument.keywords.length}
						<div>
							<h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Keywords</h3>
							<div class="mt-2 flex flex-wrap gap-2">
								{#each selectedDocument.keywords as keyword}
									<span class="badge badge-success badge-outline">{keyword.term}</span>
								{/each}
							</div>
						</div>
					{/if}

					<div class="rounded-lg border border-slate-100 bg-slate-50 p-4">
						<div class="flex flex-wrap items-center justify-between gap-3">
							<div class="text-sm font-semibold tracking-wide text-slate-600">View</div>
							<div class="join">
								<button
									type="button"
									class={`btn btn-sm join-item ${viewMode === 'sections' ? 'btn-primary' : 'btn-ghost'}`}
									onclick={() => (viewMode = 'sections')}
								>
									By segment
								</button>
								<button
									type="button"
									class={`btn btn-sm join-item ${viewMode === 'document' ? 'btn-primary' : 'btn-ghost'}`}
									onclick={() => (viewMode = 'document')}
								>
									Whole document
								</button>
							</div>
						</div>
					</div>
				</div>
			</section>

                {#if viewMode === 'document'}
                    <section class="card rounded-lg border border-slate-200 bg-white shadow-xl">
                        <div class="card-body space-y-6">
                            <div class="flex items-center justify-between">
                                <h3 class="text-lg font-semibold text-slate-900">Whole document</h3>
                                {#if transcriptDownloadUrl}
                                    <a class="btn btn-sm btn-outline" href={transcriptDownloadUrl} target="_blank" rel="noreferrer">
                                        Export
                                    </a>
                                {/if}
                            </div>
                            {#if !selectedDocument}
                                <p class="text-sm text-slate-500">Select a document to view its contents.</p>
                            {:else}
                                <div class="space-y-2 text-sm text-slate-600">
                                    <div class="text-xl font-semibold text-slate-900">{selectedDocument.document.title}</div>
                                    <ul class="list-disc space-y-1 pl-5">
                                        <li>Source system: {selectedDocument.document.source_system}</li>
                                        <li>External ID: {selectedDocument.document.external_id}</li>
                                        <li>Segment count: {selectedDocument.segments.length}</li>
                                        <li>Created: {formatDate(selectedDocument.document.created_at)}</li>
                                        <li>Updated: {formatDate(selectedDocument.document.updated_at)}</li>
                                        <li>Last ingested: {formatDate(selectedDocument.version.ingested_at)}</li>
                                    </ul>
                                </div>
                                <div class="space-y-6">
                                    {#each selectedDocument.segments as segment, index}
                                        <article class="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
                                            <div class="flex flex-wrap items-start justify-between gap-3">
                                                <div class="space-y-1">
                                                    <div class="text-base font-semibold text-slate-900">
                                                        {index + 1} · {roleLabel(segment.source_role)} ({segment.segment_type})
                                                    </div>
                                                    <div class="text-xs uppercase tracking-wide text-slate-500">
                                                        Updated {formatDate(segment.started_at)}
                                                    </div>
                                                </div>
                                                <div class="flex items-center gap-2 text-xs text-slate-500">
                                                    <button class="btn btn-xs btn-outline" onclick={() => downloadSegment(segment.id)}>
                                                        Export
                                                    </button>
                                                    <button
                                                        class="btn btn-ghost btn-xs"
                                                        title={`Started: ${formatDate(segment.started_at)}\nEnded: ${formatDate(segment.ended_at)}\nRaw reference: ${segment.raw_reference ?? '—'}`}
                                                    >
                                                        ⓘ
                                                    </button>
                                                </div>
                                            </div>
                                            <div class="markdown text-sm wrap-break-word">
                                                {@html renderMarkdown(segment.content_markdown ?? '')}
                                            </div>
                                            {#if segment.assets?.length}
                                                <div class="space-y-3 rounded-lg border border-slate-200 bg-white/70 p-3">
                                                    <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-500">Attachments</h4>
                                                    <ul class="space-y-2">
                                                        {#each segment.assets as asset}
                                                            <li class="rounded border border-slate-200 bg-white p-2 text-sm text-slate-600 flex flex-wrap items-center justify-between gap-2">
                                                                <div class="space-x-2">
                                                                    <span class="font-semibold">{asset.file_name ?? 'Unnamed asset'}</span>
                                                                    {#if asset.mime_type}<span class="text-xs text-slate-500">({asset.mime_type})</span>{/if}
                                                                    {#if formatBytes(asset.size_bytes)}<span class="text-xs text-slate-500">· {formatBytes(asset.size_bytes)}</span>{/if}
                                                                </div>
                                                                {#if asset.has_content}
                                                                    <a class="btn btn-xs btn-outline" href={attachmentUrl(asset, true) ?? '#'} target="_blank" rel="noreferrer">Download</a>
                                                                {/if}
                                                            </li>
                                                        {/each}
                                                    </ul>
                                                </div>
                                            {/if}
                                        </article>
                                    {/each}
                                </div>
                            {/if}
                        </div>
                    </section>
                {:else if viewMode === 'sections'}
					{#if currentSegment}
						<section class="space-y-4">
							<div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3">
								<div class="flex flex-wrap gap-2">
									<button type="button" class="btn btn-sm btn-outline" onclick={firstSegment} disabled={selectedSegmentIndex === 0}>
										⤒ First
									</button>
									<button type="button" class="btn btn-sm btn-outline" onclick={previousSegment} disabled={selectedSegmentIndex === 0}>
										← Previous
									</button>
								</div>
								<span class="text-sm text-slate-600">
									Segment {visibleSegments.length ? selectedSegmentIndex + 1 : 0} of {visibleSegments.length}
								</span>
								<div class="flex flex-wrap gap-2">
									<button
										type="button"
										class="btn btn-sm btn-outline"
										onclick={nextSegment}
										disabled={selectedSegmentIndex >= visibleSegments.length - 1}
									>
										Next →
									</button>
									<button
										type="button"
										class="btn btn-sm btn-outline"
										onclick={lastSegment}
										disabled={selectedSegmentIndex >= visibleSegments.length - 1}
									>
										Last ⤓
									</button>
								</div>
							</div>

							<div role="group" class="card rounded-lg border border-slate-200 bg-white shadow-lg">
								<div class={`card-body space-y-6 ${currentSegment ? segmentAccentClass(currentSegment.source_role) : ''}`}>
									<header class="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
										<span
											class={`badge badge-lg border-none px-4 py-1 text-sm font-semibold uppercase tracking-wide ${
												currentSegment.source_role === 'assistant'
													? 'badge-secondary'
													: currentSegment.source_role === 'user'
														? 'badge-info'
														: 'badge-outline'
											}`}
										>
											{roleLabel(currentSegment.source_role)}
										</span>
										<div class="flex flex-wrap items-center gap-2">
											<span>{formatDate(currentSegment.started_at)} · {currentSegment.segment_type}</span>
											<button
												class="btn btn-xs btn-outline"
												onclick={() => downloadSegment(currentSegment.id)}
												oncontextmenu={(event) => {
													event.preventDefault();
													downloadSegment(currentSegment.id);
												}}
											>
												Export
											</button>
										</div>
									</header>

									{#if segmentedContent.length}
										<div class="space-y-6">
											{#each segmentedContent as part, index}
												{#if part.kind === 'markdown'}
													<div class="markdown">
														{@html renderMarkdown(part.content)}
													</div>
												{:else}
													<div class="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-4">
														<div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
															<span>{normalizeFenceLanguage(part.language)} snippet {part.snippet}</span>
															<div class="flex flex-wrap gap-2">
																<button class="btn btn-xs btn-outline" onclick={() => copyCodeToClipboard(part.content)}>
																	Copy
																</button>
																<button
																	class="btn btn-xs btn-outline"
																	onclick={() => downloadCode(part.content, `segment-${currentSegment.sequence}-code-${part.snippet}.txt`)}
																>
																	Download
																</button>
															</div>
														</div>
														<pre class="code-block overflow-x-auto rounded-md border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-900"><code>{@html highlightCode(part.content, part.language).trim()}</code></pre>
													</div>
												{/if}
											{/each}
										</div>
									{:else}
										<div class="markdown">
											{@html renderMarkdown(currentSegment.content_markdown)}
										</div>
									{/if}

									{#if hasDetailedBlocks}
										<div class="space-y-4">
											{#each currentSegment.blocks as block}
												{#if block.block_type !== 'markdown'}
												<div class="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
													<div class="flex flex-wrap items-center gap-2 text-xs">
														<span class="badge badge-outline">{blockLabelType(block.block_type)}</span>
														{#if block.language}
															<span class="badge badge-outline badge-success">{block.language}</span>
														{/if}
													</div>
													{#if block.block_type === 'code'}
														<div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
															<span>{normalizeFenceLanguage(block.language ?? null)} block</span>
															<div class="flex flex-wrap gap-2">
																<button class="btn btn-xs btn-outline" onclick={() => copyCodeToClipboard(block.body)}>
																	Copy
																</button>
																<button
																	class="btn btn-xs btn-outline"
																	onclick={() => downloadCode(block.body, `segment-${currentSegment.sequence}-code-block-${block.sequence}.txt`)}
																>
																	Download
																</button>
															</div>
														</div>
														<pre class="code-block overflow-x-auto rounded-md border border-slate-200 bg-slate-100 p-4 text-sm leading-relaxed text-slate-900"><code>{@html highlightCode(block.body, block.language ?? null).trim()}</code></pre>
													{:else}
														<div class="markdown">
															{@html renderMarkdown(block.body)}
														</div>
													{/if}
												</div>
												{/if}
											{/each}
										</div>
									{/if}

									{#if currentSegment.assets.length}
										<div class="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
											<h4 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Attachments</h4>
											<ul class="space-y-3">
												{#each currentSegment.assets as asset}
													<li class="space-y-3 rounded-md border border-slate-200 bg-white p-3 text-sm">
														<div class="flex flex-wrap items-center justify-between gap-3">
															<div class="flex flex-wrap items-center gap-2">
																<span class="badge badge-outline badge-info">{asset.asset_type}</span>
																<span class="font-semibold text-slate-900">{asset.file_name ?? 'Unnamed asset'}</span>
																{#if asset.mime_type}
																	<span class="text-xs text-slate-500">({asset.mime_type})</span>
																{/if}
																{#if formatBytes(asset.size_bytes)}
																	<span class="text-xs text-slate-500">· {formatBytes(asset.size_bytes)}</span>
																{/if}
															</div>
															<div class="flex flex-wrap gap-2">
																{#if asset.has_content}
																	<a
																		class="btn btn-xs btn-outline"
																		href={attachmentUrl(asset, true) ?? '#'}
																		target="_blank"
																		rel="noreferrer"
																	>
																		Download
																	</a>
																{/if}
															</div>
														</div>
														{#if asset.has_content}
															{#if isImageAsset(asset)}
																<img
																	src={attachmentUrl(asset) ?? ''}
																	alt={asset.file_name ?? 'Attachment preview'}
																	class="w-full max-h-[360px] rounded-sm border border-slate-200 bg-white object-contain"
																	loading="lazy"
																/>
															{:else}
																<p class="text-xs text-slate-500">Preview not available. Use the download button to view this attachment.</p>
															{/if}
														{:else}
															<p class="text-xs text-slate-500">Content not available for this attachment.</p>
														{/if}
													</li>
												{/each}
											</ul>
										</div>
									{/if}
								</div>
							</div>
						</section>
					{:else}
						<div class="alert alert-info bg-slate-50 text-slate-600">
							<span>No segments to display. Try showing empty segments or pick another document.</span>
						</div>
					{/if}
				{/if}
		{:else}
			<div class="alert alert-info bg-slate-50 text-slate-600">
				<span>Select a document to begin.</span>
			</div>
		{/if}
	</main>
</div>
