<script lang="ts">
    import { marked } from "marked";
    import type { PageData } from "./$types";
    import type {
        ChatConfig,
        ChatMessage,
        ConversationSummary,
        RetrievedContext,
        SSEEvent,
    } from "$lib/types";

    const props = $props<{ data: PageData & { backendToken?: string } }>();
    const data = $state(props.data);
    const API_BASE = $derived(data.apiBase);

    // Helper to get auth headers
    function getAuthHeaders(): HeadersInit {
        const headers: HeadersInit = { "Content-Type": "application/json" };
        // @ts-ignore - backendToken comes from layout
        if (data.backendToken) {
            // @ts-ignore
            headers["Authorization"] = `Bearer ${data.backendToken}`;
        }
        return headers;
    }

    // Conversation state
    let conversations = $state<ConversationSummary[]>([]);
    let selectedConversationId = $state<string | null>(null);
    let messages = $state<ChatMessage[]>([]);
    let isLoadingConversations = $state(false);
    let isLoadingMessages = $state(false);

    // Input state
    let inputMessage = $state("");
    let isGenerating = $state(false);
    let streamingContent = $state("");
    let lastContext = $state<RetrievedContext[]>([]);
    let showContext = $state(false);

    // New conversation dialog
    let showNewDialog = $state(false);
    let newTitle = $state("");

    // Settings panel
    let showSettings = $state(false);
    let config = $state<ChatConfig>({
        model: "gpt-4o",
        temperature: 0.7,
        max_tokens: 4096,
        context_limit: 10,
        max_context_chars: 50000,
        w_bm25: 0.5,
        w_vec: 0.5,
        include_conversation_history: 10,
    });

    // Error state
    let errorMsg = $state("");

    // Formatters
    const dateFormatter = new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });

    function formatDate(value?: string | null) {
        if (!value) return "";
        return dateFormatter.format(new Date(value));
    }

    // Markdown rendering
    marked.setOptions({ breaks: true, gfm: true });
    const markdownCache = new Map<string, string>();

    function renderMarkdown(text: string): string {
        const cached = markdownCache.get(text);
        if (cached) return cached;
        const html = marked.parse(text) as string;
        markdownCache.set(text, html);
        return html;
    }

    // Load conversations on mount
    $effect(() => {
        loadConversations();
    });

    // Load messages when conversation changes
    $effect(() => {
        if (selectedConversationId) {
            loadMessages(selectedConversationId);
            loadConfig(selectedConversationId);
        } else {
            messages = [];
            lastContext = [];
        }
    });

    async function loadConversations() {
        isLoadingConversations = true;
        errorMsg = "";
        try {
            const res = await fetch(
                `${API_BASE}/chat/conversations?limit=100`,
                {
                    headers: getAuthHeaders(),
                },
            );
            if (!res.ok)
                throw new Error(`Failed to load conversations: ${res.status}`);
            conversations = await res.json();
        } catch (e) {
            errorMsg =
                e instanceof Error ? e.message : "Failed to load conversations";
        } finally {
            isLoadingConversations = false;
        }
    }

    async function loadMessages(conversationId: string) {
        isLoadingMessages = true;
        errorMsg = "";
        try {
            const res = await fetch(
                `${API_BASE}/chat/conversations/${conversationId}/messages`,
                { headers: getAuthHeaders() },
            );
            if (!res.ok)
                throw new Error(`Failed to load messages: ${res.status}`);
            messages = await res.json();
            lastContext = [];
            // Scroll to bottom after messages load
            setTimeout(scrollToBottom, 100);
        } catch (e) {
            errorMsg =
                e instanceof Error ? e.message : "Failed to load messages";
        } finally {
            isLoadingMessages = false;
        }
    }

    async function loadConfig(conversationId: string) {
        try {
            const res = await fetch(
                `${API_BASE}/chat/conversations/${conversationId}/config`,
                { headers: getAuthHeaders() },
            );
            if (res.ok) {
                config = await res.json();
            }
        } catch {
            // Use defaults if config fails to load
        }
    }

    async function createConversation() {
        if (!newTitle.trim()) return;
        errorMsg = "";
        try {
            const res = await fetch(`${API_BASE}/chat/conversations`, {
                method: "POST",
                headers: getAuthHeaders(),
                body: JSON.stringify({ title: newTitle.trim(), config }),
            });
            if (!res.ok)
                throw new Error(`Failed to create conversation: ${res.status}`);
            const data = await res.json();
            await loadConversations();
            selectedConversationId = data.id;
            newTitle = "";
            showNewDialog = false;
        } catch (e) {
            errorMsg =
                e instanceof Error
                    ? e.message
                    : "Failed to create conversation";
        }
    }

    async function deleteConversation(id: string) {
        if (!confirm("Delete this conversation?")) return;
        try {
            const res = await fetch(`${API_BASE}/chat/conversations/${id}`, {
                method: "DELETE",
                headers: getAuthHeaders(),
            });
            if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
            if (selectedConversationId === id) {
                selectedConversationId = null;
            }
            await loadConversations();
        } catch (e) {
            errorMsg =
                e instanceof Error
                    ? e.message
                    : "Failed to delete conversation";
        }
    }

    async function updateConfig() {
        if (!selectedConversationId) return;
        try {
            const res = await fetch(
                `${API_BASE}/chat/conversations/${selectedConversationId}`,
                {
                    method: "PATCH",
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ config }),
                },
            );
            if (!res.ok)
                throw new Error(`Failed to update config: ${res.status}`);
            showSettings = false;
        } catch (e) {
            errorMsg =
                e instanceof Error ? e.message : "Failed to update settings";
        }
    }

    async function sendMessage() {
        if (!inputMessage.trim() || !selectedConversationId || isGenerating)
            return;

        const userMessage = inputMessage.trim();
        inputMessage = "";
        isGenerating = true;
        streamingContent = "";
        lastContext = [];
        errorMsg = "";

        // Optimistically add user message
        messages = [
            ...messages,
            {
                role: "user",
                content: userMessage,
                segment_id: null,
                created_at: new Date().toISOString(),
            },
        ];
        setTimeout(scrollToBottom, 50);

        try {
            const res = await fetch(
                `${API_BASE}/chat/conversations/${selectedConversationId}/messages/stream`,
                {
                    method: "POST",
                    headers: getAuthHeaders(),
                    body: JSON.stringify({ content: userMessage }),
                },
            );

            if (!res.ok)
                throw new Error(`Failed to send message: ${res.status}`);
            if (!res.body) throw new Error("No response body");

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const jsonStr = line.slice(6);
                        try {
                            const event: SSEEvent = JSON.parse(jsonStr);
                            handleSSEEvent(event);
                        } catch {
                            // Ignore parse errors
                        }
                    }
                }
            }

            // Finalize - add the complete assistant message
            if (streamingContent) {
                messages = [
                    ...messages,
                    {
                        role: "assistant",
                        content: streamingContent,
                        segment_id: null,
                        created_at: new Date().toISOString(),
                    },
                ];
                streamingContent = "";
            }
        } catch (e) {
            errorMsg =
                e instanceof Error ? e.message : "Failed to send message";
            // Remove the optimistic user message on error
            messages = messages.slice(0, -1);
        } finally {
            isGenerating = false;
            setTimeout(scrollToBottom, 50);
        }
    }

    function handleSSEEvent(event: SSEEvent) {
        switch (event.type) {
            case "content":
                streamingContent += event.content;
                scrollToBottom();
                break;
            case "context":
                lastContext = event.context;
                break;
            case "done":
                // Update the last message with the segment_id
                break;
            case "error":
                errorMsg = event.error;
                break;
        }
    }

    function scrollToBottom() {
        const container = document.getElementById("messages-container");
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function sourceAccentClass(source: string): string {
        switch (source) {
            case "chatgpt":
                return "border-l-emerald-500";
            case "claude":
                return "border-l-orange-500";
            case "2brain":
                return "border-l-blue-500";
            default:
                return "border-l-slate-400";
        }
    }

    const selectedConversation = $derived(
        conversations.find((c) => c.id === selectedConversationId),
    );
</script>

<div class="flex h-screen bg-slate-50">
    <!-- Sidebar: Conversation List -->
    <aside class="flex w-80 flex-col border-r border-slate-200 bg-white">
        <div
            class="flex items-center justify-between border-b border-slate-200 p-4"
        >
            <h1 class="text-xl font-semibold text-slate-900">Chat</h1>
            <button
                class="btn btn-primary btn-sm"
                onclick={() => (showNewDialog = true)}
            >
                + New
            </button>
        </div>

        <div class="flex-1 overflow-y-auto">
            {#if isLoadingConversations}
                <div class="p-4 text-center text-sm text-slate-500">
                    Loading...
                </div>
            {:else if conversations.length === 0}
                <div class="p-4 text-center text-sm text-slate-500">
                    No conversations yet. Create one to get started.
                </div>
            {:else}
                <ul class="divide-y divide-slate-100">
                    {#each conversations as conv (conv.id)}
                        <li>
                            <div
                                class="group flex w-full cursor-pointer items-start gap-3 p-4 text-left transition-colors hover:bg-slate-50 {selectedConversationId ===
                                conv.id
                                    ? 'bg-blue-50'
                                    : ''}"
                                role="button"
                                tabindex="0"
                                onclick={() =>
                                    (selectedConversationId = conv.id)}
                                onkeydown={(e) =>
                                    e.key === "Enter" &&
                                    (selectedConversationId = conv.id)}
                            >
                                <div class="flex-1 min-w-0">
                                    <p
                                        class="truncate font-medium {selectedConversationId ===
                                        conv.id
                                            ? 'text-blue-900'
                                            : 'text-slate-900'}"
                                    >
                                        {conv.title}
                                    </p>
                                    <p class="text-xs text-slate-500">
                                        {conv.message_count} messages · {formatDate(
                                            conv.updated_at,
                                        )}
                                    </p>
                                </div>
                                <button
                                    class="opacity-0 group-hover:opacity-100 btn btn-ghost btn-xs text-slate-400 hover:text-red-500"
                                    onclick={(e) => {
                                        e.stopPropagation();
                                        deleteConversation(conv.id);
                                    }}
                                    title="Delete conversation"
                                >
                                    ✕
                                </button>
                            </div>
                        </li>
                    {/each}
                </ul>
            {/if}
        </div>

        <!-- Navigation links -->
        <div class="border-t border-slate-200 p-3 space-y-1">
            <a href="/" class="btn btn-ghost btn-sm w-full justify-start">
                ← Documents
            </a>
            <a href="/search" class="btn btn-ghost btn-sm w-full justify-start">
                🔍 Search
            </a>
        </div>
    </aside>

    <!-- Main Chat Area -->
    <main class="flex flex-1 flex-col">
        {#if !selectedConversationId}
            <!-- No conversation selected -->
            <div class="flex flex-1 items-center justify-center">
                <div class="text-center">
                    <h2 class="text-2xl font-semibold text-slate-700">
                        Welcome to 2brain Chat
                    </h2>
                    <p class="mt-2 text-slate-500">
                        Select a conversation or create a new one to get
                        started.
                    </p>
                    <button
                        class="btn btn-primary mt-4"
                        onclick={() => (showNewDialog = true)}
                    >
                        + New Conversation
                    </button>
                </div>
            </div>
        {:else}
            <!-- Header -->
            <header
                class="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4"
            >
                <div>
                    <h2 class="text-lg font-semibold text-slate-900">
                        {selectedConversation?.title ?? "Conversation"}
                    </h2>
                    <p class="text-xs text-slate-500">
                        Model: {config.model} · Context: {config.context_limit} segments
                    </p>
                </div>
                <div class="flex gap-2">
                    {#if lastContext.length > 0}
                        <button
                            class="btn btn-outline btn-sm"
                            onclick={() => (showContext = !showContext)}
                        >
                            📎 Sources ({lastContext.length})
                        </button>
                    {/if}
                    <button
                        class="btn btn-ghost btn-sm"
                        onclick={() => (showSettings = !showSettings)}
                        title="Settings"
                    >
                        ⚙️
                    </button>
                </div>
            </header>

            <!-- Error message -->
            {#if errorMsg}
                <div class="mx-6 mt-4 alert alert-error">
                    <span>{errorMsg}</span>
                    <button
                        class="btn btn-ghost btn-xs"
                        onclick={() => (errorMsg = "")}>✕</button
                    >
                </div>
            {/if}

            <!-- Settings Panel (collapsible) -->
            {#if showSettings}
                <div class="border-b border-slate-200 bg-slate-50 p-4">
                    <div
                        class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5"
                    >
                        <label class="form-control">
                            <span class="label-text text-xs">Model</span>
                            <select
                                class="select select-bordered select-sm"
                                bind:value={config.model}
                            >
                                <option value="gpt-4o">GPT-4o</option>
                                <option value="gpt-4o-mini">GPT-4o Mini</option>
                                <option value="gpt-4-turbo">GPT-4 Turbo</option>
                                <option value="gpt-3.5-turbo"
                                    >GPT-3.5 Turbo</option
                                >
                            </select>
                        </label>
                        <label class="form-control">
                            <span class="label-text text-xs"
                                >Temperature ({config.temperature})</span
                            >
                            <input
                                type="range"
                                class="range range-sm"
                                min="0"
                                max="2"
                                step="0.1"
                                bind:value={config.temperature}
                            />
                        </label>
                        <label class="form-control">
                            <span class="label-text text-xs"
                                >Context Segments ({config.context_limit})</span
                            >
                            <input
                                type="range"
                                class="range range-sm"
                                min="0"
                                max="50"
                                step="1"
                                bind:value={config.context_limit}
                            />
                        </label>
                        <label class="form-control">
                            <span class="label-text text-xs"
                                >Max Context ({Math.round(
                                    config.max_context_chars / 1000,
                                )}k chars)</span
                            >
                            <input
                                type="range"
                                class="range range-sm"
                                min="5000"
                                max="100000"
                                step="5000"
                                bind:value={config.max_context_chars}
                            />
                        </label>
                        <label class="form-control">
                            <span class="label-text text-xs"
                                >BM25 Weight ({config.w_bm25.toFixed(1)})</span
                            >
                            <input
                                type="range"
                                class="range range-sm"
                                min="0"
                                max="1"
                                step="0.1"
                                bind:value={config.w_bm25}
                            />
                        </label>
                    </div>
                    <p class="mt-2 text-xs text-slate-500">
                        Retrieves up to {config.context_limit} segments, limited to
                        ~{Math.round(config.max_context_chars / 4)}k tokens of
                        context.
                    </p>
                    <div class="mt-3 flex justify-end gap-2">
                        <button
                            class="btn btn-ghost btn-sm"
                            onclick={() => (showSettings = false)}
                        >
                            Cancel
                        </button>
                        <button
                            class="btn btn-primary btn-sm"
                            onclick={updateConfig}
                        >
                            Save Settings
                        </button>
                    </div>
                </div>
            {/if}

            <!-- Context Panel (collapsible) -->
            {#if showContext && lastContext.length > 0}
                <div
                    class="border-b border-slate-200 bg-amber-50 p-4 max-h-64 overflow-y-auto"
                >
                    <h3 class="text-sm font-semibold text-amber-900 mb-2">
                        Sources used for last response:
                    </h3>
                    <div class="space-y-2">
                        {#each lastContext as ctx, i (ctx.segment_id)}
                            <div
                                class="rounded border border-amber-200 bg-white p-3 {sourceAccentClass(
                                    ctx.source_system,
                                )} border-l-4"
                            >
                                <div
                                    class="flex items-start justify-between gap-2"
                                >
                                    <div class="text-xs">
                                        <span class="font-medium text-slate-900"
                                            >{ctx.document_title}</span
                                        >
                                        <span class="text-slate-500">
                                            · {ctx.source_system} · {ctx.source_role}</span
                                        >
                                    </div>
                                    <span class="badge badge-sm">#{i + 1}</span>
                                </div>
                                <p
                                    class="mt-1 text-sm text-slate-700 line-clamp-3"
                                >
                                    {ctx.content}
                                </p>
                                <a
                                    href="/?document={ctx.document_id}&segment={ctx.segment_id}"
                                    class="text-xs text-blue-600 hover:underline"
                                    target="_blank"
                                >
                                    View in context →
                                </a>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            <!-- Messages -->
            <div
                id="messages-container"
                class="flex-1 overflow-y-auto p-6 space-y-4"
            >
                {#if isLoadingMessages}
                    <div class="text-center text-slate-500">
                        Loading messages...
                    </div>
                {:else if messages.length === 0}
                    <div class="text-center text-slate-500">
                        <p>No messages yet. Start the conversation!</p>
                        <p class="text-xs mt-2">
                            Your message will be augmented with relevant context
                            from your knowledge base.
                        </p>
                    </div>
                {:else}
                    {#each messages as msg, i (i)}
                        <div
                            class="flex {msg.role === 'user'
                                ? 'justify-end'
                                : 'justify-start'}"
                        >
                            <div
                                class="max-w-[80%] rounded-lg p-4 {msg.role ===
                                'user'
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-white border border-slate-200 text-slate-900'}"
                            >
                                <div
                                    class="markdown prose prose-sm {msg.role ===
                                    'user'
                                        ? 'prose-invert'
                                        : ''}"
                                >
                                    {@html renderMarkdown(msg.content)}
                                </div>
                                {#if msg.created_at}
                                    <p
                                        class="mt-2 text-xs {msg.role === 'user'
                                            ? 'text-blue-200'
                                            : 'text-slate-400'}"
                                    >
                                        {formatDate(msg.created_at)}
                                    </p>
                                {/if}
                            </div>
                        </div>
                    {/each}

                    <!-- Streaming response -->
                    {#if isGenerating && streamingContent}
                        <div class="flex justify-start">
                            <div
                                class="max-w-[80%] rounded-lg border border-slate-200 bg-white p-4 text-slate-900"
                            >
                                <div class="markdown prose prose-sm">
                                    {@html renderMarkdown(streamingContent)}
                                </div>
                                <p
                                    class="mt-2 text-xs text-slate-400 animate-pulse"
                                >
                                    Generating...
                                </p>
                            </div>
                        </div>
                    {:else if isGenerating}
                        <div class="flex justify-start">
                            <div
                                class="rounded-lg border border-slate-200 bg-white p-4"
                            >
                                <span class="loading loading-dots loading-sm"
                                ></span>
                            </div>
                        </div>
                    {/if}
                {/if}
            </div>

            <!-- Input Area -->
            <div class="border-t border-slate-200 bg-white p-4">
                <div class="flex gap-3">
                    <textarea
                        class="textarea textarea-bordered flex-1 resize-none"
                        placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
                        rows="2"
                        bind:value={inputMessage}
                        onkeydown={handleKeydown}
                        disabled={isGenerating}
                    ></textarea>
                    <button
                        class="btn btn-primary self-end"
                        onclick={sendMessage}
                        disabled={isGenerating || !inputMessage.trim()}
                    >
                        {#if isGenerating}
                            <span class="loading loading-spinner loading-sm"
                            ></span>
                        {:else}
                            Send
                        {/if}
                    </button>
                </div>
                {#if config.context_limit > 0}
                    <p class="mt-2 text-xs text-slate-500">
                        RAG enabled: Up to {config.context_limit} relevant segments
                        will be retrieved from your knowledge base.
                    </p>
                {:else}
                    <p class="mt-2 text-xs text-amber-600">
                        RAG disabled: Set context segments > 0 in settings to
                        enable retrieval.
                    </p>
                {/if}
            </div>
        {/if}
    </main>
</div>

<!-- New Conversation Dialog -->
{#if showNewDialog}
    <div class="modal modal-open">
        <div class="modal-box">
            <h3 class="text-lg font-bold">New Conversation</h3>
            <div class="py-4">
                <input
                    type="text"
                    class="input input-bordered w-full"
                    placeholder="Conversation title..."
                    bind:value={newTitle}
                    onkeydown={(e) => e.key === "Enter" && createConversation()}
                />
            </div>
            <div class="modal-action">
                <button
                    class="btn btn-ghost"
                    onclick={() => (showNewDialog = false)}
                >
                    Cancel
                </button>
                <button
                    class="btn btn-primary"
                    onclick={createConversation}
                    disabled={!newTitle.trim()}
                >
                    Create
                </button>
            </div>
        </div>
        <div
            class="modal-backdrop"
            onclick={() => (showNewDialog = false)}
        ></div>
    </div>
{/if}

<style>
    .markdown :global(pre) {
        background-color: #1e293b;
        color: #e2e8f0;
        padding: 1rem;
        border-radius: 0.5rem;
        overflow-x: auto;
    }

    .markdown :global(code) {
        font-size: 0.875rem;
    }

    .markdown :global(p) {
        margin-bottom: 0.5rem;
    }

    .markdown :global(p:last-child) {
        margin-bottom: 0;
    }

    .markdown :global(ul),
    .markdown :global(ol) {
        margin-left: 1.5rem;
        margin-bottom: 0.5rem;
    }

    .line-clamp-3 {
        display: -webkit-box;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
</style>
