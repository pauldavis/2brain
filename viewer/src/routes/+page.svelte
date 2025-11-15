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
	let showEmptySegments = $state(true);
	let pendingSegmentId = $state<string | null>(data.initialSegmentId ?? null);
	const visibleSegments = $derived<Segment[]>(
		showEmptySegments
			? segments
			: segments.filter((segment) => segmentHasContent(segment))
	);
	const hiddenSegmentCount = $derived(Math.max(0, segments.length - visibleSegments.length));
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

	function formatDate(value?: string | null) {
		if (!value) return '—';
		return dateFormatter.format(new Date(value));
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

	type CodeFence = {
		language: string | null;
		content: string;
	};

	function normalizeFenceLanguage(language: string | null): string {
		if (!language) return 'PLAINTEXT';
		const lower = language.toLowerCase();
		if (lower === 'jsonc' || lower === 'json') return 'JSON';
		if (lower === 'mermaid') return 'MERMAID';
		return lower.toUpperCase();
	}

	function extractCodeFences(markdown?: string | null): CodeFence[] {
		if (!markdown) return [];
		const fences: CodeFence[] = [];
		const regex = /```([\w-]+)?\s*\n([\s\S]*?)```/g;
		let match: RegExpExecArray | null;
		// eslint-disable-next-line no-cond-assign
		while ((match = regex.exec(markdown))) {
			const language = (match[1] || '').trim() || null;
			const content = (match[2] || '').trimEnd();
			if (content) {
				fences.push({ language, content });
			}
		}
		return fences;
	}

	const codeFences = $derived(extractCodeFences(currentSegment?.content_markdown ?? null));
	const hasDetailedBlocks = $derived(() =>
		(currentSegment?.blocks ?? []).some((block) => block.block_type !== 'markdown')
	);

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
</script>

<div class="flex min-h-screen flex-col bg-slate-50 text-slate-900 md:grid md:grid-cols-[320px_1fr]">
	<aside class="border-b border-slate-200 bg-white/90 backdrop-blur md:border-b-0 md:border-r">
		<div class="flex h-full flex-col gap-4 p-6">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight">Documents</h1>
				<p class="mt-1 text-sm text-slate-500">Filter and choose a conversation to review.</p>
			</div>

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
									class={`w-full rounded-2xl border border-slate-200 bg-white p-4 text-left transition hover:border-slate-400 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-sky-500/60 ${
										doc.id === selectedDocumentId ? 'border-sky-400 bg-sky-50 shadow-lg shadow-sky-200/70' : ''
									}`}
									disabled={isLoadingDocument}
								>
									<div class="flex items-start justify-between gap-3">
										<span class="line-clamp-2 text-sm font-semibold tracking-tight">{doc.title}</span>
										<span class="badge badge-outline badge-info uppercase">{doc.source_system}</span>
									</div>
									<div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
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
			<section class="card border border-slate-200 bg-white shadow-xl">
				<div class="card-body gap-6">
					<div class="flex flex-col justify-between gap-6 lg:flex-row lg:items-start">
						<div class="space-y-3">
							<h2 class="card-title text-3xl font-semibold">{selectedDocument.document.title}</h2>
							<div class="flex flex-wrap items-center gap-3 text-xs text-slate-600">
								<span class="badge badge-primary badge-outline uppercase">{selectedDocument.document.source_system}</span>
								<span class="badge badge-outline">Segments: {selectedDocument.segments.length}</span>
								{#if selectedDocument.keywords.length}
									<span class="badge badge-outline">Keywords: {selectedDocument.keywords.length}</span>
								{/if}
							</div>
						</div>
						<div class="grid gap-2 text-sm text-slate-600">
							<span><strong class="font-semibold text-slate-900">Created:</strong> {formatDate(selectedDocument.document.created_at)}</span>
							<span><strong class="font-semibold text-slate-900">Updated:</strong> {formatDate(selectedDocument.document.updated_at)}</span>
							<span><strong class="font-semibold text-slate-900">Ingested:</strong> {formatDate(selectedDocument.version.ingested_at)}</span>
						</div>
					</div>

					<div class="flex flex-wrap items-center gap-3">
						<button
							class="btn btn-sm btn-outline"
							onclick={() => (showEmptySegments = !showEmptySegments)}
						>
							{showEmptySegments ? 'Hide empty segments' : 'Show all segments'}
						</button>
						{#if hiddenSegmentCount > 0 && !showEmptySegments}
							<span class="text-xs text-slate-500">
								Hiding {hiddenSegmentCount} empty segment{hiddenSegmentCount === 1 ? '' : 's'}
							</span>
						{/if}
					</div>

					{#if selectedDocument.document.summary}
						<p class="rounded-2xl border border-slate-200 bg-slate-50 p-4 leading-relaxed text-slate-700">
							{selectedDocument.document.summary}
						</p>
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
				</div>
			</section>

			<section class="card border border-slate-200 bg-white shadow-xl">
				<div class="card-body space-y-4">
					<div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
						<div>
							<h3 class="text-xl font-semibold">Full conversation transcript</h3>
							<p class="text-sm text-slate-500">
								View every segment together or download a Markdown copy for sharing.
							</p>
						</div>
						<div class="flex flex-wrap gap-2">
							<button
								type="button"
								class="btn btn-sm btn-primary"
								onclick={() => loadTranscript(transcript?.document.id === selectedDocumentId)}
								disabled={!selectedDocumentId || isTranscriptLoading}
							>
								{transcript && transcript.document.id === selectedDocumentId ? 'Refresh transcript' : 'Load transcript'}
							</button>
							{#if transcriptDownloadUrl}
								<a
									class="btn btn-sm btn-outline"
									href={transcriptDownloadUrl}
									target="_blank"
									rel="noreferrer"
								>
									Download Markdown
								</a>
							{:else}
								<button class="btn btn-sm btn-outline" disabled>Download Markdown</button>
							{/if}
						</div>
					</div>

					{#if isTranscriptLoading}
						<div class="alert alert-info bg-slate-50 text-slate-600">
							<span>Loading transcript…</span>
						</div>
					{:else if transcriptError}
						<div class="alert alert-error bg-slate-50 text-slate-600">
							<span>{transcriptError}</span>
						</div>
					{:else if transcript && transcript.document.id === selectedDocumentId}
						<div class="markdown prose max-w-none rounded-2xl border border-slate-200 bg-white p-4">
							{@html renderMarkdown(transcript.markdown)}
						</div>
					{:else}
						<p class="text-sm text-slate-500">Load the transcript to render the entire conversation in order.</p>
					{/if}
				</div>
			</section>

			{#if currentSegment}
				<section class="space-y-4">
					<div class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
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

					<div
						role="group"
						class="card border border-slate-200 bg-white shadow-lg"
						oncontextmenu={(event) => {
							event.preventDefault();
							if (currentSegment) downloadSegment(currentSegment.id);
						}}
					>
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
									<button class="btn btn-xs btn-outline" onclick={() => downloadSegment(currentSegment.id)}>Export</button>
								</div>
							</header>

							<div class="markdown">
								{@html renderMarkdown(currentSegment.content_markdown)}
							</div>

							{#if hasDetailedBlocks}
								<div class="space-y-4">
									{#each currentSegment.blocks as block}
										{#if block.block_type !== 'markdown'}
										<div class="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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
												<pre class="overflow-x-auto rounded-xl border border-slate-200 bg-slate-100 p-4 text-sm leading-relaxed text-slate-900"><code>{block.body}</code></pre>
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

							{#if codeFences.length}
								<div class="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
									<h4 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Code snippets</h4>
									{#each codeFences as fence, index}
										<div class="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
											<div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
												<span>{normalizeFenceLanguage(fence.language)} snippet {index + 1}</span>
												<div class="flex flex-wrap gap-2">
													<button class="btn btn-xs btn-outline" onclick={() => copyCodeToClipboard(fence.content)}>
														Copy
													</button>
													<button
														class="btn btn-xs btn-outline"
														onclick={() => downloadCode(fence.content, `segment-${currentSegment.sequence}-code-${index + 1}.txt`)}
													>
														Download
													</button>
												</div>
											</div>
											<pre class="overflow-x-auto rounded-xl border border-slate-200 bg-slate-100 p-4 text-sm leading-relaxed text-slate-900">
												<code>{fence.content}</code>
											</pre>
										</div>
									{/each}
								</div>
							{/if}

							{#if currentSegment.assets.length}
								<div class="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
									<h4 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Attachments</h4>
									<ul class="space-y-3">
										{#each currentSegment.assets as asset}
											<li class="space-y-3 rounded-xl border border-slate-200 bg-white p-3 text-sm">
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
															class="w-full max-h-[360px] rounded-lg border border-slate-200 bg-white object-contain"
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
		{:else}
			<div class="alert alert-info bg-slate-50 text-slate-600">
				<span>Select a document to begin.</span>
			</div>
		{/if}
	</main>
</div>
