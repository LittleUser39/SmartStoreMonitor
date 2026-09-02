from __future__ import annotations

import json
from pathlib import Path

DATA_FILE = Path("data/products.json")


def load_products() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_products(products: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as file:
        json.dump(products, file, ensure_ascii=False, indent=2)


def is_new_product(product_id: str) -> bool:
    return str(product_id) not in load_products()


def add_product(product: dict) -> None:
    products = load_products()
    products[str(product["id"])] = product
    save_products(products)


def remove_products(product_ids: list[str]) -> int:
    """Remove products by ID and return the number of removed entries."""
    if not product_ids:
        return 0

    products = load_products()
    removed_count = 0

    for product_id in product_ids:
        product_id = str(product_id)
        if product_id in products:
            del products[product_id]
            removed_count += 1

    if removed_count:
        save_products(products)

    return removed_count
