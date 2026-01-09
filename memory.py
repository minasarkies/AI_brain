import uuid
import chromadb

client = chromadb.Client(
    settings=chromadb.Settings(persist_directory="./chroma_memory")
)

memory = client.get_or_create_collection("personal_brain")


def add_memory(document: str, meta: dict) -> None:
    """
    Store a document with metadata.
    IMPORTANT: meta must include 'namespace' for isolation.
    """
    mem_id = f"mem_{uuid.uuid4().hex}"
    memory.add(documents=[document], metadatas=[meta], ids=[mem_id])


def query_memory(query: str, namespace: str, n_results: int = 5) -> list[str]:
    """
    Query memory restricted to a namespace.
    Returns a flat list[str].
    """
    results = memory.query(
        query_texts=[query],
        n_results=n_results,
        where={"namespace": namespace},
    )

    docs = results.get("documents", [])
    # Chroma commonly returns nested list: [[...]]
    if docs and isinstance(docs[0], list):
        return [d for d in docs[0] if isinstance(d, str)]
    return [d for d in docs if isinstance(d, str)]
