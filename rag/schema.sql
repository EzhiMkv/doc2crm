-- Схема хранилища: проекция каталога + документы с чанками.
-- Гибридный поиск = вектор (HNSW) + полнотекст (GIN) поверх одних строк.
CREATE EXTENSION IF NOT EXISTS vector;

-- Проекция товарного каталога Битрикса (см. ARCHITECTURE.md «проекция вместо реплики»)
CREATE TABLE IF NOT EXISTS catalog_items (
    product_id  TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    embed_text  TEXT NOT NULL,           -- что векторизуем: название + описание + атрибуты
    price       NUMERIC,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    embedding   vector(384),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('russian', embed_text)) STORED,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS catalog_tsv_idx ON catalog_items USING gin(tsv);
CREATE INDEX IF NOT EXISTS catalog_vec_idx ON catalog_items USING hnsw (embedding vector_cosine_ops);

-- Загруженные документы (рождаются у нас, в Битрикс попадает только результат)
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    source      TEXT NOT NULL,           -- telegram | api
    seller_name TEXT,
    seller_inn  TEXT,
    doc_number  TEXT,
    doc_date    DATE,
    total       NUMERIC,
    file_path   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Чанки документов: единица RAG-поиска
CREATE TABLE IF NOT EXISTS doc_chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(384),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED
);
CREATE INDEX IF NOT EXISTS doc_chunks_tsv_idx ON doc_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS doc_chunks_vec_idx ON doc_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_idx ON doc_chunks(doc_id);
