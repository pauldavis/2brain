<script lang="ts">
	import type { PageData } from './$types';
	import type { DocumentSummary, DocumentView, Segment } from '$lib/types';
	import { marked } from 'marked';

	export let data: PageData;

	const API_BASE = data.apiBase;

	let documents: DocumentSummary[] = data.documents;
	let searchTerm = '';
	$: filteredDocuments = documents.filter((doc) =>
		doc.title.toLowerCase().includes(searchTerm.toLowerCase())
	);

	let selectedDocument: DocumentView | null = data.initialDocument;
	let selectedDocumentId: string | null = selectedDocument?.document.id ?? null;
	let selectedSegmentIndex = 0;
	let isLoadingDocument = false;
	let loadError = '';

	let segments: Segment[] = selectedDocument?.segments ?? [];
	let currentSegment: Segment | null = segments[selectedSegmentIndex] ?? null;

	const dateFormatter = new Intl.DateTimeFormat('en-US', {
		year: 'numeric',
		month: 'short',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit'
	});

	function formatDate(value?: string | null) {
		if (!value) return '—';
		return dateFormatter.format(new Date(value));
	}

	async function selectDocument(id: string) {
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
			selectedDocumentId = doc.document.id;
			selectedSegmentIndex = 0;
		} catch (error) {
			console.error(error);
			loadError = error instanceof Error ? error.message : 'Unknown error while loading document.';
		} finally {
			isLoadingDocument = false;
		}
	}

	function previousSegment() {
		if (!selectedDocument) return;
		selectedSegmentIndex = Math.max(0, selectedSegmentIndex - 1);
	}

	function nextSegment() {
		if (!selectedDocument) return;
		selectedSegmentIndex = Math.min(selectedDocument.segments.length - 1, selectedSegmentIndex + 1);
	}

	$: segments = selectedDocument?.segments ?? [];
	$: currentSegment = segments[selectedSegmentIndex] ?? null;

	marked.setOptions({ breaks: true, gfm: true });
	const markdownCache = new Map<string, string>();
	function renderMarkdown(text: string) {
		if (!text) return '';
		const cached = markdownCache.get(text);
		if (cached) return cached;
		const html = marked.parse(text);
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
</script>

<div class="page">
	<aside class="sidebar">
		<div class="sidebar-header">
			<h1>Documents</h1>
			<input
				type="search"
				placeholder="Filter by title"
				bind:value={searchTerm}
				autocomplete="off"
			/>
		</div>
		{#if filteredDocuments.length === 0}
			<p class="empty">No documents match that filter.</p>
		{:else}
			<ul class="document-list">
				{#each filteredDocuments as doc}
					<li class:selected={doc.id === selectedDocumentId}>
						<button type="button" on:click={() => selectDocument(doc.id)} disabled={isLoadingDocument}>
							<span class="title">{doc.title}</span>
							<span class="meta">
								<span class="badge">{doc.source_system}</span>
								<span>{doc.segment_count} segments</span>
							</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<main class="content">
		{#if isLoadingDocument}
			<div class="loading">Loading document…</div>
		{/if}
		{#if loadError}
			<div class="error">{loadError}</div>
		{/if}
		{#if selectedDocument}
			<section class="document-meta">
				<header>
					<div>
						<h2>{selectedDocument.document.title}</h2>
						<div class="labels">
							<span class="badge">{selectedDocument.document.source_system}</span>
							<span class="badge muted">segments: {selectedDocument.segments.length}</span>
							{#if selectedDocument.keywords.length}
								<span class="badge muted">keywords: {selectedDocument.keywords.length}</span>
							{/if}
						</div>
					</div>
					<div class="timestamps">
						<div><strong>Created:</strong> {formatDate(selectedDocument.document.created_at)}</div>
						<div><strong>Updated:</strong> {formatDate(selectedDocument.document.updated_at)}</div>
						<div><strong>Ingested:</strong> {formatDate(selectedDocument.version.ingested_at)}</div>
					</div>
				</header>
				{#if selectedDocument.document.summary}
					<p class="summary">{selectedDocument.document.summary}</p>
				{/if}
				{#if selectedDocument.keywords.length}
					<div class="keywords">
						<h3>Keywords</h3>
						<ul>
							{#each selectedDocument.keywords as keyword}
								<li>{keyword.term}</li>
							{/each}
						</ul>
					</div>
				{/if}
			</section>

			{#if currentSegment}
				<section class="segment-viewer">
					<div class="segment-controls">
						<button type="button" on:click={previousSegment} disabled={selectedSegmentIndex === 0}>
							← Previous
						</button>
						<span>
							Segment {selectedSegmentIndex + 1} of {segments.length}
						</span>
						<button
							type="button"
							on:click={nextSegment}
							disabled={selectedSegmentIndex >= segments.length - 1}
						>
							Next →
						</button>
					</div>

					<div class="segment-card">
						<header>
							<span class={`role ${currentSegment.source_role}`}>
								{roleLabel(currentSegment.source_role)}
							</span>
							<span class="segment-meta">
								{formatDate(currentSegment.started_at)} · {currentSegment.segment_type}
							</span>
						</header>

						<div class="segment-body markdown">
							{@html renderMarkdown(currentSegment.content_markdown)}
						</div>

							{#if currentSegment.blocks.length > 1}
								<div class="blocks">
									{#each currentSegment.blocks as block}
										<div class="block">
											<div class="block-header">
												<span class="badge muted">{blockLabelType(block.block_type)}</span>
												{#if block.language}
													<span class="badge code">{block.language}</span>
												{/if}
											</div>
											{#if block.block_type === 'code'}
												<pre><code>{block.body}</code></pre>
											{:else}
												<div class="markdown">
													{@html renderMarkdown(block.body)}
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{/if}

						{#if currentSegment.assets.length}
							<div class="assets">
								<h4>Attachments</h4>
								<ul>
									{#each currentSegment.assets as asset}
										<li>
											<span class="badge muted">{asset.asset_type}</span>
											<strong>{asset.file_name ?? 'Unnamed asset'}</strong>
											{#if asset.mime_type} <span class="dim">({asset.mime_type})</span>{/if}
											{#if asset.size_bytes} <span class="dim">· {asset.size_bytes} bytes</span>{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					</div>
				</section>
			{:else}
				<p class="empty">This document has no segments.</p>
			{/if}
		{:else}
			<p class="empty">Select a document to begin.</p>
		{/if}
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
		background: #0f172a;
		color: #e2e8f0;
	}

	.page {
		display: grid;
		grid-template-columns: 320px 1fr;
		min-height: 100vh;
	}

	.sidebar {
		border-right: 1px solid rgba(148, 163, 184, 0.2);
		padding: 1.5rem;
		background: rgba(15, 23, 42, 0.9);
		backdrop-filter: blur(12px);
	}

	.sidebar-header {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}

	.sidebar h1 {
		font-size: 1.3rem;
		margin: 0;
	}

	.sidebar input {
		background: rgba(30, 41, 59, 0.8);
		border: 1px solid rgba(148, 163, 184, 0.3);
		color: inherit;
		padding: 0.5rem 0.75rem;
		border-radius: 0.5rem;
	}

	.document-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		max-height: calc(100vh - 160px);
		overflow-y: auto;
	}

	.document-list li button {
		all: unset;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		width: 100%;
		padding: 0.8rem;
		border-radius: 0.75rem;
		background: rgba(30, 41, 59, 0.7);
		cursor: pointer;
		transition: transform 0.12s ease, background 0.2s ease;
	}

	.document-list li button:hover,
	.document-list li.selected button {
		background: linear-gradient(135deg, #1e293b, #334155);
		transform: translateY(-1px);
	}

	.document-list .title {
		font-weight: 600;
	}

	.document-list .meta {
		display: flex;
		gap: 0.5rem;
		font-size: 0.85rem;
		color: #cbd5f5;
		align-items: center;
	}

	.badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: rgba(59, 130, 246, 0.2);
		color: #93c5fd;
		border-radius: 999px;
		padding: 0.1rem 0.5rem;
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.badge.muted {
		background: rgba(148, 163, 184, 0.2);
		color: #cbd5f5;
	}

	.badge.code {
		background: rgba(45, 212, 191, 0.2);
		color: #5eead4;
	}

	.content {
		padding: 2rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.document-meta {
		background: rgba(15, 23, 42, 0.8);
		padding: 1.5rem;
		border-radius: 1.25rem;
		box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.45);
		border: 1px solid rgba(148, 163, 184, 0.2);
	}

	.document-meta header {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		align-items: flex-start;
	}

	.document-meta h2 {
		margin: 0;
		font-size: 1.6rem;
	}

	.labels {
		display: flex;
		gap: 0.5rem;
		margin-top: 0.5rem;
		flex-wrap: wrap;
	}

	.timestamps {
		font-size: 0.85rem;
		color: #cbd5f5;
		display: grid;
		gap: 0.25rem;
		text-align: right;
	}

	.summary {
		margin-top: 1rem;
		line-height: 1.6;
		color: #e2e8f0;
	}

	.keywords ul {
		list-style: none;
		display: flex;
		gap: 0.5rem;
		padding: 0;
		margin: 0.5rem 0 0;
		flex-wrap: wrap;
	}

	.keywords li {
		background: rgba(15, 118, 110, 0.25);
		color: #5eead4;
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		font-size: 0.75rem;
	}

	.segment-viewer {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.segment-controls {
		display: flex;
		justify-content: space-between;
		align-items: center;
		background: rgba(15, 23, 42, 0.8);
		padding: 0.8rem 1rem;
		border-radius: 0.9rem;
		border: 1px solid rgba(148, 163, 184, 0.2);
	}

	.segment-controls button {
		background: rgba(59, 130, 246, 0.25);
		color: #bfdbfe;
		border: none;
		padding: 0.4rem 0.9rem;
		border-radius: 0.75rem;
		font-weight: 600;
		cursor: pointer;
		transition: background 0.2s ease, transform 0.2s ease;
	}

	.segment-controls button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.segment-controls button:not(:disabled):hover {
		background: rgba(59, 130, 246, 0.35);
		transform: translateY(-1px);
	}

	.segment-card {
		background: rgba(15, 23, 42, 0.85);
		border-radius: 1.25rem;
		border: 1px solid rgba(148, 163, 184, 0.16);
		padding: 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		box-shadow: 0 20px 40px -25px rgba(15, 23, 42, 0.8);
	}

	.segment-card header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: 0.9rem;
	}

	.role {
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.role.user {
		color: #93c5fd;
	}

	.role.assistant {
		color: #f0abfc;
	}

	.role.system,
	.role.tool {
		color: #86efac;
	}

	.segment-meta {
		color: #cbd5f5;
		font-size: 0.8rem;
	}

	.segment-body {
		font-size: 1rem;
		line-height: 1.6;
	}

	.markdown :global(p) {
		margin: 0 0 1rem 0;
	}

	.markdown :global(p:last-child) {
		margin-bottom: 0;
	}

	.markdown :global(strong) {
		color: #f1f5f9;
	}

	.markdown :global(em) {
		color: #fbcfe8;
	}

	.markdown :global(a) {
		color: #93c5fd;
		text-decoration: underline;
		text-decoration-color: rgba(147, 197, 253, 0.4);
	}

	.markdown :global(ul),
	.markdown :global(ol) {
		margin: 0 0 1rem 1.2rem;
		padding: 0;
	}

	.markdown :global(li) {
		margin-bottom: 0.35rem;
	}

	.blocks {
		display: grid;
		gap: 1rem;
	}

	.block {
		background: rgba(30, 41, 59, 0.75);
		border-radius: 1rem;
		padding: 1rem;
		border: 1px solid rgba(148, 163, 184, 0.15);
	}

	.block-header {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		margin-bottom: 0.75rem;
	}

	pre {
		margin: 0;
		padding: 1rem;
		background: rgba(15, 23, 42, 0.9);
		border-radius: 0.75rem;
		overflow-x: auto;
		font-size: 0.85rem;
		line-height: 1.5;
		border: 1px solid rgba(148, 163, 184, 0.15);
	}

	.assets ul {
		list-style: none;
		padding: 0;
		margin: 0.5rem 0 0;
		display: grid;
		gap: 0.5rem;
	}

	.assets li {
		background: rgba(30, 41, 59, 0.7);
		padding: 0.75rem;
		border-radius: 0.75rem;
		border: 1px solid rgba(148, 163, 184, 0.15);
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.dim {
		color: #94a3b8;
		font-size: 0.8rem;
	}

	.loading,
	.error,
	.empty {
		background: rgba(15, 23, 42, 0.8);
		padding: 1rem;
		border-radius: 0.75rem;
		border: 1px solid rgba(148, 163, 184, 0.2);
	}

	.error {
		color: #fecaca;
		border-color: rgba(248, 113, 113, 0.45);
	}

	@media (max-width: 1024px) {
		.page {
			grid-template-columns: 1fr;
		}

		.sidebar {
			position: sticky;
			top: 0;
			z-index: 10;
			border-right: none;
			border-bottom: 1px solid rgba(148, 163, 184, 0.2);
		}

		.document-list {
			max-height: 220px;
		}
	}
</style>
