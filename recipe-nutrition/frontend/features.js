'use strict';

const API = {
  async get(url) {
    const r = await fetch(url); if (!r.ok) throw new Error(r.statusText);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method:'DELETE' });
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
  },
};

function ls(key, val) {
  if (val === undefined) {
    try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
  }
  try { localStorage.setItem(key, JSON.stringify(val)); } catch {}
}

// ────────────────────────────────────────────────────────────
// 1. 설정 자동 저장 / 복원
// ────────────────────────────────────────────────────────────
const Settings = (() => {
  const SLIDER_IDS  = ['w_price','w_protein','w_calorie','w_sodium','w_time'];
  const KEY_SLIDERS = 'rec_sliders';
  const KEY_ALLERGY = 'rec_allergy';

  function saveSliders() {
    const data = {};
    SLIDER_IDS.forEach(id => {
      const el = document.getElementById(id) || document.querySelector(`[name="${id}"]`);
      if (el) data[id] = el.value;
    });
    if (Object.keys(data).length) ls(KEY_SLIDERS, data);
  }

  function restoreSliders() {
    const data = ls(KEY_SLIDERS);
    if (!data) return;
    SLIDER_IDS.forEach(id => {
      const el = document.getElementById(id) || document.querySelector(`[name="${id}"]`);
      if (el && data[id] !== undefined) {
        el.value = data[id];
        el.dispatchEvent(new Event('input'));
      }
    });
  }

  function saveAllergy() {
    const checked = [];
    document.querySelectorAll('input[type=checkbox][name^="allergen"],input[type=checkbox][data-allergen]')
      .forEach(cb => { if (cb.checked) checked.push(cb.value || cb.dataset.allergen); });
    ls(KEY_ALLERGY, checked);
  }

  function restoreAllergy() {
    const saved = ls(KEY_ALLERGY);
    if (!saved || !saved.length) return;
    document.querySelectorAll('input[type=checkbox][name^="allergen"],input[type=checkbox][data-allergen]')
      .forEach(cb => {
        const val = cb.value || cb.dataset.allergen;
        if (saved.includes(val)) cb.checked = true;
      });
  }

  function init() {
    restoreSliders();
    restoreAllergy();
    document.addEventListener('change', e => {
      const t = e.target;
      if (SLIDER_IDS.some(id => t.id === id || t.name === id)) saveSliders();
      if (t.type === 'checkbox' && (t.name?.startsWith('allergen') || t.dataset.allergen)) saveAllergy();
    });
    document.addEventListener('input', e => {
      const t = e.target;
      if (SLIDER_IDS.some(id => t.id === id || t.name === id)) saveSliders();
    });
  }

  return { init };
})();

// ────────────────────────────────────────────────────────────
// 6. 시간대별 자동 가중치 (토글 방식)
// ────────────────────────────────────────────────────────────
const TimeSlot = (() => {
  const SLOT_INFO = {
    '아침': { emoji:'🌅', label:'아침 추천 모드', desc:'빠르고 가벼운 아침 식사 위주로 추천합니다.' },
    '점심': { emoji:'☀️', label:'점심 추천 모드', desc:'영양 균형 잡힌 점심 메뉴를 추천합니다.' },
    '저녁': { emoji:'🌙', label:'저녁 추천 모드', desc:'든든하고 영양 풍부한 저녁 식사를 추천합니다.' },
    '야식': { emoji:'🌃', label:'야식 추천 모드', desc:'칼로리 낮은 야식 메뉴를 추천합니다.' },
  };
  const LS_KEY = 'time_slot_enabled';
  let currentSlot = null;
  let enabled = true;

  function detectSlot() {
    const h = new Date().getHours();
    if (h >= 6  && h < 11) return '아침';
    if (h >= 11 && h < 18) return '점심';
    if (h >= 18 && h < 22) return '저녁';
    return '야식';
  }

  function renderUI() {
    document.getElementById('time-slot-wrap')?.remove();
    const wrap = document.createElement('div');
    wrap.id = 'time-slot-wrap';
    wrap.style.cssText = 'margin:10px 0';

    if (enabled) {
      const info = SLOT_INFO[currentSlot] || {};
      wrap.innerHTML = `
        <div style="background:linear-gradient(90deg,#667eea,#764ba2);color:#fff;padding:10px 18px;border-radius:10px;display:flex;align-items:center;gap:10px;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,0.15)">
          <span style="font-size:22px">${info.emoji||'🕐'}</span>
          <div style="flex:1">
            <div style="font-weight:700">${info.label||''}</div>
            <div style="opacity:0.9;font-size:12px">${info.desc||''}</div>
          </div>
          <button id="ts-toggle" style="background:rgba(255,255,255,0.25);border:1px solid rgba(255,255,255,0.6);color:#fff;padding:4px 12px;border-radius:12px;cursor:pointer;font-size:12px;white-space:nowrap">⏸ 끄기</button>
        </div>`;
    } else {
      wrap.innerHTML = `
        <div style="background:#f0f0f0;border-radius:10px;padding:8px 16px;display:flex;align-items:center;gap:8px;font-size:13px;color:#888">
          <span>🕐 시간대 자동 추천이 꺼져 있어요</span>
          <button id="ts-toggle" style="background:#667eea;border:none;color:#fff;padding:4px 12px;border-radius:12px;cursor:pointer;font-size:12px;white-space:nowrap">▶ 켜기</button>
        </div>`;
    }

    const form = document.querySelector('form') || document.querySelector('.search-box') || document.body.firstElementChild;
    form.parentNode.insertBefore(wrap, form);
    document.getElementById('ts-toggle')?.addEventListener('click', () => {
      enabled = !enabled;
      ls(LS_KEY, enabled);
      renderUI();
    });
  }

  function getSlot() { return enabled ? currentSlot : null; }

  function init() {
    const saved = ls(LS_KEY);
    enabled = (saved === null) ? false : !!saved;
    currentSlot = detectSlot();
    renderUI();
  }

  return { init, getSlot };
})();

