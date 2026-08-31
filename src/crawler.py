from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

BASE_URL = "https://smartstore.naver.com"
DEBUG_DIR = Path("debug")


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _absolute_url(href: str | None) -> str | None:
    return urljoin(BASE_URL, href) if href else None


def _product_id(url: str) -> str:
    match = re.search(r"/products/(\d+)", url)
    return match.group(1) if match else url


def _price(value: object) -> str:
    if value is None:
        return "가격 정보 없음"
    if isinstance(value, (int, float)):
        return f"{int(value):,}원"
    text = _normalize_text(str(value))
    digits = re.sub(r"[^0-9]", "", text)
    return f"{int(digits):,}원" if digits else (text or "가격 정보 없음")


def _first_image(page: Page) -> str:
    for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]', 'img[src]', 'img[data-src]'):
        locator = page.locator(selector)
        for i in range(min(locator.count(), 5)):
            node = locator.nth(i)
            image = node.get_attribute("content") or node.get_attribute("src") or node.get_attribute("data-src")
            image = _absolute_url(image)
            if image and image.startswith("http"):
                return image
    return ""


def _json_ld_product(page: Page) -> dict:
    for script in page.locator('script[type="application/ld+json"]').all():
        try:
            data = json.loads(script.inner_text())
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
                return item
            for graph_item in item.get("@graph", []):
                if isinstance(graph_item, dict) and graph_item.get("@type") == "Product":
                    return graph_item
    return {}


def _enrich_product(page: Page, product: dict) -> dict:
    try:
        page.goto(product["url"], wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1_500)
        data = _json_ld_product(page)
        if data.get("name"):
            product["name"] = _normalize_text(str(data["name"]))
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


def crawl_products(store_url: str, max_products: int = 100, keywords: list[str] | None = None) -> list[dict]:
    keywords = keywords or []
    found: dict[str, dict] = {}
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ko-KR",
            viewport={"width": 1440, "height": 1000},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        )
        page = context.new_page()
        detail_page = context.new_page()
        response_status = None
        try:
            response = page.goto(store_url, wait_until="domcontentloaded", timeout=60_000)
            response_status = response.status if response else None
            page.wait_for_timeout(4_000)
            for _ in range(5):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(800)

            html = page.content()
            (DEBUG_DIR / "page.html").write_text(html, encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "screenshot.png"), full_page=True)

            anchors = page.locator('a[href*="/products/"]')
            anchor_count = anchors.count()
            print(f"Page title: {_normalize_text(page.title())}")
            print(f"Final URL: {page.url}")
            print(f"HTTP status: {response_status}")
            print(f"HTML size: {len(html):,} bytes")
            print(f"Total <a> tags: {page.locator('a').count()}")
            print(f"Product links (/products/): {anchor_count}")
            print(f"Total <img> tags: {page.locator('img').count()}")
            print(f"Total <script> tags: {page.locator('script').count()}")
            print(f"Body text preview: {_normalize_text(page.locator('body').inner_text())[:500]}")

            for i in range(min(anchor_count, max_products)):
                anchor = anchors.nth(i)
                try:
                    href = _absolute_url(anchor.get_attribute("href"))
                    if not href:
                        continue
                    pid = _product_id(href)
                    if pid in found:
                        continue
                    found[pid] = {
                        "id": pid,
                        "name": _normalize_text(anchor.inner_text()) or f"상품 {pid}",
                        "price": "가격 정보 없음",
                        "url": href,
                        "image": "",
                    }
                except Exception:
                    continue

            candidates = [
                product for product in found.values()
                if not keywords or any(k.casefold() in product["name"].casefold() for k in keywords)
            ]
            for product in candidates:
                _enrich_product(detail_page, product)
        finally:
            context.close()
            browser.close()

    if not found:
        raise RuntimeError("상품을 하나도 찾지 못했습니다. debug/page.html 및 debug/screenshot.png를 확인하세요.")
    return list(found.values())
