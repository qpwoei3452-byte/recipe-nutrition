/* ──────────────────────────────────────────────────────
   render.js  v2.0
   추천 점수·이유·상세 분석이 한 페이지에 통합된 버전
   ────────────────────────────────────────────────────── */

import { getEasySteps } from './api.js';

const MODE_LABEL = { '기본':'균형', '가성비':'가성비', '고단백':'고단백', '저칼로리':'저칼로리', '맞춤':'내 선호' };
const MODE_CLS   = { '기본':'badge-mode-균형', '가성비':'badge-mode-가성비', '고단백':'badge-mode-고단백', '저칼로리':'badge-mode-저칼로리', '맞춤':'badge-mode-맞춤' };

// "쉽게 보기" 결과의 클라이언트 캐시(레시피 id → steps) — 토글 왔다갔다 할 때 재요청 방지
const _easyStepsMemCache = {};
// 현재 화면에 떠 있는 타이머들 (레시피 전환 시 정리해서 orphan 타이머 방지)
let _activeTimers = [];

function _clearAllTimers() {
  _activeTimers.forEach(id => clearInterval(id));
  _activeTimers = [];
}

/* ── 로딩 / 에러 ─────────────────────────────────── */
export function renderLoading(container, message = '로딩 중...') {
  container.innerHTML = `
    <div class="loading-wrap">
      <div class="spinner"></div>
      <div class="loading-text">${message}</div>
    </div>`;
}

export function renderError(container, message = '오류가 발생했습니다.') {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">⚠️</div>
      <p>${message}</p>
    </div>`;
}

/* ── 레시피 카드 목록 ──────────────────────────────
   recommend 결과는 score / reason / _scores 포함    */
export function renderRecipeList(recipes, container, onSelect, mode = '기본', rankOffset = 0) {
  container.innerHTML = '';

  if (!recipes || recipes.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🍽️</div>
        <p>검색 결과가 없습니다. 다른 키워드를 입력해보세요.</p>
      </div>`;
    return;
  }

  /* 결과 요약 바 */
  const bar = document.createElement('div');
  bar.className = 'result-bar';
  bar.innerHTML = `
    <span class="result-count"><strong>${recipes.length}</strong>개 레시피</span>`;
  container.appendChild(bar);

  const grid = document.createElement('div');
  grid.className = 'recipe-grid';

  recipes.forEach((r, idx) => {
    const rank   = idx + 1 + rankOffset;
    const score  = r.score ?? null;
    const reason = r.reason ?? '';
    // 다양성 패널티로 순위가 조정된 항목 (이전에 먹었거나 이미 추천된 것과 유사)
    const divSim = r.diversity_sim ?? r.similarity_score ?? 0;
    const divNote = divSim >= 0.5
      ? `<div class="card-diversity-note">🔀 비슷한 메뉴가 있어 순위 조정됨</div>`
      : '';

    const card = document.createElement('div');
    card.className = 'recipe-card';
    // ★ Bug Fix: 즐겨찾기/별점 기능이 올바른 ID를 쓰도록 data 속성 설정
    const _rid = r.id ?? r.RCP_SEQ ?? '';
    if (_rid) card.dataset.recipeId = String(_rid);
    card.dataset.recipeName = r.name ?? '';

    card.innerHTML = `
      <div class="card-rank-badge rank-${rank <= 3 ? rank : 'n'}">${rank}위</div>
      ${r.image_url
        ? `<img class="card-img" src="${r.image_url}" alt="${r.name}" onerror="this.outerHTML='<div class=\\'card-img-placeholder\\'>${_foodEmoji(r)}</div>'">`
        : `<div class="card-img-placeholder">${_foodEmoji(r)}</div>`}
      <div class="card-body">
        <div class="card-name">${r.name ?? ''}</div>
        <div class="card-meta">
          <span class="meta-badge">${r.category ?? ''}</span>
          <span class="meta-badge">${r.method ?? ''}</span>
        </div>

        ${reason ? `<div class="card-reason">💡 ${reason}</div>` : ''}
        ${divNote}
        <div class="card-cal-row">
          ${r.nutrition_total?.energy_kcal ? `<span class="card-cal">${Math.round(r.nutrition_total.energy_kcal)} kcal</span>` : ''}
          ${_priceBadge(r.price_total_krw)}
        </div>
      </div>
      <div class="rf-actions">
        <span class="rf-label">평가</span>
        <span class="rf-stars">${[1,2,3,4,5].map(n =>
          `<span class="rf-star" data-score="${n}">☆</span>`).join('')}</span>
        <button type="button" class="rf-fav">🤍 즐겨찾기</button>
      </div>`;

    card.addEventListener('click', () => {
      document.querySelectorAll('.recipe-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      onSelect(r);
    });

    // [FIX] 별점·즐겨찾기를 카드와 같이 렌더하고, 이 카드가 어느 레시피인지
    // 클로저(_rid, r.name)로 직접 보유한다. DOM을 뒤져 추측하지 않으므로
    // "옆 레시피가 저장되는" 문제가 구조적으로 사라진다.
    _wireCardActions(card, _rid, r.name ?? '', r.image_url ?? '');

    grid.appendChild(card);
  });

  container.appendChild(grid);
}

/* ── 별점/즐겨찾기 공통 헬퍼 ───────────────────────────────── */
function _store() { return window.RecipeStore || null; }

function _paintStars(scope, score) {
  scope.querySelectorAll('.rf-star').forEach((st, i) => {
    const on = i < score;
    st.textContent = on ? '★' : '☆';
    st.classList.toggle('on', on);
  });
}

