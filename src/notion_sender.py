from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
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


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _text(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def _get_data_source_schema(token: str, data_source_id: str) -> dict:
    """Read the live Notion Data Source schema before creating pages."""
    response = requests.get(
        f"{NOTION_API_BASE}/data_sources/{data_source_id}",
        headers=_headers(token),
        timeout=20,
    )

    if not response.ok:
        raise RuntimeError(
            f"Notion Data Source schema request failed "
            f"({response.status_code}): {response.text}"
        )

    data = response.json()
    properties = data.get("properties", {})
    if not isinstance(properties, dict):
        raise RuntimeError("Notion Data Source returned an invalid properties schema")

    return properties


def _find_property(schema: dict, name: str, expected_type: str) -> str:
    """Resolve a property by its live schema name and verify its type."""
    prop = schema.get(name)
    if not prop:
        available = ", ".join(schema.keys())
        raise RuntimeError(
            f'Notion property "{name}" was not found. Available properties: {available}'
        )

    actual_type = prop.get("type")
    if actual_type != expected_type:
        raise RuntimeError(
            f'Notion property "{name}" has type "{actual_type}", '
            f'but "{expected_type}" is required.'
        )

    # Property IDs are accepted by the Notion API and avoid ambiguity if a
    # property name is renamed later. Fall back to the name if an ID is absent.
    return prop.get("id") or name


def _make_page(product: dict, schema: dict, data_source_id: str) -> dict:
    title_key = _find_property(schema, "상품명", "title")
    product_id_key = _find_property(schema, "상품 ID", "rich_text")
    price_key = _find_property(schema, "가격", "rich_text")
    product_url_key = _find_property(schema, "상품 URL", "url")
    image_url_key = _find_property(schema, "이미지 URL", "url")
    keyword_key = _find_property(schema, "키워드", "rich_text")
    discovered_key = _find_property(schema, "발견일", "date")

    now = datetime.now(timezone.utc).isoformat()

    properties = {
        title_key: {
            "title": [
                {
                    "text": {
                        "content": _text(product.get("name"), "상품명 없음")[:2000]
                    }
                }
            ]
        },
        product_id_key: {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("id"))[:2000]
                    }
                }
            ]
        },
        price_key: {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("price"), "가격 정보 없음")[:2000]
                    }
                }
            ]
        },
        product_url_key: {
            "url": product.get("url") or None
        },
        image_url_key: {
            "url": product.get("image") or None
        },
        keyword_key: {
            "rich_text": [
                {
                    "text": {
                        "content": _text(product.get("keyword"), "미쿠")[:2000]
                    }
                }
            ]
        },
        discovered_key: {
            "date": {
                "start": now,
                "end": None,
            }
        },
    }

    return {
        "parent": {
            "type": "data_source_id",
            "data_source_id": data_source_id,
        },
        "properties": properties,
    }


def _post_page(token: str, payload: dict) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(token),
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

    token, data_source_id = _get_config()

    # Do not assume the Notion schema. Read the live schema on every run so
    # configuration errors are reported before any product page is created.
    schema = _get_data_source_schema(token, data_source_id)
    print(
        "[Notion] Schema verified: "
        + ", ".join(f"{name}={prop.get('type')}" for name, prop in schema.items())
    )

    print(f"[Notion] Saving {len(products)} products")

    for index, product in enumerate(products, start=1):
        payload = _make_page(product, schema, data_source_id)
        _post_page(token, payload)
        print(
            f"[Notion] Product {index}/{len(products)} saved: "
            f"{product.get('name', 'unknown')}"
        )


def send_notion_notification(product: dict) -> None:
    """Backward-compatible single-product wrapper."""
    send_notion_notifications([product])
