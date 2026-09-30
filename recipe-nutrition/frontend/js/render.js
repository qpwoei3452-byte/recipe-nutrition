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
export function renderRecipeList(recipes, container, onSelect, mode = '기본') {
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
    const rank   = idx + 1;
    const score  = r.score ?? null;
    const reason = r.reason ?? '';
    // 다양성 패널티로 순위가 조정된 항목 (이전에 먹었거나 이미 추천된 것과 유사)
    const divSim = r.diversity_sim ?? r.similarity_score ?? 0;
    const divNote = divSim >= 0.5
      ? `<div class="card-diversity-note">🔀 비슷한 메뉴가 있어 순위 조정됨</div>`
      : '';

    const card = document.createElement('div');
    card.className = 'recipe-card';

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
      </div>`;

    card.addEventListener('click', () => {
      document.querySelectorAll('.recipe-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      onSelect(r);
    });

    grid.appendChild(card);
  });

  container.appendChild(grid);
}

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
          <h2 class="detail-title">${detail?.name ?? ''}</h2>
          <div class="detail-meta">
            <span class="meta-badge">${detail?.category ?? ''}</span>
            <span class="meta-badge">${detail?.method ?? ''}</span>
            <span class="source-chip">출처: ${detail?.source ?? '식약처'}</span>
          </div>
        </div>

      </div>

      <!-- ② 추천 분석 섹션 (score 있을 때만) -->
      ${scores ? _renderRecommendSection(detail, scores, score, reason, mode) : ''}

      <!-- ③ 영양 요약 -->
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
        <div class="section-label">재료 및 상세 영양 정보</div>
        <div class="table-wrap">
          <table class="ing-table">
            <thead>
              <tr>
                <th>재료명</th>
                <th>사용량(g)</th>
                <th>단백질(g)</th>
                <th>지방(g)</th>
                <th>탄수화물(g)</th>
                <th>가격(원)</th>
              </tr>
            </thead>
            <tbody>
              ${ingredients.map(ing => {
                const nMatched = !!(ing.nutrition_matched_name);  // 영양 사전 매칭 성공 여부
                const pMatched = !!(ing.price_matched_name);      // 가격 사전 매칭 성공 여부
                const hasData = nMatched || pMatched;
                return `
                <tr${hasData ? '' : ' class="ing-nodata"'}>
                  <td>${_ingName(ing.raw_name ?? ing.standard_nm)}</td>
                  <td>${_ingUnit(ing.raw_name, ing.amount_g)}</td>
                  <td>${_cell(ing.protein_g, nMatched)}</td>
                  <td>${_cell(ing.fat_g, nMatched)}</td>
                  <td>${_cell(ing.carb_g, nMatched)}</td>
                  <td>${pMatched ? Math.round(ing.price_krw ?? 0).toLocaleString() : '0'}</td>
                </tr>`;
              }).join('')}
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
          ${steps.map(s => `<li>${(s?.desc ?? '').replace(/^\d+\.\s*/, '')}</li>`).join('')}
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
}

/* ── "쉽게 보기(AI)" 토글 배선 ─────────────────────
   원본은 항상 그대로 유지, 버튼으로 원본↔AI 해설 전환.
   AI 해설은 레시피당 한 번만 불러오고 클라이언트 메모리에도 캐시.
   [FIX] AI 호출 실패 시: 원본 조리 순서로 자동 복귀 + 일시적 안내 배너 표시 */
function _wireStepsToggle(container, detail) {
  const recipeId    = detail?.id ?? '';
  const recipeName  = detail?.name ?? '';
  const originalBox = container.querySelector('#steps-original');
  const easyBox     = container.querySelector('#steps-easy');
  const btns        = container.querySelectorAll('.steps-toggle-btn');
  if (!originalBox || !easyBox || btns.length === 0) return;

  /* [FIX] 원본 보기로 되돌리는 헬퍼 — 원본 표시 + 버튼 상태 초기화 */
  function _revertToOriginal() {
    easyBox.style.display   = 'none';
    originalBox.style.display = '';
    btns.forEach(b => b.classList.remove('active'));
    const originalBtn = container.querySelector('.steps-toggle-btn[data-mode="original"]');
    if (originalBtn) originalBtn.classList.add('active');
  }

  /* [FIX] 일시적 오류 안내 배너 — 노란색, 재시도 버튼, 8초 자동 사라짐 */
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

    /* 조리 순서 섹션 바로 위에 삽입 */
    const stepsSection = container.querySelector('.steps-section');
    if (stepsSection) {
      stepsSection.insertBefore(notice, stepsSection.firstChild);
    }

    /* 재시도 버튼 — 클릭 시 배너 제거 후 쉽게 보기 버튼 다시 클릭 */
    notice.querySelector('#easy-steps-retry')?.addEventListener('click', () => {
      notice.remove();
      const easyBtn = container.querySelector('.steps-toggle-btn[data-mode="easy"]');
      if (easyBtn) easyBtn.click();
    });

    /* 8초 후 자동 제거 */
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

      // "쉽게 보기" 선택
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
        const easySteps = Array.isArray(res?.steps) ? res.steps : [];
        if (easySteps.length === 0) {
          // [FIX] 빈 결과: 원본 복귀 + 안내 배너
          _revertToOriginal();
          _showTransientNotice(recipeId, recipeName);
          return;
        }
        _easyStepsMemCache[recipeId] = easySteps;
        _renderEasySteps(easyBox, easySteps);
      } catch (e) {
        console.error('[쉽게 보기 로드 실패]', e);
        // [FIX] 예외 발생: 원본 복귀 + 안내 배너
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
            <p class="easy-step-text">${s.detail ?? s.original ?? ''}</p>
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
        // reset
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

/* AI 분석 부가 정보: 식단 유사도(설명용, MMR 다양성과 별개)
   (조리시간 출처는 내부 정보라 화면에 표시하지 않음) */
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

/* 이미지가 없을 때 음식 종류에 맞는 이모지를 골라줌 */
function _foodEmoji(r) {
  const name = (r.name || '') + ' ' + (r.category || '') + ' ' + (r.method || '');
  // 음식명 키워드 우선 매칭
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
  // 카테고리 기본값
  if (/국|탕|찌개/.test(r.category || '')) return '🍲';
  if (/밥/.test(r.category || '')) return '🍚';
  if (/반찬/.test(r.category || '')) return '🥘';
  return '🍽️';
}

function _nutriCard(label, value, unit) {
  return `
    <div class="nutri-card">
      <div class="nutri-label">${label}</div>
      <div class="nutri-value">${value}<span class="nutri-unit">${unit}</span></div>
    </div>`;
}

function _f1(v) {
  return v != null && v !== '' ? parseFloat(v).toFixed(1) : '0.0';
}

/* 매칭 성공 여부로 0과 '없음'을 구분.
   - matched=true  → 값을 그대로 표시 (0이어도 "0.0". 예: 물의 단백질)
   - matched=false → 사전에 없어 모르는 값이므로 대시(—) */

/* 재료명에서 순수 이름만 추출 (g수·단위·섹션명 제거) */
function _ingName(raw) {
  let s = (raw ?? '').trim();
  s = s.replace(/^[^:：\d]*[:：]\s*/, '');
  // [FIX] "재료 굴"처럼 앞에 붙는 분류어(재료/부재료/주재료/양념/소스)가
  // 안 지워지고 그대로 표시되던 문제 — 단위 제거 전에 먼저 제거.
  s = s.replace(/^(주재료|부재료|양념|소스|재료)\s*[:：]?\s*/, '');
  s = s.replace(/\s*\d+(?:\.\d+)?\s*(?:kg|g|mg|ml|l)\b/gi, '');
  s = s.replace(/\s*\(.*?\)/g, '');
  s = s.replace(/\s*\d+(?:\.\d+)?\s*(?:큰술|작은술|컵|개|마리|뿌리|장|쪽|모|토막|단|송이|봉지)/g, '');
  s = s.replace(/\s*[:：]\s*.*/, '');
  return s.trim();
}

/* 사용량에 표시할 단위 힌트 추출 (괄호 안 내용: 1/2개, 2큰술 등) */
function _ingUnit(raw, amount_g) {
  const hint = (raw ?? '').match(/\(([^)]+)\)/);
  const base = amount_g != null ? _f1(amount_g) : '';
  if (!hint) return base;
  const h = hint[1].trim();
  if (/^[\d\.]+\s*(?:cm|mm|×|x)/i.test(h)) return base;
  if (/^\d+(?:\.\d+)?$/.test(h)) return base;
  return `${base} (${h})`;
}

function _cell(v, matched) {
  if (!matched) return '<span style="color:var(--color-text-secondary);">0.0</span>';
  return parseFloat(v ?? 0).toFixed(1);
}

/* 재료비를 등급(낮음/보통/높음)으로 변환.
   정확한 숫자는 "공격의 여지"가 있어(교수님 피드백), 등급을 메인으로 보여주고
   숫자는 "약 ○○원" 형태로 참고용으로만 작게 표기한다.
   기준: 1인분 재료비 절대값 (DB가 바뀌어도 일관) */
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

/* 카드/요약용 짧은 가격 뱃지 HTML */
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

/* 상세 영양요약용 가격 카드 (등급 + 참고 숫자) */
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