function _paintFav(btn, faved) {
  btn.textContent = faved ? '❤️ 즐겨찾기됨' : '🤍 즐겨찾기';
  btn.classList.toggle('on', faved);
}

function _wireCardActions(card, recipeId, recipeName, imageUrl) {
  const actions = card.querySelector('.rf-actions');
  const store   = _store();
  if (!actions || !store || !recipeId) return;

  const favBtn = actions.querySelector('.rf-fav');
  _paintStars(actions, store.getRating(recipeId));
  _paintFav(favBtn, store.isFavorite(recipeId));

  // [FIX] 별을 눌렀을 때 카드 클릭까지 같이 발동해 상세가 열리던 문제.
  // 액션 영역의 클릭은 카드로 전파시키지 않는다.
  actions.addEventListener('click', (e) => {
    e.stopPropagation();

    const star = e.target.closest('.rf-star');
    if (star) {
      const picked = parseInt(star.dataset.score, 10);
      const score  = store.getRating(recipeId) === picked ? 0 : picked;  // 같은 별 다시 누르면 취소
      store.saveRating(recipeId, recipeName, score);
      _paintStars(actions, score);
      _syncDetailRating(recipeId, score);
      return;
    }

    if (e.target.closest('.rf-fav')) {
      const added = store.toggleFavorite(recipeId, recipeName, imageUrl);
      _paintFav(favBtn, added);
      _syncDetailFav(recipeId, added);
    }
  });

  // 별 위에 올렸을 때 미리보기
  actions.querySelectorAll('.rf-star').forEach(st => {
    st.addEventListener('mouseenter', () => _paintStars(actions, parseInt(st.dataset.score, 10)));
  });
  actions.addEventListener('mouseleave', () => _paintStars(actions, store.getRating(recipeId)));
}

/* 목록 ↔ 상세 패널 상태 동기화 */
function _syncDetailRating(recipeId, score) {
  const wrap = document.querySelector(`#detail-rating-wrap[data-rid="${recipeId}"]`);
  if (wrap) _paintStars(wrap, score);
}
function _syncDetailFav(recipeId, faved) {
  const btn = document.querySelector(`#detail-fav-btn[data-rid="${recipeId}"]`);
  if (btn) _paintFav(btn, faved);
}
function _syncCardRating(recipeId, score) {
  document.querySelectorAll(`.recipe-card[data-recipe-id="${recipeId}"] .rf-actions`)
    .forEach(a => _paintStars(a, score));
}
function _syncCardFav(recipeId, faved) {
  document.querySelectorAll(`.recipe-card[data-recipe-id="${recipeId}"] .rf-fav`)
    .forEach(b => _paintFav(b, faved));
}

/* [FIX] 즐겨찾기 모달에서 항목을 지워도 목록 카드의 ❤️ 표시가 그대로 남아
   있었다. features.js(클래식 스크립트)에서 호출할 수 있도록 전역에 노출한다. */
window._syncFavUI = (recipeId, faved) => {
  _syncCardFav(recipeId, faved);
  _syncDetailFav(recipeId, faved);
};

/* ── 상세 패널 ─────────────────────────────────────
   recommend 결과에 score / reason / _scores 포함    */
