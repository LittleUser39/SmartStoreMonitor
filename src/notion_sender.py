from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests

NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2025-09-03"
MAX_RETRIES = 5
DEFAULT_RETRY_SECONDS = 2.0


def _get_config() -> tuple[str, str]:
    token = os.environ.get("NOTION_TOKEN")
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID")

    if not token:
        raise RuntimeError("NOTION_TOKEN is not configured")
    if not data_source_id:
        raise RuntimeError("NOTION_DATA_SOURCE_ID is not configured")

    return token, data_source_id


def _text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def _make_page(product: dict) -> dict:
    properties: dict = {
        "상품명": {
            "title": [
                {
                    "text": {
                        "content": _text(product.get("name"), "상품명 없음")[:2000]
                    }
                }
            ]
        },
        "상품 ID": {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("id"))[:2000]
                    }
                }
            ]
        },
        "가격": {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("price"), "가격 정보 없음")[:2000]
                    }
                }
            ]
        },
        "상품 URL": {
            "url": product.get("url") or None
        },
        "이미지 URL": {
            "url": product.get("image") or None
        },
        "키워드": {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("keyword"), "미쿠")[:2000]
                    }
                }
            ]
        },
        "date:발견일:start": datetime.now(timezone.utc).isoformat(),
        "date:발견일:is_datetime": 1,
    }

    return {
        "parent": {
            "type": "data_source_id",
            "data_source_id": os.environ["NOTION_DATA_SOURCE_ID"],
        },
        "properties": properties,
    }


def _post_page(token: str, payload: dict) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(
            NOTION_API_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )

        if response.status_code != 429:
            if not response.ok:
                raise RuntimeError(
                    f"Notion API failed ({response.status_code}): {response.text}"
                )
            return

        retry_after = DEFAULT_RETRY_SECONDS
        try:
            retry_after = float(response.headers.get("Retry-After", retry_after))
        except (TypeError, ValueError):
            pass

        retry_after = max(retry_after, DEFAULT_RETRY_SECONDS)
        print(
            f"[Notion] Rate limited (429). "
            f"Retrying in {retry_after:.2f}s ({attempt}/{MAX_RETRIES})"
        )
        time.sleep(retry_after)

    raise RuntimeError("Notion API rate limit retry count exceeded")


def send_notion_notifications(products: list[dict]) -> None:
    if not products:
        return

    token, _ = _get_config()
    print(f"[Notion] Saving {len(products)} products")

    for index, product in enumerate(products, start=1):
        _post_page(token, _make_page(product))
        print(
            f"[Notion] Product {index}/{len(products)} saved: "
            f"{product.get('name', 'unknown')}"
        )


def send_notion_notification(product: dict) -> None:
    """Backward-compatible single-product wrapper."""
    send_notion_notifications([product])
