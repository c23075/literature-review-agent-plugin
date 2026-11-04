"""research.db: libraries, documents and page-aware chunks. Keyword and vector tables are made
by hand."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

RESEARCH_METADATA = MetaData()

libraries = Table(
    "libraries",
    RESEARCH_METADATA,
    Column("id", Integer, primary_key=True),
    Column("name", String(63), nullable=False, unique=True),
    Column("folder", Text, nullable=False),
    Column("environment", Text, nullable=False),
    Column("embedding_model", Text),  # virtual model used, e.g. cw/litreview-offline:embed
    Column("embedding_dim", Integer),
    Column("created_at", String(32), nullable=False),
)

documents = Table(
    "documents",
    RESEARCH_METADATA,
    Column("id", Integer, primary_key=True),
    Column("library_id", Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),  # relative to the library folder
    Column("sha256", String(64), nullable=False),
    Column("title", Text),
    Column("authors", Text),
    Column("year", Integer),
    Column("pages", Integer),
    Column("status", String(12), nullable=False),  # indexed | no_text | failed | missing
    Column("error", Text),
    Column("chunks", Integer, nullable=False, default=0),
    Column("indexed_at", String(32), nullable=False),
    Index("ix_documents_library_path", "library_id", "path", unique=True),
)

chunks = Table(
    "chunks",
    RESEARCH_METADATA,
    Column("id", Integer, primary_key=True),
    Column("document_id", Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("page_start", Integer, nullable=False),
    Column("page_end", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("tokens", Integer, nullable=False),
    Index("ix_chunks_document_seq", "document_id", "seq"),
)
