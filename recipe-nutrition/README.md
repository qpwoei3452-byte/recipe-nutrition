# 한국 레시피 영양 분석기

식품의약품안전처 레시피 DB + 농촌진흥청 영양성분 DB + KAMIS 가격 API를 연동한 졸업 프로젝트용 웹 애플리케이션입니다.

---

## 폴더 구조

```
recipe-nutrition/
├── backend/
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── config.py                # 환경변수 로딩 (.env)
│   ├── routers/
│   │   ├── recipe.py            # GET /api/recipe/search, /{id}/detail
│   │   └── export.py            # POST /api/export/csv, /excel
│   ├── services/
│   │   ├── recipe_service.py    # 식약처 레시피 API (Mock/Real 전환)
│   │   ├── nutrition_service.py # 농진청 영양성분 API
│   │   └── price_service.py     # KAMIS 가격 API
│   ├── utils/
│   │   ├── normalizer.py        # 재료명 표준화 규칙
│   │   └── unit_converter.py    # 단위 → g 환산
│   └── data/
│       ├── sample_recipes.json  # 식약처 API 응답 샘플
│       ├── sample_nutrition.json# 농진청 영양성분 샘플 (100g 기준)
│       ├── sample_prices.json   # KAMIS 가격 샘플 (100g당 원)
│       └── ingredient_master.csv# 재료 표준명 마스터 테이블
├── frontend/
│   ├── index.html               # 메인 UI
│   ├── css/style.css
│   └── js/
│       ├── api.js               # 백엔드 호출 (API 키 없음)
│       └── render.js            # DOM 렌더링
├── .env                         # API 키 (git 제외)
├── .env.example                 # 키 예시
├── requirements.txt
└── README.md
```

---

## 빠른 시작 (샘플 데이터 모드)

### 1) Python 가상환경 생성 및 패키지 설치

```bash
cd recipe-nutrition

# 가상환경 생성
python -m venv venv

# 활성화 (macOS/Linux)
source venv/bin/activate

# 활성화 (Windows)
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 2) 환경변수 설정

```bash
# .env 파일은 이미 USE_MOCK=true로 설정되어 있습니다.
# 실제 API 키 없이도 바로 실행 가능합니다.
cat .env
```

### 3) 백엔드 서버 실행

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 4) 브라우저에서 접속

```
http://localhost:8000
```

- API 문서(Swagger): `http://localhost:8000/docs`
- API 문서(ReDoc):   `http://localhost:8000/redoc`

---

## 실제 공공데이터 API 연동 방법

### Step 1: API 키 발급

| 데이터 | 발급 사이트 | 검색어 |
|--------|------------|--------|
| 식약처 레시피 | [data.go.kr](https://www.data.go.kr) | `식품의약품안전처_조리식품의 레시피 DB 정보` |
| 농진청 영양성분 | [data.go.kr](https://www.data.go.kr) | `농촌진흥청_국립농업과학원_통합식품영양성분정보` |
| KAMIS 가격 | [kamis.or.kr](https://www.kamis.or.kr) | 오픈API → 이용신청 |

### Step 2: .env 파일 수정

```env
USE_MOCK=false                        # ← 이 줄만 바꾸면 실제 API 사용
MFDS_API_KEY=발급받은_식약처_키
RDA_API_KEY=발급받은_농진청_키
KAMIS_API_KEY=발급받은_KAMIS_키
KAMIS_API_ID=발급받은_KAMIS_ID
```

### Step 3: 실제 API 교체 지점 (코드 수정)

각 서비스 파일에 `# TODO:` 주석으로 교체 지점이 명시되어 있습니다.

- `services/recipe_service.py` → `_fetch_real_search()`, `_fetch_real_detail()`
- `services/nutrition_service.py` → `_fetch_real_nutrition()`
- `services/price_service.py` → `_fetch_real_price()`

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 레시피 검색 | 이름으로 검색, 전체 목록 보기 |
| 재료명 표준화 | 달걀→계란, 소고기→쇠고기 등 자동 변환 |
| 단위 환산 | 개/큰술/공기/ml 등 → g으로 통일 |
| 영양 분석 | 재료별 + 레시피 전체 영양 합산 |
| 가격 계산 | 재료별 + 총 재료비 산출 |
| 오류 목록 | 매핑 실패 재료 별도 표시 |
| CSV/Excel 저장 | 분석 결과 3개 시트로 내보내기 |

---

## 재료명 표준화 규칙 예시

| 원본 | 표준명 | 규칙 |
|------|--------|------|
| 달걀, 달걀(2개) | 계란 | 동의어 매핑 |
| 소고기, 불고기용 소고기 | 쇠고기 | 동의어 매핑 |
| 청양고추 | 고추(청양) | 세분류 처리 |
| 참치캔, 참치 캔 | 참치(통조림) | 표현 통합 |
| 간장 | 간장(진간장) | 기본값 설정 |
| 대파, 파 | 파(대파) | 기본값 설정 |

---

## 단위 환산 기준

| 단위 | 기준 | 예시 |
|------|------|------|
| 큰술 | 15g (ml) | 된장 3큰술 = 54g |
| 작은술 | 5g (ml) | 마늘 1작은술 = 5g |
| 컵 | 200ml | 물 1컵 = 200g |
| 계란 1개 | 55g | 중란 기준 |
| 밥 1공기 | 210g | 일반 공기 기준 |
| 양파 1개 | 200g | 중간 크기 기준 |
| 감자 1개 | 150g | 중간 크기 기준 |
| 마늘 1쪽 | 5g | 깐마늘 기준 |

---

## API 엔드포인트 요약

```
GET  /api/recipe/search?q={검색어}    레시피 검색
GET  /api/recipe/{id}/detail          재료+영양+가격 상세
POST /api/export/csv                  CSV 다운로드
POST /api/export/excel                Excel 다운로드
GET  /api/health                      서버 상태 확인
GET  /docs                            Swagger API 문서
```

---

## 데이터 출처

- **레시피**: 식품의약품안전처 조리식품의 레시피 DB (공공데이터포털)
- **영양정보**: 농촌진흥청 국가표준식품성분표 제10개정판 (2021)
- **가격정보**: KAMIS 농산물유통정보 서울 소매가격 기준
