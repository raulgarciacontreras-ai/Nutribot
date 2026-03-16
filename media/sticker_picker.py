"""
Sticker Picker — selecciona sticker/meme aleatorio según el tono de la respuesta.

Estructura esperada en media/stickers/:
    media/stickers/
    ├── metadata.json          ← (opcional) file_ids de Telegram para stickers reales
    ├── motivacional/
    │   ├── img_01.jpg
    │   └── img_02.png
    ├── gracioso/
    ├── nutricion/
    ├── felicitacion/
    ├── empujoncito/
    └── default/

metadata.json (para stickers de Telegram reales):
{
    "motivacional": ["CAACAgIAAxkBAAI...", "CAACAgIAAxkBAAI..."],
    "gracioso": ["CAACAgIAAxkBAAI..."],
    ...
}
"""
import json
import os
import random
from pathlib import Path
from typing import Optional

from config import MEDIA_PATH

CATEGORIES = ["motivacional", "gracioso", "nutricion", "felicitacion", "empujoncito", "default"]


def _base() -> Path:
    return Path(MEDIA_PATH)


def _files_in(category: str) -> list[Path]:
    """Lista archivos de media válidos en una categoría."""
    cat_dir = _base() / category
    if not cat_dir.is_dir():
        return []
    return [f for f in cat_dir.iterdir() if f.suffix in (".jpg", ".png", ".gif", ".webp")]


def ensure_folders() -> None:
    """Crea las carpetas de categorías si no existen."""
    for cat in CATEGORIES:
        os.makedirs(os.path.join(MEDIA_PATH, cat), exist_ok=True)


def stats() -> dict[str, int]:
    """Retorna cuántos archivos hay por categoría."""
    return {cat: len(_files_in(cat)) for cat in CATEGORIES}


def _load_metadata() -> dict:
    """Carga file_ids de stickers de Telegram si existe metadata.json."""
    meta_path = _base() / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def pick(tone: str) -> dict:
    """
    Retorna el sticker/media a enviar.

    Returns:
        {
            "type": "sticker_id" | "photo" | "none",
            "value": <file_id o path>
        }
    """
    # 1. Intentar file_id de Telegram (mejor experiencia)
    metadata = _load_metadata()
    ids = metadata.get(tone, [])
    if ids:
        return {"type": "sticker_id", "value": random.choice(ids)}

    # 2. Intentar archivo local de la categoría
    cat_dir = _base() / tone
    if cat_dir.is_dir():
        files = [f for f in cat_dir.iterdir() if f.suffix in (".jpg", ".png", ".gif", ".webp")]
        if files:
            return {"type": "photo", "value": str(random.choice(files))}

    # 3. Fallback a 'default'
    default_dir = _base() / "default"
    if default_dir.is_dir():
        files = [f for f in default_dir.iterdir() if f.suffix in (".jpg", ".png", ".gif", ".webp")]
        if files:
            return {"type": "photo", "value": str(random.choice(files))}

    # 4. Fallback a file_ids de cualquier categoría
    all_ids = [fid for ids_list in metadata.values() for fid in ids_list]
    if all_ids:
        return {"type": "sticker_id", "value": random.choice(all_ids)}

    return {"type": "none", "value": None}
