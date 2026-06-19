import chromadb
import subprocess

MODEL = "llama3:8b"

# =============================
# OLLAMA CALL
# =============================
def run_llm(prompt):
    result = subprocess.run(
        ["ollama", "run", MODEL],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE
    )
    return result.stdout.decode("utf-8").strip()


# =============================
# CHROMADB CONNECT
# =============================
client = chromadb.Client()
collection = client.get_or_create_collection("book")


# =============================
# QUERY FUNCTION
# =============================
def query_book(question):
    results = collection.query(
        query_texts=[question],
        n_results=5
    )

    docs = results["documents"][0]
    analyses = [m["analysis"] for m in results["metadatas"][0]]

    context = "\n\n".join(analyses)

    prompt = f"""
Du bist ein Literatur-Liebhaber.

Nutze folgende Analysen eines Romans:

{context}

Beantworte die Frage präzise und verständlich:

Frage: {question}
"""

    return run_llm(prompt)


# =============================
# CHAT LOOP
# =============================
def chat():
    print("📚 Buch-Chat gestartet (exit zum Beenden)\n")

    while True:
        q = input("Du: ")

        if q.lower() == "exit":
            break

        answer = query_book(q)
        print("\n🤖:", answer, "\n")


if __name__ == "__main__":
    chat()
