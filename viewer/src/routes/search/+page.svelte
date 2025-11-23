<script lang="ts">
  import type { PageData } from './$types';
  import type { DocumentSearchResult, SearchResult } from '$lib/types';

  const props = $props<{ data: PageData }>();
  const data = $state(props.data);
  const API_BASE = $derived(data.apiBase);
  let q = $state('');
  let mode: 'bm25' | 'hybrid' = $state('bm25');
  let segmentResults = $state<SearchResult[]>([]);
  let documentResults = $state<DocumentSearchResult[]>([]);
  let loading = $state(false);
  let errorMsg = $state('');
  let threshold: string = $state('');
  let w_bm25 = $state(0.5);
  let w_vec = $state(0.5);
  let k = $state(60);
  let plan = $state<any | null>(null);
  let planError = $state('');
  let planLoading = $state(false);
  let analyzePlan = $state(false);

  const dateFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', day: '2-digit', year: 'numeric' });
  const numberFormatter = new Intl.NumberFormat();
  const percentFormatter = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 });

  function formatDate(value?: string | null) {
    if (!value) return '—';
    return dateFormatter.format(new Date(value));
  }

  function formatChars(value?: number | null) {
    if (!value) return '0';
    return numberFormatter.format(value);
  }

  function formatNumber(value?: number | null) {
    if (value === undefined || value === null) return '0';
    return numberFormatter.format(value);
  }

  function formatPercent(value?: number | null) {
    if (typeof value !== 'number' || Number.isNaN(value)) return '0%';
    return percentFormatter.format(Math.max(0, value));
  }

  function applyCommonSearchParams(u: URL) {
    u.searchParams.set('limit', '20');
    u.searchParams.set('offset', '0');
  }

  async function run() {
    loading = true; errorMsg = ''; segmentResults = []; documentResults = [];
    try {
      let url: string;
      if (mode === 'bm25') {
        const u = new URL('search/bm25', API_BASE);
        u.searchParams.set('q', q);
        applyCommonSearchParams(u);
        if (threshold.trim()) u.searchParams.set('threshold', threshold);
        url = u.toString();
      } else {
        const u = new URL('search/hybrid_documents', API_BASE);
        u.searchParams.set('q', q);
        u.searchParams.set('w_bm25', String(w_bm25));
        u.searchParams.set('w_vec', String(w_vec));
        u.searchParams.set('k', String(k));
        applyCommonSearchParams(u);
        url = u.toString();
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (mode === 'bm25') {
        segmentResults = await res.json();
      } else {
        documentResults = await res.json();
      }
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      loading = false;
    }
  }

  async function explain() {
    if (!q.trim()) {
      planError = 'Enter a query first.';
      return;
    }
    planLoading = true; planError = ''; plan = null;
    try {
      const u = new URL('stats/search_plan', API_BASE);
      u.searchParams.set('mode', mode);
      u.searchParams.set('q', q);
      applyCommonSearchParams(u);
      u.searchParams.set('analyze', analyzePlan ? 'true' : 'false');
      if (mode === 'bm25') {
        if (threshold.trim()) u.searchParams.set('threshold', threshold);
      } else {
        u.searchParams.set('w_bm25', String(w_bm25));
        u.searchParams.set('w_vec', String(w_vec));
        u.searchParams.set('k', String(k));
      }
      const res = await fetch(u.toString());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || 'Explain failed');
      plan = json;
    } catch (e) {
      planError = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      planLoading = false;
    }
  }

  function downloadSegment(segmentId: string, title: string) {
    const url = `${API_BASE}/documents/segments/${segmentId}/export?format=markdown&download=1`;
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noreferrer';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  function renderSnippet(text: string) {
    if (!text) return '';
    return text
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`[^`]*`/g, '')
      .replace(/!?\[(.*?)\]\((.*?)\)/g, '$1')
      .replace(/[*_~]/g, '')
      .replace(/^>\s?/gm, '')
      .replace(/^#+\s?/gm, '')
      .replace(/-{3,}/g, '—')
      .trim();
  }
</script>

<main class="min-h-screen space-y-6 bg-slate-50 p-6 text-slate-900">
  <h1 class="text-2xl font-semibold text-slate-900">Search</h1>

  <div class="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex flex-wrap items-center gap-3">
      <input class="input input-bordered bg-white" placeholder="enter query" bind:value={q} />
      <select class="select select-bordered bg-white" bind:value={mode}>
        <option value="bm25">BM25</option>
        <option value="hybrid">Hybrid (BM25 + Vector)</option>
      </select>
      <button class="btn btn-primary" onclick={(e)=>{ e.preventDefault(); run(); }} disabled={loading || !q.trim()}>Search</button>
      <button class="btn" onclick={(e)=>{ e.preventDefault(); explain(); }} disabled={planLoading || !q.trim()}>
        {#if planLoading}<span class="loading loading-spinner loading-sm"></span>{/if}
        Explain query
      </button>
      <label class="label cursor-pointer gap-2 text-slate-600">
        <input type="checkbox" class="toggle toggle-sm" bind:checked={analyzePlan} />
        <span class="label-text text-xs">Analyze (executes query)</span>
      </label>
    </div>

    {#if mode === 'bm25'}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <label>Score threshold (optional): <input class="input input-sm input-bordered bg-white w-32" bind:value={threshold} placeholder="-0.8" /></label>
      </div>
    {:else}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <label>BM25 weight <input type="number" step="0.1" min="0" max="1" class="input input-sm input-bordered bg-white w-24" bind:value={w_bm25} /></label>
        <label>Vector weight <input type="number" step="0.1" min="0" max="1" class="input input-sm input-bordered bg-white w-24" bind:value={w_vec} /></label>
        <label>k <input type="number" min="1" class="input input-sm input-bordered bg-white w-20" bind:value={k} /></label>
      </div>
    {/if}
  </div>

  {#if loading}
    <div class="alert alert-info bg-slate-50 text-slate-600">Searching…</div>
  {/if}
  {#if errorMsg}
    <div class="alert alert-error bg-rose-50 text-rose-600">{errorMsg}</div>
  {/if}

  <section class="rounded-xl border border-dashed border-slate-300 bg-white/60 p-4">
    <h2 class="text-lg font-semibold text-slate-900">Instrumentation</h2>
    <p class="text-sm text-slate-600">Use "Explain query" to inspect planner output for the current mode/parameters.</p>
    {#if planError}
      <div class="alert alert-error mt-3 bg-rose-50 text-rose-600">{planError}</div>
    {/if}
    {#if plan}
      <div class="mt-3 grid gap-4 md:grid-cols-2">
        <div class="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 space-y-1">
          <div><span class="font-semibold">Mode:</span> {plan.metadata?.mode}</div>
          <div><span class="font-semibold">Planning:</span> {plan.planning_time_ms ?? '—'} ms</div>
          <div><span class="font-semibold">Execution:</span> {plan.execution_time_ms ?? (analyzePlan ? 'n/a' : 'plan only')}</div>
          <div><span class="font-semibold">Limit/Offset:</span> {plan.metadata?.limit}/{plan.metadata?.offset}</div>
        </div>
        <div class="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600 overflow-auto">
          <pre class="text-xs whitespace-pre-wrap">{JSON.stringify(plan.metadata, null, 2)}</pre>
        </div>
      </div>
      <div class="mt-4 rounded-lg border border-slate-200 bg-slate-900/5 p-3 text-xs overflow-auto">
        <pre>{JSON.stringify(plan.plan, null, 2)}</pre>
      </div>
    {:else}
      <div class="mt-3 text-sm text-slate-500">No plan captured yet.</div>
    {/if}
  </section>

  {#if mode === 'bm25' && segmentResults.length}
    <ul class="space-y-3">
      {#each segmentResults as r (r.segment_id)}
        <li
          class="group rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-300"
          oncontextmenu={(event) => { event.preventDefault(); downloadSegment(r.segment_id, r.document_title); }}
        >
          <div class="flex items-start justify-between gap-3">
            <div class="text-sm text-slate-600">
              <a class="font-semibold text-slate-900 hover:text-sky-600" href={`/?document=${r.document_id}&segment=${r.segment_id}`}>
                {r.document_title}
              </a>
              <span class="ml-2 uppercase badge badge-outline">{r.source_system}</span>
            </div>
            <div class="text-xs text-slate-500 text-right space-y-0.5">
              <div>Updated {formatDate(r.document_updated_at)}</div>
              <div>{r.document_segment_count ?? 0} segments · {formatChars(r.document_char_count)} chars</div>
            </div>
          </div>
          <div class="mt-2 text-xs uppercase tracking-wide text-slate-500">
            Segment {r.sequence} · {r.source_role}
          </div>
          <div class="markdown mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm whitespace-pre-line wrap-break-word">
            {renderSnippet(r.snippet)}
          </div>
          <div class="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
            {#if r.started_at}<span>Started {formatDate(r.started_at)}</span>{/if}
            <button class="btn btn-xs btn-outline" onclick={() => downloadSegment(r.segment_id, r.document_title)}>Export segment</button>
          </div>
        </li>
      {/each}
    </ul>
  {:else if mode === 'hybrid' && documentResults.length}
    <ul class="space-y-4">
      {#each documentResults as doc (doc.document_id)}
        <li class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-300">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="text-sm text-slate-600 space-y-1">
              <a class="font-semibold text-slate-900 hover:text-sky-600" href={`/?document=${doc.document_id}`}>
                {doc.document_title}
              </a>
              <div class="space-x-2 text-xs text-slate-500">
                <span class="uppercase badge badge-outline">{doc.source_system}</span>
                <span>Score {doc.document_score.toFixed(3)}</span>
                <span>Matches {formatNumber(doc.match_count)}</span>
                <span>Density {formatPercent(doc.match_density)}</span>
              </div>
            </div>
            <div class="text-xs text-slate-500 text-right space-y-0.5">
              <div>Updated {formatDate(doc.document_updated_at)}</div>
              <div>{doc.document_segment_count ?? 0} segments · {formatChars(doc.document_char_count)} chars</div>
            </div>
          </div>
          <div class="mt-3 space-y-3">
            {#if doc.top_segments.length === 0}
              <div class="text-sm text-slate-500">No preview segments captured.</div>
            {:else}
              {#each doc.top_segments as segment, index (segment.segment_id + '-' + index)}
                {#if doc.top_segments.findIndex((s) => s.segment_id === segment.segment_id) === index}
                <div class="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-1">
                  <div class="flex flex-wrap items-center justify-between text-xs uppercase tracking-wide text-slate-500 gap-2">
                    <span>Segment {segment.sequence} · {segment.source_role}</span>
                    <span>Score {segment.score.toFixed(3)}</span>
                  </div>
                  <div class="markdown text-sm whitespace-pre-line wrap-break-word">
                    {renderSnippet(segment.snippet)}
                  </div>
                  <div class="flex flex-wrap gap-2 text-xs text-slate-500">
                    <button class="btn btn-xs btn-outline" onclick={() => downloadSegment(segment.segment_id, doc.document_title)}>Export segment</button>
                    <a class="link link-hover" href={`/?document=${doc.document_id}&segment=${segment.segment_id}`}>Open in viewer</a>
                  </div>
                </div>
                {/if}
              {/each}
            {/if}
            {#if doc.match_count > doc.top_segments.length}
              <div class="text-xs text-slate-500">
                +{formatNumber(doc.match_count - doc.top_segments.length)} more matching segment{doc.match_count - doc.top_segments.length === 1 ? '' : 's'} not shown.
              </div>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  /* rely on existing Tailwind/DaisyUI config from viewer */
</style>
