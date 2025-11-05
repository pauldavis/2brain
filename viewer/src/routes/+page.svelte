<script lang="ts">
	import type { PageData } from './$types';
	import type { DocumentSummary, DocumentView, Segment } from '$lib/types';
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

	const segments = $derived<Segment[]>(selectedDocument?.segments ?? []);
	const currentSegment = $derived<Segment | null>(segments[selectedSegmentIndex] ?? null);

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
		selectedSegmentIndex = Math.min(segments.length - 1, selectedSegmentIndex + 1);
	}

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

<div class="flex min-h-screen flex-col bg-slate-950 text-slate-100 md:grid md:grid-cols-[320px_1fr]">
	<aside class="border-b border-slate-800 bg-slate-900/80 backdrop-blur md:border-b-0 md:border-r">
		<div class="flex h-full flex-col gap-4 p-6">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight">Documents</h1>
				<p class="mt-1 text-sm text-slate-400">Filter and choose a conversation to review.</p>
			</div>

			<label class="input input-bordered flex items-center gap-2 bg-slate-900/50">
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
				<div class="alert alert-warning bg-amber-500/10 text-amber-200">
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
									class={`w-full rounded-2xl border border-slate-800 bg-slate-900/70 p-4 text-left transition hover:border-slate-600 hover:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500/60 ${
										doc.id === selectedDocumentId ? 'border-sky-500/60 bg-slate-800/80 shadow-lg shadow-sky-900/30' : ''
									}`}
									disabled={isLoadingDocument}
								>
									<div class="flex items-start justify-between gap-3">
										<span class="line-clamp-2 text-sm font-semibold tracking-tight">{doc.title}</span>
										<span class="badge badge-outline badge-info uppercase">{doc.source_system}</span>
									</div>
									<div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-300">
										<span class="badge badge-sm badge-outline">{doc.segment_count} segments</span>
										<span>Updated {formatDate(doc.updated_at)}</span>
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
			<section class="card border border-slate-800 bg-slate-900/80 shadow-xl">
				<div class="card-body gap-6">
					<div class="flex flex-col justify-between gap-6 lg:flex-row lg:items-start">
						<div class="space-y-3">
							<h2 class="card-title text-3xl font-semibold">{selectedDocument.document.title}</h2>
							<div class="flex flex-wrap items-center gap-3 text-xs text-slate-300">
								<span class="badge badge-primary badge-outline uppercase">{selectedDocument.document.source_system}</span>
								<span class="badge badge-outline">Segments: {selectedDocument.segments.length}</span>
								{#if selectedDocument.keywords.length}
									<span class="badge badge-outline">Keywords: {selectedDocument.keywords.length}</span>
								{/if}
							</div>
						</div>
						<div class="grid gap-2 text-sm text-slate-300">
							<span><strong class="font-semibold text-slate-100">Created:</strong> {formatDate(selectedDocument.document.created_at)}</span>
							<span><strong class="font-semibold text-slate-100">Updated:</strong> {formatDate(selectedDocument.document.updated_at)}</span>
							<span><strong class="font-semibold text-slate-100">Ingested:</strong> {formatDate(selectedDocument.version.ingested_at)}</span>
						</div>
					</div>

					{#if selectedDocument.document.summary}
						<p class="rounded-2xl border border-slate-800/70 bg-slate-950/50 p-4 leading-relaxed text-slate-200">
							{selectedDocument.document.summary}
						</p>
					{/if}

					{#if selectedDocument.keywords.length}
						<div>
							<h3 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Keywords</h3>
							<div class="mt-2 flex flex-wrap gap-2">
								{#each selectedDocument.keywords as keyword}
									<span class="badge badge-success badge-outline">{keyword.term}</span>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			</section>

			{#if currentSegment}
				<section class="space-y-4">
					<div class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/80 px-4 py-3">
						<button type="button" class="btn btn-sm btn-outline" onclick={previousSegment} disabled={selectedSegmentIndex === 0}>
							← Previous
						</button>
						<span class="text-sm text-slate-300">Segment {selectedSegmentIndex + 1} of {segments.length}</span>
						<button
							type="button"
							class="btn btn-sm btn-outline"
							onclick={nextSegment}
							disabled={selectedSegmentIndex >= segments.length - 1}
						>
							Next →
						</button>
					</div>

					<div class="card border border-slate-800 bg-slate-900/80 shadow-lg">
						<div class="card-body space-y-6">
							<header class="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-300">
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
								<span>{formatDate(currentSegment.started_at)} · {currentSegment.segment_type}</span>
							</header>

							<div class="markdown">
								{@html renderMarkdown(currentSegment.content_markdown)}
							</div>

							{#if currentSegment.blocks.length > 1}
								<div class="space-y-4">
									{#each currentSegment.blocks as block}
										<div class="space-y-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
											<div class="flex flex-wrap items-center gap-2 text-xs">
												<span class="badge badge-outline">{blockLabelType(block.block_type)}</span>
												{#if block.language}
													<span class="badge badge-outline badge-success">{block.language}</span>
												{/if}
											</div>
											{#if block.block_type === 'code'}
												<pre class="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/80 p-4 text-sm leading-relaxed text-slate-100"><code>{block.body}</code></pre>
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
								<div class="space-y-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
									<h4 class="text-sm font-semibold uppercase tracking-wide text-slate-400">Attachments</h4>
									<ul class="space-y-2">
										{#each currentSegment.assets as asset}
											<li class="flex flex-wrap items-center gap-3 rounded-xl border border-slate-800/80 bg-slate-900/70 px-3 py-2 text-sm">
												<span class="badge badge-outline badge-info">{asset.asset_type}</span>
												<span class="font-semibold text-slate-100">{asset.file_name ?? 'Unnamed asset'}</span>
												{#if asset.mime_type}
													<span class="text-xs text-slate-400">({asset.mime_type})</span>
												{/if}
												{#if asset.size_bytes}
													<span class="text-xs text-slate-500">· {asset.size_bytes} bytes</span>
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
				<div class="alert alert-info bg-slate-900/80 text-slate-200">
					<span>This document has no segments.</span>
				</div>
			{/if}
		{:else}
			<div class="alert alert-info bg-slate-900/80 text-slate-200">
				<span>Select a document to begin.</span>
			</div>
		{/if}
	</main>
</div>
