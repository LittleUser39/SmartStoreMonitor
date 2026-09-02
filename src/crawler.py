from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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


def build_keyword_search_url(search_url: str, keyword: str) -> str:
    """Replace only the search keyword while preserving the existing URL parameters."""
    parsed = urlparse(search_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["keyword"] = [keyword]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


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


def debug_compare_sold_out_pages() -> None:
    """Compare SOLD OUT DOM structures for known in-stock and sold-out products."""
    test_products = [
        {
            "id": "76080",
            "name": "판매중 상품",
            "url": "https://herotime.co.kr/product/detail.html?product_no=76080&cate_no=1&display_group=25",
        },
        {
            "id": "69294",
            "name": "품절 상품",
            "url": "https://herotime.co.kr/product/%EC%9E%85%EA%B3%A0%EC%99%84%EB%A3%8C%EA%B5%BF%EC%8A%A4%EB%A7%88%EC%9D%BC%EC%BB%B4%ED%8D%BC%EB%8B%88-%EB%84%A8%EB%8F%84%EB%A1%9C%EC%9D%B4%EB%93%9C%EC%BA%90%EB%A6%AD%ED%84%B0%EB%B3%B4%EC%BB%AC%EC%8B%9C%EB%A6%AC%EC%A6%8801-%ED%95%98%EC%B8%A0%EB%84%A4%EB%AF%B8%EC%BF%A0-%EB%A7%88%EB%84%A4%ED%82%A4%EB%AF%B8%EC%BF%A0ver%EC%9E%AC%ED%8C%90/69294/category/63/display/1/",
        },
    ]

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
            for product in test_products:
                print()
                print("=" * 80)
                print(f"[SOLD OUT DOM DEBUG] {product['id']} | {product['name']}")
                print("=" * 80)

                response = page.goto(
                    product["url"],
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(2_000)

                print(f"HTTP status : {response.status if response else 'unknown'}")
                print(f"Final URL   : {page.url}")
                print(f"Page title  : {normalize_text(page.title())}")

                sold_out = page.get_by_text("SOLD OUT", exact=True)
                count = sold_out.count()
                print(f"SOLD OUT count: {count}")

                if count == 0:
                    print(">>> SOLD OUT 요소가 DOM에 존재하지 않습니다.")
                    continue

                for index in range(count):
                    element = sold_out.nth(index)
                    print()
                    print(f"--- SOLD OUT #{index} ---")

                    try:
                        print("visible      :", element.is_visible())
                    except Exception:
                        print("visible      : ERROR")

                    try:
                        print("enabled      :", element.is_enabled())
                    except Exception:
                        print("enabled      : ERROR")

                    try:
                        print("tag          :", element.evaluate("(el) => el.tagName"))
                    except Exception:
                        print("tag          : ERROR")

                    try:
                        print("class        :", element.get_attribute("class"))
                    except Exception:
                        print("class        : ERROR")

                    try:
                        print("id           :", element.get_attribute("id"))
                    except Exception:
                        print("id           : ERROR")

                    try:
                        print("style        :", element.get_attribute("style"))
                    except Exception:
                        print("style        : ERROR")

                    try:
                        outer_html = element.evaluate("(el) => el.outerHTML")
                        print("outerHTML    :")
                        print(outer_html[:3000])
                    except Exception:
                        print("outerHTML    : ERROR")

                    try:
                        parent_html = element.evaluate(
                            "(el) => el.parentElement?.outerHTML || ''"
                        )
                        print("parentHTML   :")
                        print(parent_html[:5000])
                    except Exception:
                        print("parentHTML   : ERROR")

                    try:
                        ancestor_html = element.evaluate(
                            """
                            (el) => {
                                let current = el;
                                let result = [];

                                for (let i = 0; i < 5 && current; i++) {
                                    result.push(current.outerHTML);
                                    current = current.parentElement;
                                }

                                return result.join(
                                    "\\n\\n--- ANCESTOR ---\\n\\n"
                                );
                            }
                            """
                        )
                        print("ancestorHTML :")
                        print(ancestor_html[:10000])
                    except Exception:
                        print("ancestorHTML : ERROR")
        finally:
            page.close()
            context.close()
            browser.close()


def is_sold_out(detail_page, product: dict) -> bool:
    """Return True only when a visible SOLD OUT exists in the product action area."""
    try:
        detail_page.goto(
            product["url"],
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        detail_page.wait_for_timeout(800)

        # Only inspect the actual product purchase/action area.
        sold_out = detail_page.locator(
            ".xans-product-action .ec-base-button > span.btnEm.gFlex2"
        )

        for i in range(sold_out.count()):
            element = sold_out.nth(i)

            if not element.is_visible():
                continue

            text = normalize_text(element.inner_text())

            if text == "SOLD OUT":
                return True

        return False

    except Exception as exc:
        print(
            f"[soldout check skip] "
            f"{product['id']} | {product['name']}: {exc}"
        )
        return False


def cleanup_sold_out_products(products: dict[str, dict]) -> list[str]:
    """Return IDs from the existing database that currently contain exact 'SOLD OUT'."""
    if not products:
        return []

    sold_out_ids: list[str] = []

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
        detail_page = context.new_page()
        try:
            print(f"Checking existing database products: {len(products)}")
            for product_id, product in products.items():
                if is_sold_out(detail_page, product):
                    print(f"[DB SoldOut] {product_id} | {product.get('name', 'Unknown')}")
                    sold_out_ids.append(str(product_id))
        finally:
            detail_page.close()
            context.close()
            browser.close()

    return sold_out_ids


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
    keywords = [keyword.strip() for keyword in (keywords or []) if keyword and keyword.strip()]

    search_targets = [(None, search_url)] if not keywords else [
        (keyword, build_keyword_search_url(search_url, keyword))
        for keyword in keywords
    ]

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
            for keyword, target_url in search_targets:
                if max_products is not None and len(products) >= max_products:
                    break

                print(f"=== Keyword: {keyword or '(configured search URL)'} ===")
                response = page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
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
