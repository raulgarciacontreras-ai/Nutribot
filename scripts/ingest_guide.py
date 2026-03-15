"""
Indexa TODOS los archivos de conocimiento en data/ dentro de ChromaDB.
Ejecutar cada vez que se agregue o modifique un archivo:
    python scripts/ingest_guide.py

Soporta: .txt, .md, .pdf
Escanea automáticamente todos los archivos válidos en data/
"""
import os
import sys
from pathlib import Path

# Agregar raíz del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP
from rag.vector_store import ingest_chunks

DATA_DIR = Path("./data")
VALID_EXTENSIONS = {".txt", ".md", ".pdf"}


def read_file(path: str) -> str:
    """Lee un archivo. Soporta txt/md y PDF."""
    if path.endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            print(f"  Para PDFs instala PyMuPDF: pip install PyMuPDF")
            return ""
    else:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Divide el texto en chunks con overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def discover_files() -> list[Path]:
    """Encuentra todos los archivos indexables en data/."""
    if not DATA_DIR.exists():
        return []
    files = [
        f for f in DATA_DIR.iterdir()
        if f.is_file() and f.suffix in VALID_EXTENSIONS
    ]
    return sorted(files)


def main():
    files = discover_files()
    if not files:
        print(f"No se encontraron archivos (.txt, .md, .pdf) en {DATA_DIR}/")
        print("Coloca tus documentos de conocimiento ahí y vuelve a ejecutar.")
        sys.exit(1)

    print(f"\nArchivos encontrados en {DATA_DIR}/:")
    for f in files:
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")

    all_chunks = []
    all_metadatas = []

    for filepath in files:
        print(f"\nProcesando: {filepath.name}")
        text = read_file(str(filepath))
        if not text:
            print(f"  (vacío o error al leer, saltando)")
            continue

        print(f"  Texto extraído: {len(text):,} caracteres")
        chunks = chunk_text(text, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP)
        print(f"  Chunks generados: {len(chunks)}")

        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metadatas.append({
                "source": filepath.name,
                "chunk_idx": i,
            })

    if not all_chunks:
        print("\nNo se generaron chunks. Verifica que los archivos tengan contenido.")
        sys.exit(1)

    print(f"\nTotal: {len(all_chunks)} chunks de {len(files)} archivos")
    print("Indexando en ChromaDB...")

    count = ingest_chunks(chunks=all_chunks, metadatas=all_metadatas)
    print(f"\nIndexación completa: {count} documentos en ChromaDB")


if __name__ == "__main__":
    main()
