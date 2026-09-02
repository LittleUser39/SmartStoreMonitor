from __future__ import annotations

import json
from pathlib import Path

# from crawler import cleanup_sold_out_products, crawl_products
#DebugTest
from crawler import (
    cleanup_sold_out_products,
    crawl_products,
    debug_compare_sold_out_pages,
)
from database import add_product, is_new_product, load_products, remove_products
from discord_notify import send_discord_notifications
from notion_sender import send_notion_notifications

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
    #DebugTest
    # debug_compare_sold_out_pages()
    # return
    keywords = config["keywords"]

    # Recheck products already saved in products.json first.
    # Only entries whose detail page contains the exact text "SOLD OUT" are removed.
    existing_products = load_products()
    sold_out_ids = cleanup_sold_out_products(existing_products)
    removed_count = remove_products(sold_out_ids)
    print(f"Removed sold-out products from database: {removed_count}")

    max_products = config.get("max_products")
    if max_products is not None:
        max_products = int(max_products)

    products = crawl_products(
        config["store_url"],
        max_products=max_products,
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

    # Both destinations must succeed before product state is persisted.
    send_discord_notifications(new_products)
    send_notion_notifications(new_products)

    # Only persist products after both Discord and Notion notifications succeed.
    for product in new_products:
        add_product(product)

    print(f"Saved {len(new_products)} newly notified products")


if __name__ == "__main__":
    main()
