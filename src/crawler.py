from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE_URL = "https://smartstore.naver.com"


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _absolute_url(href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(BASE_URL, href)


def _product_id(url: str) -> str:
    match = re.search(r"/products/(\d+)", url)
    return match.group(1) if match else url


def crawl_products(store_url: str, max_products: int = 100) -> list[dict]:
    """Collect rendered SmartStore product links.

    SmartStore markup can change, so this collector intentionally avoids
    undocumented APIs and de-duplicates products by product URL/ID.
    """
    found: dict[str, dict] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            locale="ko-KR",
            viewport={"width": 1440, "height": 1000},
        )
        page.goto(store_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)

        for _ in range(3):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1_000)

        for anchor in page.locator("a").all():
            try:
                href = _absolute_url(anchor.get_attribute("href"))
                if not href or "/products/" not in href:
                    continue

                name = _normalize_text(anchor.inner_text())
                if not name:
                    continue

                pid = _product_id(href)
                found[pid] = {
                    "id": pid,
                    "name": name,
                    "price": "가격 정보 없음",
                    "url": href,
                    "image": "",
                }

                if len(found) >= max_products:
                    break
            except Exception:
                continue

        browser.close()

    return list(found.values())
