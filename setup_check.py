"""
setup_check.py — Verifica que todo esté listo antes de lanzar Nutribot.
Ejecutar con: python setup_check.py
"""

import os
import sys

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


@check("Variables de entorno (.env)")
def check_env():
    from dotenv import load_dotenv
    load_dotenv()
    missing = [v for v in ["TELEGRAM_BOT_TOKEN", "SAMBANOVA_API_KEY"] if not os.getenv(v)]
    if missing:
        return False, f"Faltan en .env: {', '.join(missing)}"
    return True, "TELEGRAM_BOT_TOKEN y SAMBANOVA_API_KEY presentes"


@check("Token de Telegram")
def check_telegram():
    import urllib.request, json
    from dotenv import load_dotenv
    load_dotenv()
    try:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        url   = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        if data.get("ok"):
            bot = data["result"]
            return True, f"Bot: @{bot['username']} — {bot['first_name']}"
        return False, str(data)
    except Exception as e:
        return False, str(e)


@check("API de Sambanova (texto)")
def check_sambanova():
    from dotenv import load_dotenv
    load_dotenv()
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["SAMBANOVA_API_KEY"],
            base_url="https://api.sambanova.ai/v1",
        )
        response = client.chat.completions.create(
            model="Meta-Llama-3.1-8B-Instruct",
            messages=[{"role": "user", "content": "Responde solo: OK"}],
            max_tokens=10,
        )
        text = response.choices[0].message.content.strip()
        return True, f"Respuesta: {text[:50]}"
    except Exception as e:
        return False, str(e)


@check("API de Sambanova (vision)")
def check_sambanova_vision():
    from dotenv import load_dotenv
    load_dotenv()
    try:
        import base64, struct, zlib
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["SAMBANOVA_API_KEY"],
            base_url="https://api.sambanova.ai/v1",
        )
        vision_model = os.getenv("SAMBANOVA_VISION_MODEL", "Llama-4-Maverick-17B-128E-Instruct")
        # PNG rojo 2x2
        raw = b'\x00\xff\x00\x00\xff\x00\x00' * 2
        compressed = zlib.compress(raw)
        def chunk(ct, d):
            c = ct + d
            return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n' +
               chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0)) +
               chunk(b'IDAT', compressed) +
               chunk(b'IEND', b''))
        b64 = base64.b64encode(png).decode()
        resp = client.chat.completions.create(
            model=vision_model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "Que color ves? Una palabra."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            max_tokens=10,
        )
        text = resp.choices[0].message.content.strip()
        return True, f"Vision ({vision_model}): {text[:50]}"
    except Exception as e:
        return False, str(e)


@check("Embeddings (Gemini text-embedding-004)")
def check_embeddings():
    try:
        from llm.llm_client import embed
        emb = embed(["prueba"])
        return True, f"Gemini embeddings OK, dimensiones: {len(emb[0])}"
    except Exception as e:
        return False, str(e)


@check("ChromaDB local")
def check_chroma():
    try:
        import chromadb
        from chromadb.config import Settings
        os.makedirs("./data/chroma_test", exist_ok=True)
        client = chromadb.PersistentClient(
            path="./data/chroma_test",
            settings=Settings(anonymized_telemetry=False),
        )
        col = client.get_or_create_collection("test_col")
        col.add(documents=["prueba"], ids=["t1"])
        client.delete_collection("test_col")
        return True, "ChromaDB funciona correctamente"
    except Exception as e:
        return False, str(e)


@check("Guia nutricional indexada")
def check_rag():
    from dotenv import load_dotenv
    load_dotenv()
    from rag.vector_store import is_populated, get_count
    if not is_populated():
        return False, "ChromaDB vacio. Ejecuta: python scripts/ingest_guide.py"
    return True, f"{get_count()} chunks indexados en ChromaDB"


@check("Carpetas de stickers")
def check_media():
    from dotenv import load_dotenv
    load_dotenv()
    from media.sticker_picker import ensure_folders, stats
    ensure_folders()
    s     = stats()
    total = sum(s.values())
    if total == 0:
        return True, "Carpetas creadas pero vacias — agrega stickers/memes para que funcionen"
    return True, f"{total} archivos de media en {len([v for v in s.values() if v])} categorias"


# ── Runner ────────────────────────────────────────────────────────────────────
def main():
    print("\nVerificacion de Nutribot")
    print("-" * 50)
    passed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"Error inesperado: {e}"
        icon = "[OK]" if ok else "[FAIL]"
        print(f"{icon}  {name}")
        print(f"    {detail}\n")
        if ok:
            passed += 1

    print("-" * 50)
    print(f"Resultado: {passed}/{len(CHECKS)} verificaciones pasadas\n")
    if passed == len(CHECKS):
        print("Todo listo! Ejecuta:  python main.py")
    else:
        print("Corrige los errores marcados con [FAIL] antes de continuar.")
        sys.exit(1)


if __name__ == "__main__":
    main()
