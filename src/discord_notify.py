from __future__ import annotations

import os
import time

import requests

MAX_EMBEDS_PER_MESSAGE = 10
MAX_RETRIES = 5
DEFAULT_RETRY_SECONDS = 2.0


def _make_embed(product: dict) -> dict:
    embed = {
        "title": "🔔 HeroTime 미쿠 상품 발견!",
        "description": product["name"],
        "url": product["url"],
        "fields": [
            {"name": "가격", "value": product.get("price", "가격 정보 없음"), "inline": True},
            {"name": "키워드", "value": product.get("keyword", "미쿠"), "inline": True},
        ],
        "footer": {"text": "HeroTime Monitor"},
    }

    if product.get("image"):
        embed["thumbnail"] = {"url": product["image"]}

    return embed


def _post_with_retry(webhook_url: str, embeds: list[dict]) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(
            webhook_url,
            json={"embeds": embeds},
            timeout=15,
        )

        if response.status_code != 429:
            response.raise_for_status()
            return

        retry_after = DEFAULT_RETRY_SECONDS
        try:
            retry_after = float(response.json().get("retry_after", retry_after))
        except (ValueError, TypeError):
            pass

        retry_after = max(retry_after, DEFAULT_RETRY_SECONDS)
        print(
            f"[Discord] Rate limited (429). "
            f"Retrying in {retry_after:.2f}s ({attempt}/{MAX_RETRIES})"
        )
        time.sleep(retry_after)

    response.raise_for_status()


def send_discord_notifications(products: list[dict]) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

    if not products:
        return

    batches = [
        products[i : i + MAX_EMBEDS_PER_MESSAGE]
        for i in range(0, len(products), MAX_EMBEDS_PER_MESSAGE)
    ]

    print(
        f"[Discord] Sending {len(products)} products "
        f"in {len(batches)} message(s)"
    )

    for index, batch in enumerate(batches, start=1):
        embeds = [_make_embed(product) for product in batch]
        _post_with_retry(webhook_url, embeds)
        print(f"[Discord] Batch {index}/{len(batches)} sent ({len(batch)} products)")

        if index < len(batches):
            time.sleep(1.0)


def send_discord_notification(product: dict) -> None:
    """Backward-compatible single-product wrapper."""
    send_discord_notifications([product])
