# HeroTime Product Monitor

HeroTime 검색 결과에서 `config.json`에 등록한 여러 키워드의 상품을 Playwright로 수집하고, 처음 발견한 상품을 Discord Webhook과 Notion으로 알립니다.

## 대상 페이지

`config.json`의 `store_url`을 기준으로 검색하며, `keywords`에 원하는 키워드를 원하는 만큼 등록할 수 있습니다.

## 키워드 설정

`config.json`의 `keywords` 배열만 수정하면 됩니다.

```json
{
  "store_url": "https://herotime.co.kr/product/search.html?banner_action=&keyword=%EB%AF%B8%EC%BF%A0",
  "keywords": [
    "미쿠",
    "니케",
    "블루아카이브"
  ]
}
```

- 키워드를 추가하려면 배열에 문자열을 추가합니다.
- 키워드를 삭제하려면 해당 문자열을 삭제합니다.
- 키워드는 1개만 등록해도 됩니다.
- 키워드 개수에 별도의 코드 수정은 필요하지 않습니다.
- `max_products`를 설정하지 않으면 검색 결과의 전체 페이지를 대상으로 수집합니다.

## 수집 방식

1. `keywords`의 키워드를 하나씩 HeroTime 검색 URL에 적용합니다.
2. 각 키워드의 페이지네이션을 끝까지 확인합니다.
3. 상품 ID 기준으로 중복 상품을 제거합니다. 여러 키워드에 동시에 검색되는 상품도 한 번만 처리합니다.
4. 상품 상세 페이지에서 `SOLD OUT` 또는 `품절` 상태를 확인하고 품절 상품은 제외합니다.
5. `data/products.json`에 이미 저장된 상품 ID인지 확인합니다.
6. 처음 발견한 상품이면 Discord Webhook과 Notion으로 알립니다.
7. 두 알림이 모두 성공한 뒤 새 상품 상태를 저장합니다.

## 수집 정보

- 상품명
- 판매 가격
- 상품 이미지
- 상품 URL
- 상품 ID

## Discord 설정

GitHub Repository의 Settings → Secrets and variables → Actions에서 다음 Secret을 추가합니다.

`DISCORD_WEBHOOK_URL`

값에는 Discord 채널의 Webhook URL을 입력합니다.

## 수동 테스트

GitHub → Actions → `HeroTime Miku Monitor` → `Run workflow`를 실행합니다.

> GitHub Actions의 scheduled workflow는 정확히 5분마다 실행된다고 보장되지 않습니다. GitHub의 실행 지연이 발생할 수 있습니다.
