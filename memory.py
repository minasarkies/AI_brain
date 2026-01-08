import chromadb

client = chromadb.Client(
    settings=chromadb.Settings(persist_directory="./chroma_memory")
)
memory = client.get_or_create_collection("personal_brain")

def add_memory(document: str, meta: dict = {}):
    memory.add(documents=[document], metadatas=[meta], ids=[f"mem_{len(memory.get()['ids'])+1}"])

def query_memory(query: str, n_results: int = 5):
    results = memory.query(query_texts=[query], n_results=n_results)
    docs = results.get("documents", [])
    # Chroma returns documents as a nested list: [[...]]
    if docs and isinstance(docs[0], list):
        return docs[0]
    return docs