export function renderDetail(detail, container) {
  _clearAllTimers(); // 이전 레시피에서 돌던 타이머가 있으면 정리

  const nt          = detail?.nutrition_total ?? {};
  const ingredients = Array.isArray(detail?.ingredients) ? detail.ingredients : [];
  const steps       = Array.isArray(detail?.steps) ? detail.steps : [];
  const scores      = detail?._scores ?? null;
  const score       = detail?.score ?? null;
  const reason      = detail?.reason ?? null;
  const mode        = detail?.mode ?? null;

  container.innerHTML = `
    <div class="detail-panel">

      <!-- ① 헤더 -->
      <div class="detail-header">
        <div>
          <!-- [FIX] 별점·즐겨찾기를 레시피명 바로 오른쪽에 둔다.
               예전에는 영양 요약 아래에 있어 스크롤해야 보였고,
               헤더 맨 끝으로 밀면 제목과 멀어져 연결이 약해진다.
               평가·즐겨찾기는 '이 레시피'에 대한 행동이므로
               이름과 같은 줄에 붙여 둔다. -->
          <div class="detail-title-row">
            <h2 class="detail-title">${detail?.name ?? ''}</h2>
            <div id="detail-rating-wrap" class="detail-actions" data-rid="${detail?.id ?? ''}">
              <div class="detail-actions-rate">
                <span class="detail-actions-label">평가</span>
                <div id="detail-stars" class="rf-stars rf-stars-lg"></div>
                <span id="detail-rating-label"></span>
              </div>
              <button type="button" id="detail-fav-btn" class="rf-fav"
                      data-rid="${detail?.id ?? ''}">🤍 즐겨찾기</button>
            </div>
          </div>
          <div class="detail-meta">
            <span class="meta-badge">${detail?.category ?? ''}</span>
            <span class="meta-badge">${detail?.method ?? ''}</span>
            <span class="source-chip">출처: ${detail?.source ?? '식약처'}</span>
          </div>
        </div>
      </div>

      <!-- ② 추천 분석 섹션 (score 있을 때만) -->
      ${scores ? _renderRecommendSection(detail, scores, score, reason, mode) : ''}

      <!-- ③ 영양 요약 — 식약처가 주는 1인분 기준값 (INFO_ENG 등) -->
      <div class="nutri-head">
        <span class="nutri-head-title">영양 정보</span>
        <span class="nutri-head-sub">1인분 기준 · 괄호는 1일 영양성분 기준치 대비</span>
      </div>
      <div class="nutrition-summary">
        ${_nutriCard('열량',    Math.round(nt.energy_kcal ?? 0), 'kcal')}
        ${_nutriCard('단백질',  _f1(nt.protein_g), 'g')}
        ${_nutriCard('지방',    _f1(nt.fat_g), 'g')}
        ${_nutriCard('탄수화물',_f1(nt.carb_g), 'g')}
        ${_nutriCard('나트륨',  Math.round(nt.sodium_mg ?? 0), 'mg')}
        ${_priceCard(detail?.price_total_krw)}
      </div>


      <!-- ④ 재료 테이블 -->
      <div class="table-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <div class="section-label" style="margin:0">재료 목록${
            detail?.servings ? `<span class="ing-servings">${detail.servings}인분 기준</span>` : ''
          }</div>
          <button id="ing-detail-toggle" onclick="(function(btn){
            var cols=document.querySelectorAll('.ing-nut-col');
            var show=cols[0]&&cols[0].style.display==='none';
            cols.forEach(function(c){c.style.display=show?'':'none';});
            btn.textContent=show?'영양 정보 숨기기':'재료별 영양 정보 보기';
          })(this)" style="font-size:12px;padding:3px 10px;border:1px solid #ddd;border-radius:6px;background:#f9fafb;cursor:pointer;color:#555" title="재료별 영양성분과 가격을 g 단위로 확인합니다">재료별 영양 정보 보기</button>
        </div>
        <div class="table-wrap">
          <table class="ing-table">
            <thead>
              <tr>
                <th>재료명</th>
                <th>사용량</th>
                <th class="ing-nut-col" style="display:none">단백질(g)</th>
                <th class="ing-nut-col" style="display:none">지방(g)</th>
                <th class="ing-nut-col" style="display:none">탄수화물(g)</th>
                <th class="ing-nut-col" style="display:none">나트륨(mg)</th>
                <th class="ing-nut-col" style="display:none">가격(원)</th>
              </tr>
            </thead>
            <tbody>
              ${_groupIngredients(ingredients).map(([sec, rows]) => `
                ${sec ? `<tr class="ing-section"><td colspan="7">${sec}</td></tr>` : ''}
                ${rows.map(ing => {
                const nMatched = !!(ing.nutrition_matched_name);
                const pMatched = !!(ing.price_matched_name);
                const hasData = nMatched || pMatched;
                return `
                <tr${hasData ? '' : ' class="ing-nodata"'}>
                  <td>${_ingName(ing.raw_name ?? ing.standard_nm)}</td>
                  <td>${_ingUnit(ing.raw_name, ing.amount_g, ing.amount_display)}</td>
                  <td class="ing-nut-col" style="display:none">${_cell(ing.protein_g, nMatched)}</td>
                  <td class="ing-nut-col" style="display:none">${_cell(ing.fat_g, nMatched)}</td>
                  <td class="ing-nut-col" style="display:none">${_cell(ing.carb_g, nMatched)}</td>
                  <td class="ing-nut-col" style="display:none">${_cell(ing.sodium_mg, nMatched, 0)}</td>
                  <td class="ing-nut-col" style="display:none">${pMatched ? Math.round(ing.price_krw ?? 0).toLocaleString() : '-'}</td>
                </tr>`;
              }).join('')}`).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- ⑤ 조리 순서 -->
      <div class="steps-section">
        <div class="steps-header-row">
          <div class="section-label" style="margin:0">조리 순서</div>
          <div class="steps-toggle" role="group">
            <button type="button" class="steps-toggle-btn active" data-mode="original">원본</button>
            <button type="button" class="steps-toggle-btn" data-mode="easy">✨ 쉽게 보기 (AI)</button>
          </div>
        </div>
        <ol class="step-list" id="steps-original">
          ${steps.map(s => `<li>
            ${s?.img_url ? `<img class="step-img" src="${s.img_url}" alt="" loading="lazy"
                 onerror="this.style.display='none'">` : ''}
            <span class="step-text">${(s?.desc ?? '').replace(/^\d+\.\s*/, '')}</span>
          </li>`).join('')}
        </ol>
        <div id="steps-easy" class="easy-steps-wrap" style="display:none"></div>
      </div>

    </div>`;

  /* 점수 바 애니메이션 */
  requestAnimationFrame(() => {
    container.querySelectorAll('.factor-bar-fill[data-w]').forEach(b => {
      b.style.width = b.dataset.w;
    });
  });

  _wireStepsToggle(container, detail);
  _wireDetailRating(container, detail);
}

/* ── 상세 패널 별점 + 즐겨찾기 배선 ─────────────────────────
   [FIX] 예전에는 이 함수가 localStorage 읽기/쓰기를 자체 구현해 features.js
   쪽 로직과 중복돼 있었다. 이제 window.RecipeStore 하나만 사용한다.
   상세 패널에 즐겨찾기 버튼이 없어 목록으로 되돌아가야 했던 문제도 함께 해결. */
