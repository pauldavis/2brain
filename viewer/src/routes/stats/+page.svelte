<script lang="ts">
    import type { PageData } from "./$types";
    import { onMount } from "svelte";

    const props = $props<{ data: PageData }>();
    const data = $state(props.data);
    const API_BASE = $derived(data.apiBase);

    type Snapshot = {
        t: string;
        vectorizer?: any;
        bm25?: any;
        coverage?: any;
        table?: any;
    };

    let snapshots = $state<Snapshot[]>([]);
    let polling = $state(true);
    let errorMsg = $state("");

    async function fetchJSON(path: string) {
        const url = new URL(path, API_BASE).toString();
        const headers: HeadersInit = {};
        // @ts-ignore
        if (data.backendToken)
            headers["Authorization"] = `Bearer ${data.backendToken}`;
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error(`${res.status} ${url}`);
        return await res.json();
    }

    async function pollOnce() {
        try {
            const [vectorizer, bm25, coverage, table, queries] =
                await Promise.all([
                    fetchJSON("stats/vectorizer"),
                    fetchJSON("stats/bm25"),
                    fetchJSON("stats/coverage"),
                    fetchJSON("stats/table"),
                    fetchJSON("stats/queries"),
                ]);
            const t = new Date().toISOString();
            snapshots = [
                { t, vectorizer, bm25, coverage, table, queries },
                ...snapshots,
            ].slice(0, 200);
        } catch (e) {
            errorMsg = e instanceof Error ? e.message : "Unknown error";
        }
    }

    let timer: any;
    onMount(() => {
        pollOnce();
        timer = setInterval(() => {
            if (polling) void pollOnce();
        }, 5000);
        return () => clearInterval(timer);
    });
</script>

<main class="min-h-screen space-y-6 bg-slate-50 p-6 text-slate-900">
    <h1 class="text-2xl font-semibold text-slate-900">Stats</h1>

    <div class="flex items-center gap-3">
        <button class="btn btn-sm" onclick={() => pollOnce()}>Refresh</button>
        <label class="label cursor-pointer gap-2">
            <span class="label-text text-slate-600">Auto refresh</span>
            <input type="checkbox" class="toggle" bind:checked={polling} />
        </label>
        {#if errorMsg}<span class="text-rose-600 text-sm">{errorMsg}</span>{/if}
    </div>

    {#if snapshots.length}
        <!-- Current snapshot summary -->
        {#key snapshots[0].t}
            <section class="grid gap-4 md:grid-cols-2">
                <div
                    class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                    <h2 class="text-lg font-semibold">Vectorizer</h2>
                    {#if snapshots[0].vectorizer?.vectorizers?.length}
                        <pre class="text-xs overflow-auto">{JSON.stringify(
                                snapshots[0].vectorizer,
                                null,
                                2,
                            )}</pre>
                    {:else}
                        <span class="text-slate-500 text-sm"
                            >No vectorizer data</span
                        >
                    {/if}
                </div>
                <div
                    class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                    <h2 class="text-lg font-semibold">BM25</h2>
                    <pre class="text-xs overflow-auto">{JSON.stringify(
                            snapshots[0].bm25,
                            null,
                            2,
                        )}</pre>
                </div>
                <div
                    class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                    <h2 class="text-lg font-semibold">Coverage</h2>
                    <pre class="text-xs overflow-auto">{JSON.stringify(
                            snapshots[0].coverage,
                            null,
                            2,
                        )}</pre>
                </div>
                <div
                    class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                >
                    <h2 class="text-lg font-semibold">Table</h2>
                    <pre class="text-xs overflow-auto">{JSON.stringify(
                            snapshots[0].table,
                            null,
                            2,
                        )}</pre>
                </div>
            </section>
        {/key}

        <!-- Scrolling history -->
        <section
            class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
        >
            <h2 class="text-lg font-semibold">History (latest first)</h2>
            <div class="mt-3 max-h-[40vh] overflow-y-auto">
                <ul class="text-xs space-y-2">
                    {#each snapshots as s}
                        <li
                            class="rounded-lg border border-slate-200 bg-slate-50 p-2"
                        >
                            <div class="mb-1 text-slate-600">{s.t}</div>
                            <div class="grid gap-2 md:grid-cols-2">
                                <pre class="overflow-auto">{JSON.stringify(
                                        {
                                            pending_exact:
                                                s.vectorizer?.pending_exact,
                                            usage: s.bm25?.usage,
                                        },
                                        null,
                                        2,
                                    )}</pre>
                                <pre class="overflow-auto">{JSON.stringify(
                                        {
                                            embedding_status:
                                                s.coverage?.embedding_status,
                                            noise: s.coverage?.noise,
                                        },
                                        null,
                                        2,
                                    )}</pre>
                            </div>
                            {#if s.queries?.items?.length}
                                <div class="mt-2">
                                    <h3 class="font-semibold">
                                        Recent queries
                                    </h3>
                                    <div class="overflow-auto">
                                        <table class="table table-xs">
                                            <thead
                                                ><tr
                                                    ><th>t</th><th>mode</th><th
                                                        >q</th
                                                    ><th>count</th><th
                                                        >best_score</th
                                                    ><th>elapsed_ms</th></tr
                                                ></thead
                                            >
                                            <tbody>
                                                {#each s.queries.items.slice(0, 10) as q}
                                                    <tr>
                                                        <td>{q.t}</td><td
                                                            >{q.mode}</td
                                                        ><td
                                                            class="truncate max-w-[240px]"
                                                            >{q.q}</td
                                                        ><td>{q.count}</td><td
                                                            >{q.best_score}</td
                                                        ><td>{q.elapsed_ms}</td>
                                                    </tr>
                                                {/each}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            {/if}
                        </li>
                    {/each}
                </ul>
            </div>
        </section>
    {:else}
        <div class="text-slate-600">No snapshots yet.</div>
    {/if}
</main>
