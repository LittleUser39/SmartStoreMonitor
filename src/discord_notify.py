from __future__ import annotations

import os
import time
from urllib.parse import urljoin

import requests

BASE_URL = "https://herotime.co.kr"
MAX_EMBEDS_PER_MESSAGE = 10
MAX_CHARS_PER_MESSAGE = 5500  # Discord 제한은 메시지당 임베드 합계 6000자, 여유를 둠
MAX_RETRIES = 5
DEFAULT_RETRY_SECONDS = 2.0


def _clean_text(value, fallback: str, limit: int) -> str:
    """None/빈 문자열/숫자 등을 안전한 문자열로 바꾸고 길이를 제한한다.
    Discord는 빈 field value, 빈 description을 400으로 거부한다."""
    text = str(value).strip() if value is not None else ""
    if not text:
        text = fallback
    return text[:limit]


def _abs_url(value) -> str | None:
    """상대경로/프로토콜 생략 URL을 절대 URL로 변환. 이상하면 None."""
    if not value:
        return None
    url = str(value).strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = urljoin(BASE_URL, url)
    return url if url.startswith(("http://", "https://")) else None


def _make_embed(product: dict) -> dict:
    embed = {
        "title": "🔔 HeroTime 미쿠 상품 발견!",
        "description": _clean_text(product.get("name"), "이름 없음", 4000),
        "fields": [
            {
                "name": "가격",
                "value": _clean_text(product.get("price"), "가격 정보 없음", 1000),
                "inline": True,
            },
            {
                "name": "키워드",
                "value": _clean_text(product.get("keyword"), "미쿠", 1000),
                "inline": True,
            },
        ],
        "footer": {"text": "HeroTime Monitor"},
    }

    url = _abs_url(product.get("url"))
    if url:
        embed["url"] = url

    image = _abs_url(product.get("image"))
    if image:
        embed["thumbnail"] = {"url": image}

    return embed


def _embed_size(embed: dict) -> int:
    """Discord가 합산하는 글자 수(title, description, field, footer)."""
    size = len(embed.get("title", "")) + len(embed.get("description", ""))
    for field in embed.get("fields", []):
        size += len(field["name"]) + len(field["value"])
    size += len(embed.get("footer", {}).get("text", ""))
    return size


def _split_batches(products: list[dict]) -> list[list[tuple[dict, dict]]]:
    """개수(10개)와 글자 수(5500자) 두 기준으로 (product, embed) 묶음을 나눈다."""
    batches: list[list[tuple[dict, dict]]] = []
    current: list[tuple[dict, dict]] = []
    current_size = 0

    for product in products:
        embed = _make_embed(product)
        size = _embed_size(embed)
        if current and (
            len(current) >= MAX_EMBEDS_PER_MESSAGE
            or current_size + size > MAX_CHARS_PER_MESSAGE
        ):
            batches.append(current)
            current, current_size = [], 0
        current.append((product, embed))
        current_size += size

    if current:
        batches.append(current)
    return batches


def _post_with_retry(webhook_url: str, embeds: list[dict]) -> None:
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.post(
            webhook_url,
            json={"embeds": embeds},
            timeout=15,
        )

        if response.status_code != 429:
            if not response.ok:
                # Discord는 응답 본문에 문제된 필드를 알려준다 (웹훅 URL은 포함되지 않음)
                print(f"[Discord] HTTP {response.status_code}: {response.text}")
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


def _is_bad_request(exc: requests.HTTPError) -> bool:
    return exc.response is not None and exc.response.status_code == 400


def send_discord_notifications(products: list[dict]) -> list[dict]:
    """상품 목록을 Discord로 전송하고, 실제로 전송에 성공한 상품 목록을 반환한다.

    - 한 묶음이 400으로 실패하면 상품을 1개씩 다시 보내 문제 상품만 건너뛴다.
    - 400 이외의 오류(웹훅 URL 오류 등)는 그대로 예외를 던진다.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

    if not products:
        return []

    batches = _split_batches(products)

    print(
        f"[Discord] Sending {len(products)} products "
        f"in {len(batches)} message(s)"
    )

    sent: list[dict] = []
    skipped: list[dict] = []

    for index, batch in enumerate(batches, start=1):
        embeds = [embed for _, embed in batch]
        try:
            _post_with_retry(webhook_url, embeds)
            sent.extend(product for product, _ in batch)
            print(f"[Discord] Batch {index}/{len(batches)} sent ({len(batch)} products)")
        except requests.HTTPError as exc:
            if not _is_bad_request(exc):
                raise
            print(
                f"[Discord] Batch {index}/{len(batches)} rejected (400). "
                f"Retrying each product individually..."
            )
            for product, embed in batch:
                try:
                    _post_with_retry(webhook_url, [embed])
                    sent.append(product)
                except requests.HTTPError as single_exc:
                    if not _is_bad_request(single_exc):
                        raise
                    skipped.append(product)
                    print(
                        f"[Discord] Skipped bad product: "
                        f"{product.get('name')} | {product.get('url')} | "
                        f"image={product.get('image')!r} | price={product.get('price')!r}"
                    )
                time.sleep(0.5)

        if index < len(batches):
            time.sleep(1.0)

    print(f"[Discord] Done. sent={len(sent)}, skipped={len(skipped)}")
    return sent


def send_discord_notification(product: dict) -> None:
    """Backward-compatible single-product wrapper."""
    send_discord_notifications([product])
