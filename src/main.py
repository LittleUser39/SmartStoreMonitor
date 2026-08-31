from __future__ import annotations

import json
from pathlib import Path

from crawler import crawl_products
from database import add_product, is_new_product
from discord_notify import send_discord_notification

CONFIG_FILE = Path("config.json")


def load_config() -> dict:
    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def find_keyword(name: str, keywords: list[str]) -> str | None:
    lowered = name.casefold()
    for keyword in keywords:
        if keyword.casefold() in lowered:
            return keyword
    return None


def main() -> None:
    config = load_config()
    products = crawl_products(
        config["store_url"],
        int(config.get("max_products", 100)),
    )

    print(f"Collected {len(products)} product candidates")

    for product in products:
        keyword = find_keyword(product["name"], config["keywords"])
        if not keyword:
            continue

        product["keyword"] = keyword

        if not is_new_product(product["id"]):
            print(f"[existing] {product['name']}")
            continue

        print(f"[new] {product['name']}")
        add_product(product)
        send_discord_notification(product)


if __name__ == "__main__":
    main()