function _wireDetailRating(container, detail) {
  const recipeId   = String(detail?.id ?? detail?.RCP_SEQ ?? '');
  const recipeName = detail?.name ?? '';
  const imageUrl   = detail?.image_url ?? '';
  const wrap       = container.querySelector('#detail-rating-wrap');
  const starsEl    = container.querySelector('#detail-stars');
  const labelEl    = container.querySelector('#detail-rating-label');
  const favBtn     = container.querySelector('#detail-fav-btn');
  const store      = _store();
  if (!starsEl || !wrap || !store || !recipeId) return;

  const STAR_LABELS = ['', '별로예요', '괜찮아요', '맛있어요', '훌륭해요', '최고예요!'];

  starsEl.innerHTML = [1, 2, 3, 4, 5]
    .map(n => `<span class="rf-star" data-score="${n}">☆</span>`).join('');

  function paint(score, note) {
    _paintStars(wrap, score);
    if (labelEl) labelEl.textContent = score ? (STAR_LABELS[score] + (note || '')) : '';
  }
  paint(store.getRating(recipeId));

  starsEl.addEventListener('click', (e) => {
    const star = e.target.closest('.rf-star');
    if (!star) return;
    const picked = parseInt(star.dataset.score, 10);
    const score  = store.getRating(recipeId) === picked ? 0 : picked;  // 같은 별 재클릭 = 취소
    store.saveRating(recipeId, recipeName, score);
    paint(score, ' (저장됨)');
    _syncCardRating(recipeId, score);
  });

  starsEl.querySelectorAll('.rf-star').forEach(st => {
    st.addEventListener('mouseenter', () => {
      const n = parseInt(st.dataset.score, 10);
      _paintStars(wrap, n);
      if (labelEl) labelEl.textContent = STAR_LABELS[n];
    });
  });
  starsEl.addEventListener('mouseleave', () => paint(store.getRating(recipeId)));

  if (favBtn) {
    _paintFav(favBtn, store.isFavorite(recipeId));
    favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const added = store.toggleFavorite(recipeId, recipeName, imageUrl);
      _paintFav(favBtn, added);
      _syncCardFav(recipeId, added);
    });
  }
}

/* ── "쉽게 보기(AI)" 토글 배선 ─────────────────────
   원본은 항상 그대로 유지, 버튼으로 원본↔AI 해설 전환. */
function _wireStepsToggle(container, detail) {
  const recipeId    = detail?.id ?? '';
  const recipeName  = detail?.name ?? '';
  const originalBox = container.querySelector('#steps-original');
  const easyBox     = container.querySelector('#steps-easy');
  const btns        = container.querySelectorAll('.steps-toggle-btn');
  if (!originalBox || !easyBox || btns.length === 0) return;

  function _revertToOriginal() {
    easyBox.style.display   = 'none';
    originalBox.style.display = '';
    btns.forEach(b => b.classList.remove('active'));
    const originalBtn = container.querySelector('.steps-toggle-btn[data-mode="original"]');
    if (originalBtn) originalBtn.classList.add('active');
  }

  function _showTransientNotice(recipeId, recipeName) {
    const existing = container.querySelector('#easy-steps-notice');
    if (existing) existing.remove();

    const notice = document.createElement('div');
    notice.id = 'easy-steps-notice';
    notice.style.cssText = [
      'background:#fffbea',
      'border:1px solid #f6d860',
      'border-radius:8px',
      'padding:10px 14px',
      'margin-top:10px',
      'display:flex',
      'align-items:center',
      'gap:10px',
      'font-size:14px',
      'color:#7d5a00',
    ].join(';');

    notice.innerHTML = `
      <span>⚠️ AI 해설을 불러오지 못했어요. 원본 조리 순서를 확인해주세요.</span>
      <button type="button" id="easy-steps-retry"
        style="background:#f6d860;border:none;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:13px;color:#5a3e00;white-space:nowrap">
        🔄 다시 시도
      </button>`;

    const stepsSection = container.querySelector('.steps-section');
    if (stepsSection) {
      stepsSection.insertBefore(notice, stepsSection.firstChild);
    }

    notice.querySelector('#easy-steps-retry')?.addEventListener('click', () => {
      notice.remove();
      const easyBtn = container.querySelector('.steps-toggle-btn[data-mode="easy"]');
      if (easyBtn) easyBtn.click();
    });

    const autoRemove = setTimeout(() => notice.remove(), 8000);
    notice.addEventListener('click', () => clearTimeout(autoRemove), { once: true });
  }

  btns.forEach(btn => {
    btn.addEventListener('click', async () => {
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      if (btn.dataset.mode === 'original') {
        easyBox.style.display = 'none';
        originalBox.style.display = '';
        return;
      }

      originalBox.style.display = 'none';
      easyBox.style.display = '';

      if (_easyStepsMemCache[recipeId]) {
        _renderEasySteps(easyBox, _easyStepsMemCache[recipeId]);
        return;
      }

      easyBox.innerHTML = `
        <div class="easy-loading">
          <div class="spinner spinner-sm"></div>
          <span>AI가 조리 순서를 더 쉽게 풀어쓰는 중이에요...</span>
        </div>`;

      try {
        const res = await getEasySteps(recipeId, recipeName);
        let easySteps = Array.isArray(res?.steps) ? res.steps : [];
        // 원본 단계의 사진을 같은 순서로 이어 붙인다
        const origSteps = Array.isArray(detail?.steps) ? detail.steps : [];
        easySteps = easySteps.map((st, i) => ({ ...st, img_url: origSteps[i]?.img_url || '' }));
        if (easySteps.length === 0) {
          _revertToOriginal();
          _showTransientNotice(recipeId, recipeName);
          return;
        }
        _easyStepsMemCache[recipeId] = easySteps;
        _renderEasySteps(easyBox, easySteps);
      } catch (e) {
        console.error('[쉽게 보기 로드 실패]', e);
        _revertToOriginal();
        _showTransientNotice(recipeId, recipeName);
      }
    });
  });
}

