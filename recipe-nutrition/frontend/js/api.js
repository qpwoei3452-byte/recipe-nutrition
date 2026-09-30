export async function searchRecipes(query = '') {
  const params = new URLSearchParams({
    q: query,
    cache: Date.now().toString()
  });
  const url = `/api/recipe/search?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('검색 실패');
  return res.json();
}

export async function getRecipeDetail(recipeId, recipeName = '') {
  if (!recipeId) throw new Error('recipeId가 없습니다.');
  const params = new URLSearchParams({ cache: Date.now().toString() });
  if (recipeName && recipeName.trim()) params.set('name', recipeName.trim());
  const url = `/api/recipe/${encodeURIComponent(recipeId)}/detail?${params.toString()}`;
  console.log('[API 요청 전송]', { recipeId, recipeName, url });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`상세 데이터 로드 실패: ${res.status}`);
  return res.json();
}

export async function recommendRecipes(query = '', mode = '기본', topN = 20, opts = {}) {
  const params = new URLSearchParams({
    q: query,
    mode: mode,
    top_n: topN,
    cache: Date.now().toString()
  });
  // 개인 맞춤형: 저장된 프로필이 있으면 user_id 로 추천 (가중치 + 로그 활용)
  if (opts.userId) {
    params.set('user_id', opts.userId);
  } else if (opts.weights) {
    // 비로그인 즉석 가중치
    const w = opts.weights;
    if (w.price   != null) params.set('w_price',   w.price);
    if (w.protein != null) params.set('w_protein', w.protein);
    if (w.calorie != null) params.set('w_calorie', w.calorie);
    if (w.sodium  != null) params.set('w_sodium',  w.sodium);
    if (w.time    != null) params.set('w_time',    w.time);
  }
  // 사용자가 직접 입력한 "최근 먹은 음식" — 다양성 패널티에 반영
  if (opts.history && opts.history.length) {
    params.set('history', opts.history.join(','));
  }
  if (opts.allergens && opts.allergens.length) {
    params.set('allergens', opts.allergens.join(','));
  }
  const res = await fetch(`/api/recipe/recommend?${params}`);
  if (!res.ok) throw new Error('추천 검색 실패: ' + res.status);
  return res.json();
}

// ── 프로필 API (개인 맞춤형) ──────────────────────────────────
export async function createProfile(weights) {
  const res = await fetch('/api/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ weights }),
  });
  if (!res.ok) throw new Error('프로필 생성 실패: ' + res.status);
  return res.json();
}

export async function getProfile(userId) {
  const res = await fetch(`/api/profile/${encodeURIComponent(userId)}?cache=${Date.now()}`);
  if (!res.ok) throw new Error('프로필 조회 실패: ' + res.status);
  return res.json();
}

export async function updateProfileWeights(userId, weights) {
  const res = await fetch(`/api/profile/${encodeURIComponent(userId)}/weights`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(weights),
  });
  if (!res.ok) throw new Error('가중치 업데이트 실패: ' + res.status);
  return res.json();
}

export async function logFood(userId, foodName) {
  const res = await fetch(`/api/profile/${encodeURIComponent(userId)}/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ food_name: foodName }),
  });
  if (!res.ok) throw new Error('음식 기록 실패: ' + res.status);
  return res.json();
}

// ── 추가된 함수 ──────────────────────────────────────────────
// 카드 클릭 시 호출 — AI로 조리시간·추천이유·유사도 분석
export async function aiAnalyzeRecipe(recipeId, name = '', history = []) {
  const params = new URLSearchParams({
    name:    name,
    history: history.join(','),
    cache:   Date.now().toString(),
  });
  const res = await fetch(`/api/recipe/${encodeURIComponent(recipeId)}/ai-analyze?${params}`);
  if (!res.ok) throw new Error('AI 분석 실패: ' + res.status);
  return res.json();
}

export async function checkHealth() {
  const res = await fetch(`/api/health?cache=${Date.now()}`);
  return res.json();
}

// 조리 순서 초보자용 해설 ("쉽게 보기" 토글) — 레시피당 서버에서 캐시되어
// 두 번째 요청부터는 즉시 응답됨
export async function getEasySteps(recipeId, name = '') {
  const params = new URLSearchParams({ name, cache: Date.now().toString() });
  const res = await fetch(`/api/recipe/${encodeURIComponent(recipeId)}/easy-steps?${params}`);
  if (!res.ok) throw new Error('조리 순서 해설 로드 실패: ' + res.status);
  return res.json();
}