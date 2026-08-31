from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import sync_playwright

BASE_URL = "https://herotime.co.kr"
PRODUCT_URL_RE = re.compile(r"^https?://(?:www\.)?herotime\.co\.kr/product/[^?#]+/(\d+)(?:/|$)", re.I)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text: str) -> str:
    matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원", text or "")
    if not matches:
        return "가격 정보 없음"
    return f"{int(matches[0].replace(',', '')):,}원"


def product_id_from_url(url: str) -> str | None:
    match = PRODUCT_URL_RE.match(url)
    return match.group(1) if match else None


def find_product_container(link):
    selectors = (
        "xpath=ancestor::li[contains(@class,'xans-record')][1]",
        "xpath=ancestor::li[contains(@class,'prdList__item')][1]",
        "xpath=ancestor::li[1]",
        "xpath=ancestor::div[contains(@class,'prdList__item')][1]",
        "xpath=ancestor::div[contains(@class,'description')][1]",
    )
    for selector in selectors:
        container = link.locator(selector).first
        if container.count():
            return container
    return link.locator("xpath=ancestor::div[1]").first


def first_text(container, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            nodes = container.locator(selector)
            for i in range(min(nodes.count(), 3)):
                value = normalize_text(nodes.nth(i).inner_text())
                if value:
                    return value
        except Exception:
            continue
    return ""


def first_image(container) -> str:
    for selector in ("img[src]", "img[data-src]", "img[data-original]"):
        try:
            nodes = container.locator(selector)
            for i in range(min(nodes.count(), 3)):
                img = nodes.nth(i)
                src = (
                    img.get_attribute("data-src")
                    or img.get_attribute("data-original")
                    or img.get_attribute("src")
                    or ""
                )
                if src and not src.startswith("data:"):
                    return urljoin(BASE_URL, src)
        except Exception:
            continue
    return ""


def extract_product(link) -> dict | None:
    href = link.get_attribute("href")
    if not href:
        return None

    url = urljoin(BASE_URL, href)
    product_id = product_id_from_url(url)
    if not product_id:
        return None

    container = find_product_container(link)
    card_text = normalize_text(container.inner_text())

    name = first_text(
        container,
        (
            ".name a",
            ".name",
            ".prdName a",
            ".prdName",
            '[class*="prdName"] a',
            '[class*="prdName"]',
            '[class*="product_name"] a',
            '[class*="product_name"]',
            '[class*="description"] a',
        ),
    )

    if not name:
        name = normalize_text(link.inner_text())

    if not name:
        name = normalize_text(link.get_attribute("title"))

    if not name:
        return None

    price = first_text(
        container,
        (
            ".xans-product-listitem li",
            ".price",
            ".sale",
            ".product_price",
            '[class*="price"]',
        ),
    )
    price = parse_price(price or card_text)
    image = first_image(container)

    return {
        "id": product_id,
        "name": name,
        "price": price,
        "url": url,
        "image": image,
    }


def collect_current_page(page, products: dict[str, dict], max_products: int) -> int:
    links = page.locator('a[href*="/product/"]')
    print(f"Candidate /product/ links on page: {links.count()}")

    for i in range(links.count()):
        if len(products) >= max_products:
            break
        try:
            product = extract_product(links.nth(i))
            if not product:
                continue
            products[product["id"]] = product
        except Exception as exc:
            print(f"[skip] product link {i}: {exc}")

    return len(products)


def crawl_products(search_url: str, max_products: int = 1000, keywords: list[str] | None = None) -> list[dict]:
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
            page.wait_for_timeout(2_500)

            print(f"HTTP status: {response.status if response else 'unknown'}")
            print(f"Page title: {normalize_text(page.title())}")
            print(f"Final URL: {page.url}")

            collect_current_page(page, products, max_products)

            pagination_links = page.locator(
                'a[href*="page="], a[href*="page_num="], a[href*="?page"]'
            )
            page_urls: list[str] = []
            for i in range(pagination_links.count()):
                href = pagination_links.nth(i).get_attribute("href")
                if not href:
                    continue
                candidate = urljoin(page.url, href)
                parsed = urlparse(candidate)
                query = parse_qs(parsed.query)
                page_value = query.get("page", query.get("page_num", [""]))[0]
                if page_value.isdigit() and candidate not in page_urls:
                    page_urls.append(candidate)

            def page_number(url: str) -> int:
                query = parse_qs(urlparse(url).query)
                value = query.get("page", query.get("page_num", ["1"]))[0]
                return int(value) if value.isdigit() else 1

            page_urls.sort(key=page_number)
            print(f"Discovered pagination pages: {len(page_urls)}")

            for page_url in page_urls:
                if len(products) >= max_products:
                    break
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_500)
                    before = len(products)
                    collect_current_page(page, products, max_products)
                    print(f"Page {page_number(page_url)}: +{len(products) - before} products")
                except Exception as exc:
                    print(f"[pagination skip] {page_url}: {exc}")

            result = list(products.values())[:max_products]
            print(f"Collected {len(result)} HeroTime products")
            for product in result[:10]:
                print(f"  - {product['id']} | {product['name']} | {product['price']}")
            return result
        finally:
            context.close()
            browser.close()