/* AI 해설 단계를 카드 형태로 렌더링 (팁·타이머 포함) */
function _renderEasySteps(container, steps) {
  container.innerHTML = `
    <ol class="easy-step-list">
      ${steps.map((s, i) => `
        <li class="easy-step-card">
          <div class="easy-step-num">${s.step ?? i + 1}</div>
          <div class="easy-step-body">
            ${s.img_url ? `<img class="step-img" src="${s.img_url}" alt="" loading="lazy"
                 onerror="this.style.display='none'">` : ''}
            <p class="easy-step-text">${s.detail ?? s.original ?? ''}</p>
            ${s.is_fallback ? `<div class="easy-step-fallback">ℹ️ 이 단계는 AI 해설을 받지 못해 원본 문장을 그대로 보여주고 있어요</div>` : ''}
            ${s.tip ? `<div class="easy-step-tip">💡 ${s.tip}</div>` : ''}
            ${s.duration_min > 0 ? `
              <div class="easy-step-timer" data-minutes="${s.duration_min}" data-idx="${i}">
                <span class="timer-badge">⏱ 약 ${s.duration_min}분 소요</span>
                <button type="button" class="timer-btn" data-action="start">타이머 시작</button>
                <span class="timer-display" style="display:none">00:00</span>
              </div>` : ''}
          </div>
        </li>`).join('')}
    </ol>`;

  container.querySelectorAll('.easy-step-timer').forEach(el => {
    const minutes = parseFloat(el.dataset.minutes) || 1;
    const btn     = el.querySelector('.timer-btn');
    const display = el.querySelector('.timer-display');
    let remaining = Math.round(minutes * 60);
    let intervalId = null;

    const render = () => {
      const m = Math.floor(remaining / 60).toString().padStart(2, '0');
      const s = (remaining % 60).toString().padStart(2, '0');
      display.textContent = `${m}:${s}`;
    };

    btn.addEventListener('click', () => {
      if (btn.dataset.action === 'start') {
        display.style.display = '';
        render();
        btn.textContent = '일시정지';
        btn.dataset.action = 'pause';
        intervalId = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(intervalId);
            _activeTimers = _activeTimers.filter(id => id !== intervalId);
            display.textContent = '완료! ⏰';
            el.classList.add('timer-done');
            btn.textContent = '다시 시작';
            btn.dataset.action = 'reset';
            return;
          }
          render();
        }, 1000);
        _activeTimers.push(intervalId);
      } else if (btn.dataset.action === 'pause') {
        clearInterval(intervalId);
        _activeTimers = _activeTimers.filter(id => id !== intervalId);
        btn.textContent = '계속하기';
        btn.dataset.action = 'resume';
      } else if (btn.dataset.action === 'resume') {
        btn.textContent = '일시정지';
        btn.dataset.action = 'pause';
        intervalId = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(intervalId);
            _activeTimers = _activeTimers.filter(id => id !== intervalId);
            display.textContent = '완료! ⏰';
            el.classList.add('timer-done');
            btn.textContent = '다시 시작';
            btn.dataset.action = 'reset';
            return;
          }
          render();
        }, 1000);
        _activeTimers.push(intervalId);
      } else {
        remaining = Math.round(minutes * 60);
        el.classList.remove('timer-done');
        render();
        btn.textContent = '일시정지';
        btn.dataset.action = 'pause';
        intervalId = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(intervalId);
            _activeTimers = _activeTimers.filter(id => id !== intervalId);
            display.textContent = '완료! ⏰';
            el.classList.add('timer-done');
            btn.textContent = '다시 시작';
            btn.dataset.action = 'reset';
            return;
          }
          render();
        }, 1000);
        _activeTimers.push(intervalId);
      }
    });
  });
}

/* ── 추천 분석 섹션 렌더링 ─────────────────────── */
function _renderRecommendSection(detail, scores, score, reason, mode) {
  const nt     = detail?.nutrition_total ?? {};
  const mLabel = MODE_LABEL[mode] || mode || '기본';
  const mCls   = MODE_CLS[mode]   || 'badge-mode-균형';

  const factors = [
    {
      key:   'price',
      label: '가격',
      icon:  '💰',
      val:   (() => { const lv = _priceLevel(detail?.price_total_krw); return lv ? lv.label : '정보 없음'; })(),
      ok:    (detail?.price_total_krw ?? 0) > 0,
      color: '#15803d',
      bg:    '#dcfce7',
    },
    {
      key:   'calorie',
      label: '칼로리',
      icon:  '🔥',
      val:   `${Math.round(nt.energy_kcal ?? 0)} kcal`,
      ok:    (nt.energy_kcal ?? 0) > 0,
      color: '#c2410c',
      bg:    '#fff1ec',
    },
    {
      key:   'protein',
      label: '단백질',
      icon:  '💪',
      val:   `${_f1(nt.protein_g)} g`,
      ok:    (nt.protein_g ?? 0) > 0,
      color: '#7c3aed',
      bg:    '#f5f3ff',
    },
    {
      key:   'sodium',
      label: '나트륨',
      icon:  '🧂',
      val:   `${Math.round(nt.sodium_mg ?? 0)} mg`,
      ok:    (nt.sodium_mg ?? 0) > 0,
      color: '#0891b2',
      bg:    '#ecfeff',
    },
    {
      key:   'time',
      label: '조리시간',
      icon:  '⏱',
      val:   detail?.cook_time_min ? `${detail.cook_time_min}분` : '정보 없음',
      ok:    detail?.cook_time_min != null,
      color: '#0369a1',
      bg:    '#f0f9ff',
    },
  ];

  return `
    <div class="recommend-section">
      <div class="recommend-header">
        <div class="recommend-title-row">
          <span class="section-label" style="margin:0">추천 분석</span>
          <span class="result-mode-badge ${mCls}">${mLabel} 기준</span>
        </div>
        ${reason ? `
        <div class="reason-highlight">
          <span class="reason-icon">💡</span>
          <span class="reason-text">${reason}</span>
        </div>` : ''}
      </div>

      <div class="factor-grid">
        ${factors.map(f => {
          const pct  = Math.round((scores[f.key] ?? 0) * 100);
          const okCls = f.ok ? '' : 'factor-card-warn';
          return `
          <div class="factor-card ${okCls}">
            <div class="factor-top">
              <span class="factor-icon">${f.icon}</span>
              <span class="factor-label">${f.label}</span>
            </div>
            <div class="factor-bar-bg">
              <div class="factor-bar-fill"
                   data-w="${pct}%"
                   style="width:0%;background:${f.color}"></div>
            </div>
            <div class="factor-val">${f.val}</div>
          </div>`;
        }).join('')}
      </div>

      ${_renderAiInfo(detail)}
    </div>`;
}

