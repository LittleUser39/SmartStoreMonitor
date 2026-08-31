# HeroTime Miku Monitor

HeroTime 검색 결과에서 `미쿠` 상품을 Playwright로 수집하고, 처음 발견한 상품을 Discord Webhook으로 알립니다.

## 대상 페이지

https://herotime.co.kr/product/search.html?banner_action=&keyword=%EB%AF%B8%EC%BF%A0

## 수집 정보

- 상품명
- 판매 가격
- 상품 이미지
- 상품 URL
- 상품 ID

## 동작 방식

1. GitHub Actions가 약 5분 주기로 실행됩니다.
2. Playwright Chromium으로 HeroTime 검색 페이지를 엽니다.
3. `/product/.../상품ID/` 형태의 상품 링크를 찾습니다.
4. 상품 카드에서 이름/가격/이미지를 추출합니다.
5. `data/products.json`에 이미 저장된 상품 ID인지 확인합니다.
6. 처음 발견한 상품이면 Discord Webhook으로 알립니다.
7. 새 상품 상태를 GitHub에 커밋합니다.

## Discord 설정

GitHub Repository의 Settings → Secrets and variables → Actions에서 다음 Secret을 추가합니다.

`DISCORD_WEBHOOK_URL`

값에는 Discord 채널의 Webhook URL을 입력합니다.

## 수동 테스트

GitHub → Actions → `HeroTime Miku Monitor` → `Run workflow`를 실행합니다.

> GitHub Actions의 scheduled workflow는 정확히 5분마다 실행된다고 보장되지 않습니다. GitHub의 실행 지연이 발생할 수 있습니다.
