from __future__ import annotations

import os

import requests


def send_discord_notification(product: dict) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

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

    response = requests.post(webhook_url, json={"embeds": [embed]}, timeout=15)
    response.raise_for_status()
