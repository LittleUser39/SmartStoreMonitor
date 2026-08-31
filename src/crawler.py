from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

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


def _price(value: object) -> str:
    if value is None:
        return "가격 정보 없음"
    if isinstance(value, (int, float)):
        return f"{int(value):,}원"
    text = _normalize_text(str(value))
    if not text:
        return "가격 정보 없음"
    digits = re.sub(r"[^0-9]", "", text)
    return f"{int(digits):,}원" if digits else text


def _first_image(page: Page) -> str:
    for selector in (
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'img[src]',
        'img[data-src]',
    ):
        locator = page.locator(selector)
        if locator.count():
            for i in range(min(locator.count(), 5)):
                image = locator.nth(i).get_attribute("content") or locator.nth(i).get_attribute("src") or locator.nth(i).get_attribute("data-src")
                image = _absolute_url(image)
                if image and image.startswith("http"):
                    return image
    return ""


def _json_ld_product(page: Page) -> dict:
    scripts = page.locator('script[type="application/ld+json"]').all()
    for script in scripts:
        try:
            raw = script.inner_text()
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Product" or "Product" in (item.get("@type") or []):
                return item
            for graph_item in item.get("@graph", []):
                if isinstance(graph_item, dict) and graph_item.get("@type") == "Product":
                    return graph_item
    return {}


def _enrich_product(page: Page, product: dict) -> dict:
    """Open the product page and extract stable metadata when available."""
    try:
        page.goto(product["url"], wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1_500)

        data = _json_ld_product(page)
        name = _normalize_text(data.get("name"))
        if name:
            product["name"] = name

        offers = data.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            product["price"] = _price(offers.get("price") or offers.get("lowPrice"))

        image = data.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if image:
            product["image"] = _absolute_url(str(image)) or ""

        if product["price"] == "가격 정보 없음":
            for selector in ('meta[property="product:price:amount"]', 'meta[itemprop="price"]'):
                locator = page.locator(selector)
                if locator.count():
                    value = locator.first.get_attribute("content") or locator.first.get_attribute("value")
                    if value:
                        product["price"] = _price(value)
                        break

        if not product["image"]:
            product["image"] = _first_image(page)

        # Product pages sometimes expose the visible title/price even when
        # JSON-LD is absent. These selectors are fallbacks, not the primary
        # extraction mechanism.
        if not product["name"]:
            title = page.locator("h1").first
            if title.count():
                product["name"] = _normalize_text(title.inner_text())

        if product["price"] == "가격 정보 없음":
            body_text = _normalize_text(page.locator("body").inner_text())
            match = re.search(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원", body_text)
            if match:
                product["price"] = _price(match.group(1))

    except Exception as exc:
        product["crawl_error"] = str(exc)

    return product


def crawl_products(
    store_url: str,
    max_products: int = 100,
    keywords: list[str] | None = None,
) -> list[dict]:
    """Collect SmartStore products and enrich keyword candidates.

    The store page is rendered with Playwright. Product URLs are collected
    from real ``/products/<id>`` links. For keyword candidates, the product
    detail page is opened and metadata is extracted primarily from standard
    JSON-LD Product data, with OpenGraph/meta/DOM fallbacks.
    """
    keywords = keywords or []
    found: dict[str, dict] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ko-KR",
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        detail_page = context.new_page()

        try:
            page.goto(store_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4_000)

            # Trigger lazy-loaded product cards.
            for _ in range(5):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(800)

            anchors = page.locator('a[href*="/products/"]').all()
            for anchor in anchors:
                if len(found) >= max_products:
                    break
                try:
                    href = _absolute_url(anchor.get_attribute("href"))
                    if not href or "/products/" not in href:
                        continue

                    name = _normalize_text(anchor.inner_text())
                    if not name:
                        continue

                    pid = _product_id(href)
                    if pid in found:
                        continue

                    # Capture an image from the same card when possible.
                    image = ""
                    card = anchor.locator("xpath=ancestor::*[.//img][1]")
                    if card.count():
                        img = card.locator("img").first
                        image = _absolute_url(img.get_attribute("src") or img.get_attribute("data-src")) or ""

                    found[pid] = {
                        "id": pid,
                        "name": name,
                        "price": "가격 정보 없음",
                        "url": href,
                        "image": image,
                    }
                except Exception:
                    continue

            # Only visit detail pages for likely keyword matches. This keeps
            # a 5-minute GitHub Actions job practical.
            candidates = []
            for product in found.values():
                lowered = product["name"].casefold()
                if not keywords or any(k.casefold() in lowered for k in keywords):
                    candidates.append(product)

            for product in candidates:
                _enrich_product(detail_page, product)

        finally:
            context.close()
            browser.close()

    return list(found.values())