// ────────────────────────────────────────────────────────────
// 3. 냉장고 재료 입력 UI
// ────────────────────────────────────────────────────────────
const Fridge = (() => {
  const LS_KEY = 'fridge_ingredients';
  let items = [];

  function load() { items = ls(LS_KEY) || []; }
  function save() { ls(LS_KEY, items); }

  function add(ingredient) {
    if (!ingredient.trim() || items.includes(ingredient.trim())) return;
    items.push(ingredient.trim()); save();
  }
  function remove(ingredient) { items = items.filter(i => i !== ingredient); save(); }

  function renderTags() {
    const container = document.getElementById('fridge-tags');
    if (!container) return;
    container.innerHTML = items.length
      ? items.map(item => `
          <span style="background:#2c7be5;color:#fff;padding:4px 10px;border-radius:20px;font-size:13px;display:inline-flex;align-items:center;gap:5px;margin:2px">
            ${item}
            <button onclick="window._fridgeRemove('${item}')" style="background:none;border:none;color:#fff;cursor:pointer;font-size:15px;line-height:1;padding:0">×</button>
          </span>`).join('')
      : '<span style="color:#aaa;font-size:13px">재료를 추가하면 해당 재료가 들어간 레시피를 우선 추천해요</span>';
  }

  function renderPanel() {
    if (document.getElementById('fridge-panel')) return;
    const panel = document.createElement('div');
    panel.id = 'fridge-panel';
    panel.style.cssText = 'border:2px solid #e8f4f8;border-radius:12px;padding:14px 16px;margin:12px 0;background:#f7fbff';
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <span style="font-size:20px">🧊</span>
        <strong style="color:#2c7be5">냉장고 재료 기반 추천</strong>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <input id="fridge-input" placeholder="메인 재료명 입력 (예: 두부, 계란, 감자)"
          style="flex:1;padding:7px 12px;border:1px solid #cce0f5;border-radius:8px;font-size:14px"/>
        <button id="fridge-add-btn"
          style="padding:7px 14px;background:#2c7be5;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px">추가</button>
      </div>
      <div id="fridge-tags"></div>
      <label style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:13px;color:#555;cursor:pointer">
        <input type="checkbox" id="fridge-only-check" style="width:15px;height:15px">
        냉장고 재료가 있는 레시피만 보기
      </label>`;
    const searchBox = document.querySelector('.search-box') || document.querySelector('form');
    if (searchBox) searchBox.parentNode.insertBefore(panel, searchBox.nextSibling);
    else document.body.appendChild(panel);
    renderTags();
    document.getElementById('fridge-add-btn').addEventListener('click', () => {
      const val = document.getElementById('fridge-input').value.trim();
      if (val) { add(val); document.getElementById('fridge-input').value = ''; renderTags(); }
    });
    document.getElementById('fridge-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') { document.getElementById('fridge-add-btn').click(); e.preventDefault(); }
    });
  }

  window._fridgeRemove = (ingredient) => { remove(ingredient); renderTags(); };
  function getItems() { return [...items]; }
  function isFridgeOnly() { return document.getElementById('fridge-only-check')?.checked || false; }
  function init() { load(); renderPanel(); }
  return { init, getItems, isFridgeOnly };
})();

// ────────────────────────────────────────────────────────────
// 4. 별점 + 5. 즐겨찾기 — 카드 자동 주입
// ────────────────────────────────────────────────────────────
const RecipeActions = (() => {
  const DONE_ATTR = 'data-rf-done';

  function saveRating(id, name, score) {
    const all = ls('rec_ratings') || {};
    if (score === 0) delete all[id];
    else all[id] = { name, score, rated_at: new Date().toISOString() };
    ls('rec_ratings', all);
    API.post('/api/user/ratings', { recipe_id: id, recipe_name: name, score }).catch(() => {});
  }
  function getRating(id) { return (ls('rec_ratings') || {})[id]?.score || 0; }

  function toggleFavorite(id, name, imageUrl) {
    const all = ls('rec_favorites') || {};
    if (all[id]) {
      delete all[id]; ls('rec_favorites', all);
      API.del(`/api/user/favorites/${encodeURIComponent(id)}`).catch(() => {});
      return false;
    }
    all[id] = { id, name, image_url: imageUrl || '', added_at: new Date().toISOString() };
    ls('rec_favorites', all);
    API.post('/api/user/favorites', { recipe_id: id, name, image_url: imageUrl || '' }).catch(() => {});
    return true;
  }
  function isFavorite(id) { return !!(ls('rec_favorites') || {})[id]; }
  function getAllFavorites() { return Object.values(ls('rec_favorites') || {}); }

  function extractName(card) {
    const selectors = ['h2','h3','h4','h5','strong',
      '.recipe-name','.title',
      '[class*="name"]','[class*="title"]','[class*="recipe"]'];
    for (const sel of selectors) {
      const el = card.querySelector(sel);
      if (el) {
        const txt = el.textContent.trim();
        if (txt.length >= 2 && txt.length <= 40) return txt;
      }
    }
    const leaves = card.querySelectorAll('p,div,span,a,li');
    for (const el of leaves) {
      if (el.children.length > 0) continue;
      const txt = el.textContent.trim();
      if (txt.length >= 2 && txt.length <= 30) return txt;
    }
    const img = card.querySelector('img');
    if (img?.alt && img.alt.length >= 2) return img.alt;
    const firstLine = card.textContent.trim().split('\n')
      .map(s => s.trim()).find(s => s.length >= 2 && s.length <= 40);
    return firstLine || '레시피';
  }

  function injectActions(card) {
    if (!card || card.nodeType !== 1) return;
    if (card.hasAttribute(DONE_ATTR)) return;
    if (card.querySelector('.rf-actions')) return;

    const img = card.querySelector('img');
    if (!img) return;

    const recipeName = card.dataset.recipeName || extractName(card);
    const recipeId = (
      card.dataset.recipeId || card.dataset.id ||
      card.getAttribute('data-recipe-id') || card.getAttribute('data-id') ||
      recipeName
    );
    const imageUrl = img.src || '';

    card.setAttribute(DONE_ATTR, '1');

    const wrapper = document.createElement('div');
    wrapper.className = 'rf-actions';
    wrapper.style.cssText = 'display:flex;align-items:center;gap:10px;margin-top:8px;padding-top:8px;border-top:1px solid #eee;flex-wrap:wrap';

    // ── 별점 ──
    const starWrap = document.createElement('div');
    starWrap.style.cssText = 'display:flex;gap:2px;align-items:center';
    const starLabel = document.createElement('span');
    starLabel.textContent = '평가:';
    starLabel.style.cssText = 'font-size:12px;color:#888;margin-right:2px';
    starWrap.appendChild(starLabel);

    const curRating = getRating(recipeId);
    for (let s = 1; s <= 5; s++) {
      const star = document.createElement('span');
      star.textContent = s <= curRating ? '★' : '☆';
      star.className = 'rf-star';
      star.style.cssText = `font-size:22px;cursor:pointer;color:${s <= curRating ? '#f59e0b' : '#ccc'};transition:color 0.1s;line-height:1`;
      star.addEventListener('mouseenter', () => {
        starWrap.querySelectorAll('.rf-star').forEach((st, i) => {
          st.textContent = i < s ? '★' : '☆';
          st.style.color = i < s ? '#f59e0b' : '#ccc';
        });
      });
      star.addEventListener('mouseleave', () => {
        const cur = getRating(recipeId);
        starWrap.querySelectorAll('.rf-star').forEach((st, i) => {
          st.textContent = i < cur ? '★' : '☆';
          st.style.color = i < cur ? '#f59e0b' : '#ccc';
        });
      });
      star.addEventListener('click', () => {
        const prev = getRating(recipeId);
        const newScore = prev === s ? 0 : s;
        saveRating(recipeId, recipeName, newScore);
        showToast(newScore ? `⭐ ${newScore}점 저장됐어요` : '별점이 취소됐어요');
        starWrap.querySelectorAll('.rf-star').forEach((st, i) => {
          st.textContent = i < newScore ? '★' : '☆';
          st.style.color = i < newScore ? '#f59e0b' : '#ccc';
        });
      });
      starWrap.appendChild(star);
    }
    wrapper.appendChild(starWrap);

    // ── 즐겨찾기 ──
    const favBtn = document.createElement('button');
    const faved = isFavorite(recipeId);
    favBtn.innerHTML = faved ? '❤️ 즐겨찾기됨' : '🤍 즐겨찾기';
    favBtn.style.cssText = `background:${faved?'#fee2e2':'none'};border:1px solid ${faved?'#fca5a5':'#ddd'};border-radius:8px;cursor:pointer;font-size:13px;padding:4px 10px;color:${faved?'#dc2626':'#555'};transition:all 0.2s`;
    favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const added = toggleFavorite(recipeId, recipeName, imageUrl);
      favBtn.innerHTML = added ? '❤️ 즐겨찾기됨' : '🤍 즐겨찾기';
      favBtn.style.background = added ? '#fee2e2' : 'none';
      favBtn.style.borderColor = added ? '#fca5a5' : '#ddd';
      favBtn.style.color = added ? '#dc2626' : '#555';
      favBtn.style.transform = 'scale(1.1)';
      setTimeout(() => favBtn.style.transform = '', 200);
      showToast(added ? '❤️ 즐겨찾기에 추가했어요' : '즐겨찾기에서 제거했어요');
      window.Favorites?.refresh();
    });
    wrapper.appendChild(favBtn);
    card.appendChild(wrapper);
  }

  // ★★★ 핵심 버그 수정: .recipe-card를 직접 찾아서 각각에 injectActions ★★★
  function scanCards() {
    const area = document.getElementById('recipeListArea');
    if (!area) return;
    area.querySelectorAll('.recipe-card').forEach(card => injectActions(card));
  }

  window.featuresScanCards = scanCards;

  function watchCards() {
    scanCards();
    let timer = null;
    new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(scanCards, 300);
    }).observe(document.body, { childList: true, subtree: true });
  }

  function init() { watchCards(); }
  return { init, getAllFavorites, isFavorite };
})();

// ────────────────────────────────────────────────────────────
// 5-B. 즐겨찾기 모달 + 우하단 버튼
// ────────────────────────────────────────────────────────────
const Favorites = (() => {
  let modal = null;

  function open() { if (!modal) create(); refresh(); modal.style.display = 'flex'; }
  function close() { if (modal) modal.style.display = 'none'; }

  function create() {
    modal = document.createElement('div');
    modal.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.5);justify-content:center;align-items:center';
    modal.innerHTML = `
      <div style="background:#fff;border-radius:16px;width:min(480px,92vw);max-height:78vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <div style="padding:16px 20px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center;background:#fff8f8">
          <div>
            <h3 style="margin:0;font-size:18px">❤️ 즐겨찾기</h3>
            <p style="margin:2px 0 0;font-size:12px;color:#999">레시피 카드의 🤍 버튼을 눌러 추가하세요</p>
          </div>
          <button id="fav-close" style="background:none;border:none;font-size:24px;cursor:pointer;color:#888;line-height:1">×</button>
        </div>
        <div id="fav-list" style="overflow-y:auto;padding:12px 16px;flex:1"></div>
      </div>`;
    document.body.appendChild(modal);
    document.getElementById('fav-close').addEventListener('click', close);
    modal.addEventListener('click', e => { if (e.target === modal) close(); });

    document.getElementById('fav-list').addEventListener('click', e => {
      const row = e.target.closest('[data-fav-id]');
      if (!row) return;
      const id   = row.dataset.favId;
      const name = row.dataset.favName;
      close();
      if (typeof window.runSelectById === 'function') {
        window.runSelectById(id, name);
      } else {
        showToast('레시피를 불러오는 중...');
        const searchInput = document.getElementById('searchInput') ||
                            document.querySelector('input[type=text]');
        if (searchInput) {
          searchInput.value = name;
          const searchBtn = document.getElementById('searchBtn') ||
                            document.querySelector('button[type=submit]');
          searchBtn?.click();
        }
      }
    });
  }

  function refresh() {
    const list = document.getElementById('fav-list');
    if (!list) return;
    const favs = RecipeActions.getAllFavorites();
    list.innerHTML = favs.length
      ? favs.map(f => `
          <div data-fav-id="${(f.id||'').replace(/"/g,'&quot;')}" data-fav-name="${(f.name||'').replace(/"/g,'&quot;')}"
            style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #f0f0f0;cursor:pointer"
            onmouseenter="this.style.background='#fef2f2'" onmouseleave="this.style.background=''">
            ${f.image_url
              ? `<img src="${f.image_url}" style="width:56px;height:56px;object-fit:cover;border-radius:8px" onerror="this.style.display='none'">`
              : '<div style="width:56px;height:56px;background:#f5f5f5;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:22px">🍽️</div>'}
            <div style="flex:1">
              <div style="font-size:15px;font-weight:500">${f.name || f.id}</div>
              <div style="font-size:12px;color:#aaa;margin-top:2px">클릭하면 레시피를 볼 수 있어요 →</div>
            </div>
            <button onclick="event.stopPropagation();window._favRemove('${(f.id||f.name).replace(/'/g,"\\'")}','${(f.name||'').replace(/'/g,"\\'")}')"
              style="background:none;border:1px solid #fca5a5;color:#dc2626;border-radius:8px;padding:5px 12px;cursor:pointer;font-size:13px;flex-shrink:0">삭제</button>
          </div>`).join('')
      : `<div style="text-align:center;padding:40px 0;color:#aaa">
          <div style="font-size:40px;margin-bottom:10px">🤍</div>
          <p style="margin:0;font-size:15px">아직 즐겨찾기가 없어요</p>
          <p style="margin:6px 0 0;font-size:13px">레시피 카드 아래의 🤍 즐겨찾기 버튼을 눌러보세요</p>
        </div>`;
  }

  window._favRemove = (id, name) => {
    const all = ls('rec_favorites') || {};
    delete all[id || name]; ls('rec_favorites', all);
    fetch(`/api/user/favorites/${encodeURIComponent(id || name)}`, { method:'DELETE' }).catch(() => {});
    refresh();
  };

  function init() {
    const btn = document.createElement('button');
    btn.id = 'fav-main-btn';
    btn.textContent = '❤️ 즐겨찾기';
    btn.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:1000;background:#e74c3c;color:#fff;border:none;border-radius:28px;padding:12px 20px;font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 4px 16px rgba(231,76,60,0.4);transition:transform 0.2s';
    btn.addEventListener('click', open);
    btn.addEventListener('mouseenter', () => btn.style.transform = 'scale(1.05)');
    btn.addEventListener('mouseleave', () => btn.style.transform = '');
    document.body.appendChild(btn);
    window.Favorites = { refresh };
  }

  return { init, refresh };
})();

// ────────────────────────────────────────────────────────────
// 토스트 알림
// ────────────────────────────────────────────────────────────
function showToast(msg, duration = 2400) {
  let t = document.getElementById('rf-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'rf-toast';
    t.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(30,30,30,0.88);color:#fff;padding:10px 24px;border-radius:24px;font-size:14px;z-index:99999;transition:opacity 0.3s;pointer-events:none;white-space:nowrap';
    document.body.appendChild(t);
  }
  t.textContent = msg; t.style.opacity = '1';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.style.opacity = '0', duration);
}

// ────────────────────────────────────────────────────────────
// 추천 API 파라미터 빌더
// ────────────────────────────────────────────────────────────
window.buildExtraParams = function() {
  const params = new URLSearchParams();
  const slot = TimeSlot.getSlot();
  if (slot) params.set('time_slot', slot);
  const fridgeItems = Fridge.getItems();
  if (fridgeItems.length) {
    params.set('fridge', fridgeItems.join(','));
    if (Fridge.isFridgeOnly()) params.set('fridge_only', 'true');
  }
  return params.toString();
};

// ────────────────────────────────────────────────────────────
// 초기화
// ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Settings.init();
  TimeSlot.init();
  Fridge.init();
  RecipeActions.init();
  Favorites.init();
  console.log('[features.js] 6가지 편의기능 로드 완료 ✅');
});