function _renderAiInfo(detail) {
  const dietSim = detail?.diet_similarity;
  const dietReason = detail?.diet_similarity_reason;

  const parts = [];
  if (dietSim != null && dietSim > 0 && dietReason) {
    const pct = Math.round(dietSim * 100);
    parts.push(`<span class="ai-info-chip">🍽 최근 식단과 유사도 ${pct}% — ${dietReason}</span>`);
  }
  if (parts.length === 0) return '';
  return `<div class="ai-info-row">${parts.join('')}</div>`;
}

/* ── 공통 헬퍼 ───────────────────────────────── */

function _foodEmoji(r) {
  const name = (r.name || '') + ' ' + (r.category || '') + ' ' + (r.method || '');
  const map = [
    [/밥|덮밥|볶음밥|비빔|죽|오므라이스/, '🍚'],
    [/찌개|국|탕/, '🍲'],
    [/닭|치킨/, '🍗'],
    [/고기|불고기|제육|소고기|돼지/, '🥩'],
    [/계란|달걀/, '🍳'],
    [/샐러드|브로콜리|야채|채소/, '🥗'],
    [/두부/, '🧈'],
    [/김치/, '🥬'],
    [/면|국수|파스타|잡채/, '🍜'],
    [/생선|회|참치|해물|해산물|바지락/, '🐟'],
  ];
  for (const [re, emoji] of map) {
    if (re.test(name)) return emoji;
  }
  if (/국|탕|찌개/.test(r.category || '')) return '🍲';
  if (/밥/.test(r.category || '')) return '🍚';
  if (/반찬/.test(r.category || '')) return '🥘';
  return '🍽️';
}

/* [FIX] 영양 수치에 '1일 영양성분 기준치 대비 %'를 함께 보여준다.
   budgetbytes 등 해외 레시피 서비스의 표준 방식이다.
       칼로리 328kcal (16%)   단백질 19g (38%)   나트륨 676mg (29%)
   '328kcal'만 보면 많은지 적은지 감이 안 오지만, '하루 치의 16%'는
   바로 읽힌다. 특히 나트륨은 저염 추천의 근거이므로 비율 표시가 중요하다.

   기준값은 식약처 고시 「1일 영양성분 기준치」(2,000kcal 기준)를 따른다.
   식품 영양표시에 쓰이는 공식 수치라 임의로 정한 값이 아니다.            */
const DAILY_VALUE = {
  '열량':     2000,   // kcal
  '탄수화물':  324,   // g
  '당류':      100,   // g
  '단백질':     55,   // g
  '지방':       54,   // g
  '나트륨':   2000,   // mg
  '식이섬유':   25,   // g
  '칼슘':      700,   // mg
};

function _nutriCard(label, value, unit) {
  const dv  = DAILY_VALUE[label];
  const num = parseFloat(value);
  let pct = '';
  if (dv && Number.isFinite(num) && num > 0) {
    const p = Math.round((num / dv) * 100);
    // 나트륨은 과다 섭취가 문제라 30% 이상이면 눈에 띄게 표시한다
    const warn = (label === '나트륨' && p >= 30) ? ' nutri-pct-warn' : '';
    pct = `<div class="nutri-pct${warn}">1일 ${p}%</div>`;
  }
  return `
    <div class="nutri-card">
      <div class="nutri-label">${label}</div>
      <div class="nutri-value">${value}<span class="nutri-unit">${unit}</span></div>
      ${pct}
    </div>`;
}

function _f1(v) {
  return v != null && v !== '' ? parseFloat(v).toFixed(1) : '0.0';
}

/* 식약처 원문 재료명이 일반 사용자에게 생소하거나 잘려 있는 경우의 표시용 사전.
   데이터 자체는 건드리지 않고 화면에 보여줄 때만 바꿔준다. */
const DISPLAY_ALIAS = {
  '토마토홀':   '홀토마토 (토마토 통조림)',
  '홀토마토':   '홀토마토 (토마토 통조림)',
  '홀그레인':   '홀그레인 머스터드',
  '홀스레디쉬': '호스래디시 (서양 고추냉이)',
  '날콩가루':   '생콩가루',
  '우민찌':     '소고기 다짐육',
  '돈민찌':     '돼지고기 다짐육',
  '패주':       '관자 (가리비 관자)',
  '청경채':     '청경채',
};

