# SmartStoreMonitor

네이버 스마트스토어에서 상품을 주기적으로 확인하고, 상품명에 설정한 키워드가 포함된 신규 상품을 Discord Webhook으로 알리는 개인용 모니터입니다.

## 현재 설정

- Store: https://smartstore.naver.com/gsc_korea_dt_pw
- Keyword: `미쿠`
- Check schedule: GitHub Actions 기준 5분마다 예약 실행
- Browser: Playwright Chromium
- Duplicate state: `data/products.json`

## Discord 설정

GitHub Repository의 `Settings → Secrets and variables → Actions`에서 다음 Repository Secret을 추가합니다.

- Name: `DISCORD_WEBHOOK_URL`
- Value: Discord 채널의 Webhook URL

Webhook URL을 소스 코드나 `config.json`에 저장하지 마세요.

## 실행

GitHub Actions의 `SmartStore Miku Monitor` workflow에서 `Run workflow`를 선택하면 수동 실행할 수 있습니다.

자동 실행은 `.github/workflows/monitor.yml`의 schedule에 의해 수행됩니다. GitHub Actions의 scheduled workflow는 정확한 시각에 실행된다고 보장되지 않을 수 있습니다.

## 로컬 테스트

```bash
python -m pip install -r requirements.txt
playwright install chromium
python src/main.py
```

## 주의

SmartStore의 페이지 구조가 변경되면 `src/crawler.py`의 상품 링크 수집 로직을 수정해야 할 수 있습니다. 이 프로젝트는 공개/공식 API를 우회하는 인증 정보나 비공개 API를 사용하지 않습니다.
