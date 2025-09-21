import os, inspect, asyncio, json, itertools
from typing import List, Dict, Any

PROMPT = "Say 'Client OK' if you can read this."
HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
MODEL_ID = os.getenv("STRANDS_MODEL", "qwen2.5-coder:3b")

def show_chunk_schema(tag: str, chunk: Any, i: int):
    if i < 3:  # print first few chunks to understand the shape
        t = type(chunk).__name__
        head = chunk if isinstance(chunk, str) else json.dumps(chunk, default=str)[:200]
        print(f"[{tag}] chunk#{i} type={t} head={head}")

def normalise_text(chunk: Any) -> str:
    # Handle common shapes from different SDKs
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        # popular keys
        for k in ("response", "text", "delta", "content"):
            v = chunk.get(k)
            if isinstance(v, str):
                return v
        # nested message
        msg = chunk.get("message")
        if isinstance(msg, dict):
            v = msg.get("content")
            if isinstance(v, str):
                return v
    return ""

async def consume_async(gen) -> str:
    buf: List[str] = []
    for i in itertools.count():
        try:
            chunk = await gen.__anext__()
        except StopAsyncIteration:
            break
        show_chunk_schema("async", chunk, i)
        buf.append(normalise_text(chunk))
    return "".join(buf)

def consume_sync(gen) -> str:
    buf: List[str] = []
    for i, chunk in enumerate(gen):
        show_chunk_schema("sync", chunk, i)
        buf.append(normalise_text(chunk))
    return "".join(buf)

def try_sdk() -> str:
    from strands.models.ollama import OllamaModel
    m = OllamaModel(host=HOST, model_id=MODEL_ID)
    g = m.stream(PROMPT, options={"temperature": 0.1})

    if inspect.isasyncgen(g):
        return asyncio.run(consume_async(g))
    else:
        return consume_sync(g)

def try_rest() -> str:
    import requests
    r = requests.post(
        f"{HOST}/api/generate",
        json={"model": MODEL_ID, "prompt": PROMPT, "stream": False, "options": {"temperature": 0.1}},
        timeout=60,
    )
    r.raise_for_status()
    j = r.json()
    return j.get("response") if isinstance(j, dict) else str(j)

def main():
    print(f"Connecting to Ollama at {HOST} with model {MODEL_ID}\n")

    print("[1/2] SDK wrapper check…")
    try:
        out = try_sdk()
        print("SDK OK:", out)
        return
    except Exception as e:
        print("SDK error:", e)

    print("\n[2/2] REST fallback check…")
    try:
        out = try_rest()
        print("REST OK:", out)
    except Exception as e:
        print("REST error:", e)

if __name__ == "__main__":
    main()