function _ingName(raw) {
  let s = (raw ?? '').trim();
  s = s.replace(/^[^:：\d]*[:：]\s*/, '');
  s = s.replace(/^(주재료|부재료|양념|소스|재료)\s*[:：]?\s*/, '');
  s = s.replace(/\s*\d+(?:\.\d+)?\s*(?:kg|g|mg|ml|l)\b/gi, '');
  s = s.replace(/\s*\(.*?\)/g, '');
  // [FIX] 분수(1/2개)·누락 단위(알·톨·줄기·가닥·캔·포·공기 등)가 재료명에 남아
  // '아몬드 1알', '감자 1/2개'처럼 표시되던 문제.
  s = s.replace(
    /\s*\d+(?:[./+]\d+)?\s*(?:큰술|작은술|스푼|컵|공기|개|알|마리|뿌리|줄기|가닥|톨|장|쪽|모|토막|단|송이|봉지|봉|캔|포|팩|포기|줌|조각|꼬집|방울)/g, '');
  // [FIX] '치커리 약간'처럼 분량 표기가 재료명에 그대로 남던 문제.
  s = s.replace(/\s*(약간|적당량|조금|소량|기호에\s*따라|넉넉히)\s*$/g, '');
  s = s.replace(/\s*[:：]\s*.*/, '');
  s = s.trim();
  for (const [key, label] of Object.entries(DISPLAY_ALIAS)) {
    if (s === key || s.replace(/\s+/g, '') === key) return label;
  }
  return s;
}

/* [FIX] 사용량 표기 — 조리 단위 우선, 떨어지지 않으면 그램
   참고 사이트(우리의식탁·만개의레시피·새미네부엌·이밥차)를 직접 확인한 결과,
   한 레시피 안에서도 표기를 섞어 쓴다.
       양파 1/2개 · 비엔나소세지 300g · 참기름 1T · 후춧가루 약간
   즉 '전부 g' 또는 '전부 조리 단위'로 통일하는 곳은 없고,
   **조리 단위로 깔끔하게 떨어지면 조리 단위, 아니면 그램**을 쓴다.

   식약처 데이터로 검증해도 같은 결론이다. 1인분 표준 분량이라 양이 작아
   전부 환산하면 '김치 0.02포기', '두부 0.03모'처럼 쓸모없는 값이 된다.

   그램 → 조리 단위 환산은 **백엔드 recipe_service.to_cooking_unit()** 이
   담당하고(ingredients[].amount_display), 여기서는 표시만 한다.
   환산표를 프런트에 따로 두면 영양·가격 계산에 쓰는 값과 어긋나기 때문이다.

   우선순위
     ① 원문에 조리 단위가 있으면 그대로   '연두부 3/4모' → 3/4모
     ② 원문이 그램뿐이면 환산값 사용      '마늘 3g'     → 2/3쪽
     ③ 환산이 깔끔하지 않으면 그램        '김치 40g'    → 40g
     ④ '약간·적당량'은 그대로 (내부 환산값 2g은 임의 가정이라 숨김)
   선택되지 않은 값은 title(툴팁)로 남겨 정보를 잃지 않는다.               */
const _MEASURE_UNITS =
  '큰술|작은술|스푼|컵|공기|개|알|모|장|쪽|톨|줄기|가닥|뿌리|대|봉지|봉|캔|포|팩|' +
  '포기|단|마리|토막|줌|조각|송이|꼬집|방울';

function _isDimension(t) {
  return /\d\s*[×xX*]\s*\d/.test(t) || /\d\s*(cm|mm|센티|밀리)/i.test(t);
}
function _isMeasure(t) {
  return new RegExp('^\\d+(?:[./+]\\d+)?\\s*(?:' + _MEASURE_UNITS + ')').test(t);
}
function _hasWeight(t) {
  return /\d\s*(g|kg|ml|mL|L|리터|cc)\b/i.test(t);
}
/* 단위별 분모 상한 — 백엔드 _UNIT_MAX_DENOM과 같은 기준.
   '쪼갤 수 있는 정도'가 단위마다 다르다는 데서 나온 값이다. */
const _DENOM_LIMIT = {
  '큰술':4,'작은술':4,'스푼':4,'컵':4, '모':4,'개':4,'포기':4,'통':4,'공기':4,
  '쪽':3,'톨':3,'알':3,
  '마리':2,'장':2,'줄기':2,'가닥':2,'송이':2,'봉지':2,'캔':2,'포':2,'팩':2,
  '토막':2,'단':2,'뿌리':2,'대':2,'조각':2, '줌':2,'꼬집':2,'방울':2,
};

function _withinDenomLimit(txt) {
  if (!txt) return false;
  const m = txt.match(/^(\d+)\s*\/\s*(\d+)\s*(.+)$/);   // '1/20모'
  if (!m) return true;                                     // 분수가 아니면 통과
  const denom = parseInt(m[2], 10);
  const unit  = m[3].trim();
  return denom <= (_DENOM_LIMIT[unit] ?? 4);
}

function _fmtGram(g) {
  if (g == null || g <= 0) return '-';
  return (g < 10 ? Math.round(g * 10) / 10 : Math.round(g)) + 'g';
}

