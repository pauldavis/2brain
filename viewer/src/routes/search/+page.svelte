<script lang="ts">
  import type { PageData } from './$types';
  const props = $props<{ data: PageData }>();
  const data = $state(props.data);
  const API_BASE = $derived(data.apiBase);
  let q = $state('');
  let mode: 'bm25' | 'hybrid' = $state('bm25');
  let results: any[] = $state([]);
  let loading = $state(false);
  let errorMsg = $state('');
  let threshold: string = $state('');
  let w_bm25 = $state(0.5);
  let w_vec = $state(0.5);
  let k = $state(60);

  async function run() {
    loading = true; errorMsg = ''; results = [];
    try {
      const params = new URLSearchParams({ limit: '20', offset: '0' });
      let url: string;
      if (mode === 'bm25') {
        const u = new URL('search/bm25', API_BASE);
        u.searchParams.set('q', q);
        u.searchParams.set('limit', '20');
        u.searchParams.set('offset', '0');
        if (threshold.trim()) u.searchParams.set('threshold', threshold);
        url = u.toString();
      } else {
        const u = new URL('search/hybrid', API_BASE);
        u.searchParams.set('q', q);
        u.searchParams.set('w_bm25', String(w_bm25));
        u.searchParams.set('w_vec', String(w_vec));
        u.searchParams.set('k', String(k));
        u.searchParams.set('limit', '20');
        u.searchParams.set('offset', '0');
        url = u.toString();
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      results = await res.json();
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      loading = false;
    }
  }
</script>

<main class="p-6 text-slate-100 bg-slate-950 min-h-screen space-y-6">
  <h1 class="text-2xl font-semibold">Search</h1>

  <div class="space-y-3 rounded-xl border border-slate-800 p-4 bg-slate-900/70">
    <div class="flex flex-wrap items-center gap-3">
      <input class="input input-bordered bg-slate-900" placeholder="enter query" bind:value={q} />
      <select class="select select-bordered bg-slate-900" bind:value={mode}>
        <option value="bm25">BM25</option>
        <option value="hybrid">Hybrid (BM25 + Vector)</option>
      </select>
      <button class="btn btn-primary" onclick={(e)=>{ e.preventDefault(); run(); }} disabled={loading || !q.trim()}>Search</button>
    </div>

    {#if mode === 'bm25'}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <label>Score threshold (optional): <input class="input input-sm input-bordered bg-slate-900 w-32" bind:value={threshold} placeholder="-0.8" /></label>
      </div>
    {:else}
      <div class="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <label>BM25 weight <input type="number" step="0.1" min="0" max="1" class="input input-sm input-bordered bg-slate-900 w-24" bind:value={w_bm25} /></label>
        <label>Vector weight <input type="number" step="0.1" min="0" max="1" class="input input-sm input-bordered bg-slate-900 w-24" bind:value={w_vec} /></label>
        <label>k <input type="number" min="1" class="input input-sm input-bordered bg-slate-900 w-20" bind:value={k} /></label>
      </div>
    {/if}
  </div>

  {#if loading}
    <div class="alert alert-info">Searching…</div>
  {/if}
  {#if errorMsg}
    <div class="alert alert-error">{errorMsg}</div>
  {/if}

  {#if results.length}
    <ul class="space-y-3">
      {#each results as r}
        <li class="rounded-xl border border-slate-800 p-4 bg-slate-900/70">
          <div class="text-sm text-slate-300">{r.document_title} • <span class="uppercase badge badge-outline">{r.source_system}</span></div>
          <div class="mt-2 text-slate-100">{r.snippet}</div>
        </li>
      {/each}
    </ul>
  {/if}
</main>

<style>
  /* rely on existing Tailwind/DaisyUI config from viewer */
</style>
