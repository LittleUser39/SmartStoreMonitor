from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import sync_playwright

BASE_URL = "https://herotime.co.kr"
PRODUCT_ID_RE = re.compile(r"/product/[^/]+/(\d+)(?:/|$)", re.I)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text: str) -> str:
    matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,9})\s*원", text or "")
    if not matches:
        return "가격 정보 없음"
    return f"{int(matches[0].replace(',', '')):,}원"


def product_id_from_url(url: str) -> str | None:
    path = urlparse(url).path
    match = PRODUCT_ID_RE.search(path)
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
    for selector in ("img[data-src]", "img[data-original]", "img[src]"):
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

    return {
        "id": product_id,
        "name": name,
        "price": parse_price(price or card_text),
        "url": url,
        "image": first_image(container),
    }


def is_sold_out(detail_page, product: dict) -> bool:
    """Check the product detail page for a visible SOLD OUT/품절 purchase state."""
    try:
        detail_page.goto(product["url"], wait_until="domcontentloaded", timeout=60_000)
        detail_page.wait_for_timeout(800)

        # Prefer visible purchase-area controls/text. HeroTime currently renders
        # sold-out products with a visible "SOLD OUT" state in the purchase UI.
        sold_out_locators = (
            detail_page.get_by_text(re.compile(r"^SOLD\s*OUT$", re.I)).filter(visible=True),
            detail_page.get_by_text(re.compile(r"^품절$"), exact=True).filter(visible=True),
        )
        for locator in sold_out_locators:
            if locator.count() > 0:
                return True

        # Fallback: inspect visible text around the purchase/action area without
        # treating unrelated hidden page content as a sold-out signal.
        action_area = detail_page.locator(
            ".xans-product-action, #NaverChk_Button, .product-detail, .detailArea"
        ).filter(visible=True)
        if action_area.count() > 0:
            text = normalize_text(action_area.first.inner_text())
            if re.search(r"\bSOLD\s*OUT\b|\b품절\b", text, re.I):
                return True
    except Exception as exc:
        print(f"[soldout check skip] {product['id']} | {product['name']}: {exc}")

    return False


def collect_current_page(page, products: dict[str, dict], max_products: int | None, debug_links: bool = False) -> int:
    links = page.locator('a[href*="/product/"]')
    count = links.count()
    print(f"Candidate /product/ links on page: {count}")

    if debug_links:
        print("--- HeroTime product-link diagnostics (first 30) ---")
        for i in range(min(count, 30)):
            try:
                href = links.nth(i).get_attribute("href") or ""
                text = normalize_text(links.nth(i).inner_text())
                absolute = urljoin(page.url, href)
                print(f"[link {i}] href={href!r} | id={product_id_from_url(absolute)!r} | text={text[:120]!r}")
            except Exception as exc:
                print(f"[link {i}] diagnostic error: {exc}")
        print("--- end diagnostics ---")

    for i in range(count):
        if max_products is not None and len(products) >= max_products:
            break
        try:
            product = extract_product(links.nth(i))
            if not product:
                continue
            products[product["id"]] = product
        except Exception as exc:
            print(f"[skip] product link {i}: {exc}")

    return len(products)


def crawl_products(search_url: str, max_products: int | None = None, keywords: list[str] | None = None) -> list[dict]:
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
        detail_page = context.new_page()
        try:
            response = page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_500)

            print(f"HTTP status: {response.status if response else 'unknown'}")
            print(f"Page title: {normalize_text(page.title())}")
            print(f"Final URL: {page.url}")

            collect_current_page(page, products, max_products, debug_links=True)

            pagination_links = page.locator(
                'a[href*="page="], a[href*="page_num="], a[href*="?page"]'
            )
            page_urls: list[str] = []
            for i in range(pagination_links.count()):
                href = pagination_links.nth(i).get_attribute("href")
                if not href:
                    continue
                candidate = urljoin(page.url, href)
                query = parse_qs(urlparse(candidate).query)
                page_value = query.get("page", query.get("page_num", [""]))[0]
                if page_value.isdigit() and candidate not in page_urls:
                    page_urls.append(candidate)

            def page_number(url: str) -> int:
                query = parse_qs(urlparse(url).query)
                value = query.get("page", query.get("page_num", ["1"]))[0]
                return int(value) if value.isdigit() else 1

            page_urls.sort(key=page_number)
            print(f"Discovered pagination pages: {len(page_urls)}")

            visited_urls = {page.url}
            for page_url in page_urls:
                if max_products is not None and len(products) >= max_products:
                    break
                if page_url in visited_urls:
                    continue
                visited_urls.add(page_url)
                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_500)
                    before = len(products)
                    collect_current_page(page, products, max_products)
                    print(f"Page {page_number(page_url)}: +{len(products) - before} products")
                except Exception as exc:
                    print(f"[pagination skip] {page_url}: {exc}")

            result = list(products.values())
            if max_products is not None:
                result = result[:max_products]

            # Check the detail page only after collecting the search results so
            # pagination remains fast and max_products still applies to the
            # collected candidate set. Sold-out products are removed before
            # main.py compares and notifies new products.
            available_products: list[dict] = []
            sold_out_count = 0
            for product in result:
                if is_sold_out(detail_page, product):
                    print(f"[SoldOut] {product['id']} | {product['name']}")
                    sold_out_count += 1
                    continue
                available_products.append(product)

            print(f"Sold-out products excluded: {sold_out_count}")
            print(f"Collected {len(available_products)} available HeroTime products")
            for product in available_products[:10]:
                print(f"  - {product['id']} | {product['name']} | {product['price']}")
            return available_products
        finally:
            detail_page.close()
            context.close()
            browser.close()