function _ingUnit(raw, amount_g, display) {
  const s = (raw ?? '').trim();

  const vague = s.match(/(약간|적당량|조금|소량|기호에\s*따라)/);
  if (vague) return vague[1];

  const gram = _fmtGram(amount_g);
  const m = s.match(/[\d½⅓⅔¼¾].*$/);

  let amt = m ? m[0].trim().replace(/\s+/g, ' ') : '';
  if (amt) {   // '주꾸미(40g)'처럼 닫는 괄호만 남는 경우 정리
    let opened = (amt.match(/\(/g) || []).length;
    let closed = (amt.match(/\)/g) || []).length;
    while (closed > opened) { amt = amt.replace(/\)(?=[^)]*$)/, '').trim(); closed--; }
  }

  let main = amt, paren = '', note = '';
  const pm = amt.match(/^(.*?)\s*\(([^)]*)\)\s*$/);
  if (pm) { main = pm[1].trim(); paren = pm[2].trim(); }
  if (paren && _isDimension(paren)) { note = `${paren}로 손질`; paren = ''; }

  // [FIX] 물처럼 부피로 써야 하는 재료는 원문보다 환산값을 우선한다.
  // 식약처 원문이 '물 300ml(1½컵)'이라 그대로 쓰면 '1/3작은술'처럼
  // 엉뚱한 단위가 나왔다. 백엔드가 ml·L·약간으로 정리해 보내준다.
  // ml·L은 물 전용 환산값이고, '약간'은 1g 미만이거나 물 10ml 미만일 때다.
  // 둘 다 원문 표기보다 우선한다.
  const isVolume = /\d\s*(?:ml|L)$/.test(display || '') || display === '약간';

  // [FIX] 원문을 우선하되, 분모가 너무 큰 분수는 쓰지 않는다.
  // 식약처는 1인분 분량이라 '두부 1/20모', '당근 1/10개'처럼 적는데,
  // 실제 레시피 서비스는 분모 2~4를 쓴다.
  //   만개의레시피 1/2작은술 · 우리의식탁 ½개·¼ · 새미네부엌 1/5대
  // 상한을 넘으면 원문을 버리고 그램(또는 환산값)을 쓴다.
  const fromRaw = _isMeasure(main) ? main : (_isMeasure(paren) ? paren : '');
  const usableRaw = _withinDenomLimit(fromRaw) ? fromRaw : '';

  // ① 부피 지정값  ② 원문의 조리 단위  ③ 백엔드 환산값  ④ 그램
  const text = isVolume ? display : (usableRaw || display || gram);

  const tips = [];
  if (note) tips.push(note);
  if (text !== gram && gram !== '-') tips.push(`약 ${gram}`);
  return tips.length ? `<span title="${tips.join(' · ')}">${text}</span>` : text;
}

/* 재료를 [재료]/[양념] 같은 원문 섹션별로 묶는다.
   섹션이 하나뿐이거나 없으면 머리글을 만들지 않는다(불필요한 줄 방지). */
function _groupIngredients(list) {
  const order = [];
  const map = new Map();
  for (const ing of list) {
    const sec = (ing.section ?? '').trim();
    if (!map.has(sec)) { map.set(sec, []); order.push(sec); }
    map.get(sec).push(ing);
  }
  if (order.length <= 1) return [['', list]];
  return order.map(sec => [sec, map.get(sec)]);
}

function _cell(v, matched, digits = 1) {
  if (!matched) return '<span class="nodata-dash">-</span>';
  return parseFloat(v ?? 0).toFixed(digits);
}

function _priceLevel(krw) {
  const p = Math.round(krw || 0);
  if (p <= 0) return null;
  let label, cls, dots;
  if (p < 3000)        { label = '낮음'; cls = 'price-low';  dots = '💰'; }
  else if (p < 10000)  { label = '보통'; cls = 'price-mid';  dots = '💰💰'; }
  else                 { label = '높음'; cls = 'price-high'; dots = '💰💰💰'; }
  const rounded = Math.round(p / 100) * 100;
  return { label, cls, dots, approx: rounded.toLocaleString() };
}

function _priceBadge(krw) {
  const lv = _priceLevel(krw);
  if (!lv) return '';
  const id = 'pb_' + Math.random().toString(36).slice(2, 7);
  return `<span class="price-badge ${lv.cls}" style="cursor:pointer"
    onclick="(function(el){
      var s=el.dataset.shown;
      el.textContent = s ? '${lv.dots} ${lv.label}' : '${lv.dots} 약 ${lv.approx}원';
      el.dataset.shown = s ? '' : '1';
    })(this)"
    title="클릭하면 금액을 볼 수 있어요"
  >${lv.dots} ${lv.label}</span>`;
}

function _priceCard(krw) {
  const lv = _priceLevel(krw);
  if (!lv) {
    return `<div class="nutri-card"><div class="nutri-label">재료비</div>`
         + `<div class="nutri-value"><span class="nodata-dash">—</span></div></div>`;
  }

  return `<div class="nutri-card" style="cursor:pointer"
      onclick="(function(el){
        var v=el.querySelector('.price-toggle-val');
        var s=el.dataset.shown;
        v.textContent = s ? '${lv.label}' : '약 ${lv.approx}원';
        el.dataset.shown = s ? '' : '1';
      })(this)"
      title="클릭하면 금액을 볼 수 있어요">
      <div class="nutri-label">재료비 <span style="font-size:0.65rem;color:#aaa;">👆</span></div>
      <div class="nutri-value ${lv.cls} price-toggle-val" style="font-size:1rem">${lv.label}</div>
    </div>`;
}