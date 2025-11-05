-- Run this after applying migrations and executing `pgai install`.
-- Adjust embedding provider/model parameters as needed for your environment.
SELECT ai.create_vectorizer(
    'public.document_segments'::regclass,
    name        => 'document_segments_embedding',
    loading     => ai.loading_column('content_markdown'::name),
    chunking    => ai.chunking_none(),
    formatting  => ai.formatting_python_template(
        $$doc=$document_version_id seq=$sequence role=$source_role\n\n$chunk$$
    ),
    embedding   => ai.embedding_openai('text-embedding-3-small', 1536),
    destination => ai.destination_column('embedding'),
    processing  => ai.processing_default(batch_size => 25, concurrency => 4),
    enqueue_existing => true
);
