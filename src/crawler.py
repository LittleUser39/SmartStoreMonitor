from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE_URL = "https://herotime.co.kr"
PRODUCT_URL_RE = re.compile(r"^https?://(?:www\.)?herotime\.co\.kr/product/.+?/\d+/")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text: str) -> str:
    match = re.search(r"(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원", text or "")
    if not match:
        return "가격 정보 없음"
    return f"{int(match.group(1).replace(',', '')):,}원"


def find_product_container(link):
    # Cafe24 product lists normally wrap each product in li.xans-record or a similar li.
    for selector in ("xpath=ancestor::li[1]", "xpath=ancestor::*[contains(@class,'prdList__item')][1]"):
        container = link.locator(selector).first
        if container.count():
            return container
    return link.locator("xpath=ancestor::div[1]").first


def crawl_products(search_url: str, max_products: int = 100, keywords: list[str] | None = None) -> list[dict]:
    keywords = [k.casefold() for k in (keywords or [])]
    products: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ko-KR",
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            response = page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)

            print(f"HTTP status: {response.status if response else 'unknown'}")
            print(f"Page title: {normalize_text(page.title())}")
            print(f"Final URL: {page.url}")

            # Search results are regular Cafe24 product links. Filter out header/footer links
            # by requiring the numeric product-id URL form.
            links = page.locator('a[href*="/product/"]')
            print(f"Candidate /product/ links: {links.count()}")

            for i in range(min(links.count(), max_products * 3)):
                link = links.nth(i)
                href = link.get_attribute("href")
                if not href:
                    continue
                url = urljoin(BASE_URL, href)
                if not PRODUCT_URL_RE.match(url):
                    continue

                container = find_product_container(link)
                text = normalize_text(container.inner_text())
                name = ""

                # Prefer the explicit Cafe24 product-name anchor/class when present.
                for selector in (
                    ".name a",
                    ".name",
                    '[class*="name"] a',
                    '[class*="name"]',
                ):
                    node = container.locator(selector).first
                    if node.count():
                        candidate = normalize_text(node.inner_text())
                        if candidate:
                            name = candidate
                            break

                if not name:
                    name = normalize_text(link.inner_text())
                if not name:
                    continue

                if keywords and not any(k in name.casefold() for k in keywords):
                    continue

                # Extract the sale price from the product card text.
                price = parse_price(text)

                image = ""
                img = container.locator("img").first
                if img.count():
                    image = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    image = urljoin(BASE_URL, image)

                # Numeric ID at the end of Cafe24 product URL is a stable identifier.
                product_id_match = re.search(r"/(\d+)/?(?:[?#].*)?$", url)
                product_id = product_id_match.group(1) if product_id_match else url

                products[product_id] = {
                    "id": product_id,
                    "name": name,
                    "price": price,
                    "url": url,
                    "image": image,
                }

                if len(products) >= max_products:
                    break

            print(f"Collected {len(products)} HeroTime products")
            return list(products.values())
        finally:
            context.close()
            browser.close()
