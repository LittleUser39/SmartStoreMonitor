from __future__ import annotations

import json
from pathlib import Path

from crawler import crawl_products
from database import add_product, is_new_product
from discord_notify import send_discord_notifications

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
    keywords = config["keywords"]

    products = crawl_products(
        config["store_url"],
        int(config.get("max_products", 100)),
        keywords=keywords,
    )

    print(f"Collected {len(products)} product candidates")

    new_products: list[dict] = []

    for product in products:
        keyword = find_keyword(product["name"], keywords)
        if not keyword:
            continue

        product["keyword"] = keyword

        if not is_new_product(product["id"]):
            print(f"[existing] {product['name']}")
            continue

        print(f"[new] {product['name']}")
        new_products.append(product)

    if not new_products:
        print("No new products found")
        return

    print(f"New products to notify: {len(new_products)}")

    # Send in batches. If Discord returns 429, discord_notify.py waits for
    # Discord's retry_after value and retries automatically.
    send_discord_notifications(new_products)

    # Only persist products after their Discord notifications were sent.
    # This prevents a failed notification from permanently marking a product
    # as already notified.
    for product in new_products:
        add_product(product)

    print(f"Saved {len(new_products)} newly notified products")


if __name__ == "__main__":
    main()
