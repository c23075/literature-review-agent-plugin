"""Literature libraries and review workflows, as a plugin for Cairnward (ADR-0017)."""

__version__ = "0.1.0"

from cairnward_research.chunking import Chunk, chunk_pages
from cairnward_research.embedder import Embedder, EmbeddingDenied, GatewayEmbedder
from cairnward_research.library import Hit, IndexReport, Library, LibraryError, Research
from cairnward_research.pdf import PdfError, PdfText, read_pdf

__all__ = [
    "Chunk",
    "Embedder",
    "EmbeddingDenied",
    "GatewayEmbedder",
    "Hit",
    "IndexReport",
    "Library",
    "LibraryError",
    "PdfError",
    "PdfText",
    "Research",
    "chunk_pages",
    "read_pdf",
]
