'use strict';
// Phim Amazon — giao diện web. Hai khu tách biệt:
//   • Khu người dùng (#/, #/search, #/movie/…, #/for-you, #/account, #/reviewer/…): ngôn ngữ đời thường, không thuật ngữ kỹ thuật.
//   • Khu quản trị (#/admin/…): tình trạng CSDL, đối soát, phân tích gợi ý, đồ thị, thống kê, thực nghiệm. Cần tài khoản quản trị.

const state = {
  auth: readStoredAuth(),
  seq: 0,
  searchSeq: 0,
  handlers: {},
  charts: [],
  network: null,
  facets: null,
  sampleUsers: null,
  reviewIndex: {},
};

const SENTIMENT_LABEL = { positive: 'Tích cực', neutral: 'Trung lập', negative: 'Tiêu cực' };
const SENTIMENT_ADMIN = { ...SENTIMENT_LABEL, unavailable: 'Không có nội dung', unsupported_language: 'Không phải tiếng Anh', pending: 'Chưa phân tích' };

// ------------------------------------------------------------------ tiện ích
function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function readStoredAuth() {
  try {
    const auth = JSON.parse(localStorage.getItem('movies_demo_auth') || 'null');
    if (!auth || typeof auth.token !== 'string') return null;
    return { role: auth.role === 'admin' ? 'admin' : 'user', ...auth };
  } catch {
    return null;
  }
}

function saveAuth(auth) {
  state.auth = auth;
  try {
    if (auth) localStorage.setItem('movies_demo_auth', JSON.stringify(auth));
    else localStorage.removeItem('movies_demo_auth');
  } catch { /* trình duyệt chặn lưu trữ: chỉ giữ trong phiên */ }
  renderAccountBox();
}

const isUser = () => Boolean(state.auth && state.auth.role === 'user');
const isAdmin = () => Boolean(state.auth && state.auth.role === 'admin');

function formatDate(value) {
  if (value === null || value === undefined || value === '') return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC',
  }).format(date);
}

function reviewDate(r) {
  return formatDate(r.review_date || (r.timestamp ? r.timestamp * 1000 : null));
}

function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('vi-VN');
}

function fmtScore(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('vi-VN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtPct(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return fmtScore(Number(n) * 100, digits) + '%';
}

function fmtPrice(p) {
  return p === null || p === undefined ? '—' : '$' + Number(p).toFixed(2);
}

function fmtMs(ms) {
  if (ms === null || ms === undefined) return '—';
  if (Number(ms) === 0) return '< 1 ms';
  return Number(ms) >= 100 ? fmtNum(Math.round(ms)) + ' ms' : fmtScore(ms, ms < 10 ? 2 : 1) + ' ms';
}

function stars(n) {
  const v = Math.round(Number(n) || 0);
  return '★'.repeat(v) + '☆'.repeat(Math.max(0, 5 - v));
}

// Điểm và số đánh giá theo tác phẩm (gộp mọi phiên bản DVD/Blu-ray, mỗi đánh giá tính một lần).
function workStats(p) {
  const s = (p && p.stats) || {};
  return {
    avg: s.work_avg !== undefined ? s.work_avg : s.avg_rating,
    reviews: s.work_reviews !== undefined ? s.work_reviews : s.review_count,
  };
}

// Thể loại hiển thị: ưu tiên nhánh thể loại của Amazon, tránh nhánh hãng phim (Studio Specials…) hay định dạng.
const GENRE_ROOTS = ['Genre for Featured Categories', 'Science Fiction & Fantasy', 'Musicals & Performing Arts', 'Art House & International', 'Classics', 'Holidays & Seasonal', 'Movies', 'TV'];
function deepestPath(product) {
  const nav = ['Movies & TV', 'Genre for Featured Categories', 'Featured Categories', 'All Titles', 'All'];
  const paths = product.category_paths || [];
  const genre = paths.filter((p) => GENRE_ROOTS.includes(p[1]));
  const pool = (genre.length ? genre : paths).map((p) => p.filter((x) => !nav.includes(x)));
  const longest = pool.reduce((best, p) => (p.length > best.length ? p : best), []);
  return longest.join(' › ');
}

function movieLink(asin, title) {
  return `<a href="#/movie/${encodeURIComponent(asin)}">${esc(title || 'Phim')}</a>`;
}

function reviewerLink(uid, name) {
  return `<a href="#/reviewer/${encodeURIComponent(uid)}">${esc(name || 'Người xem')}</a>`;
}

function adminUserLink(uid, label) {
  return `<a href="#/admin/user/${encodeURIComponent(uid)}">${esc(label || uid)}</a>`;
}

function hashFor(path, params) {
  const clean = {};
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') clean[k] = v;
  });
  const qs = new URLSearchParams(clean).toString();
  return '#/' + path + (qs ? '?' + qs : '');
}

function go(path, params) {
  const target = hashFor(path, params);
  if (location.hash === target) render();
  else location.hash = target;
}

function toast(message) {
  const box = document.getElementById('toast');
  if (!box) return;
  box.textContent = message;
  box.classList.remove('hidden');
  clearTimeout(box.timer);
  box.timer = setTimeout(() => box.classList.add('hidden'), 6000);
}

function setHTML(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function errorBox(err) {
  return `<div class="msg error">${esc(err && err.message ? err.message : String(err))}</div>`;
}

async function apiFetch(path, options = {}) {
  const headers = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (state.auth && state.auth.token) headers.Authorization = 'Bearer ' + state.auth.token;
  let response;
  try {
    response = await fetch(path, {
      method: options.method || 'GET', headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new Error('Không kết nối được máy chủ. Hãy thử lại sau.');
  }
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    if (response.status === 401 && state.auth && headers.Authorization) {
      saveAuth(null);
      toast('Phiên đăng nhập đã hết hạn, hãy đăng nhập lại.');
    }
    const error = new Error((data && data.error) || 'Có lỗi xảy ra, hãy thử lại.');
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return { status: response.status, data };
}

function rememberReview(r) {
  if (r && r.review_id) state.reviewIndex[r.review_id] = r;
}

function pagerLinks(page, total, limit, hrefFor) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return '';
  const prev = page > 1 ? `<a class="btn" href="${hrefFor(page - 1)}">← Trang trước</a>` : '<button disabled>← Trang trước</button>';
  const next = page < pages ? `<a class="btn" href="${hrefFor(page + 1)}">Trang sau →</a>` : '<button disabled>Trang sau →</button>';
  return `<div class="pager">${prev}<span class="muted">Trang ${fmtNum(page)} / ${fmtNum(pages)}</span>${next}</div>`;
}

function pagerButtons(page, total, limit, action) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return '';
  return `<div class="pager"><button type="button" data-action="${action}" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>← Trang trước</button>`
    + `<span class="muted">Trang ${fmtNum(page)} / ${fmtNum(pages)}</span>`
    + `<button type="button" data-action="${action}" data-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>Trang sau →</button></div>`;
}

async function loadFacets() {
  if (!state.facets) state.facets = (await apiFetch('/api/facets')).data;
  return state.facets;
}

function destroyVisuals() {
  state.charts.forEach((c) => { try { c.destroy(); } catch { /* đã hủy */ } });
  state.charts = [];
  if (state.network) { try { state.network.destroy(); } catch { /* đã hủy */ } state.network = null; }
}

// ------------------------------------------------------------------ thành phần dùng chung (khu người dùng)
function movieTable(items, options = {}) {
  if (!items || !items.length) return `<p class="muted">${esc(options.empty || 'Không có phim nào.')}</p>`;
  const rows = items.map((p, i) => {
    const s = workStats(p);
    const sub = [p.brand, (p.formats || []).slice(0, 3).join(', ')].filter(Boolean).join(' · ');
    const reasons = options.reasons ? options.reasons(p, i) : [];
    return `<tr>${options.rank === false ? '' : `<td class="rank">${i + 1}</td>`}
      <td>${movieLink(p.asin, p.title)}${sub ? `<div class="small muted">${esc(sub)}</div>` : ''}
        ${reasons && reasons.length ? `<ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}</td>
      <td class="num"><span class="stars" title="${fmtScore(s.avg, 2)} / 5">${stars(s.avg)}</span> ${fmtScore(s.avg, 1)}</td>
      <td class="num">${fmtNum(s.reviews)}</td>
      <td class="num">${fmtPrice(p.price_any !== undefined ? p.price_any : p.price)}</td>
      ${options.action ? `<td class="nowrap">${options.action(p)}</td>` : ''}</tr>`;
  }).join('');
  return `<div class="table-wrap"><table><thead><tr>${options.rank === false ? '' : '<th class="rank">#</th>'}<th>Phim</th>`
    + `<th class="num">Điểm người xem</th><th class="num">Lượt đánh giá</th><th class="num">Giá từ</th>${options.action ? '<th></th>' : ''}</tr></thead>`
    + `<tbody>${rows}</tbody></table></div>`;
}

function sentimentBadge(sentiment, admin = false) {
  const label = sentiment && sentiment.label;
  const names = admin ? SENTIMENT_ADMIN : SENTIMENT_LABEL;
  if (!names[label]) return '';
  const compound = admin && sentiment.compound !== null && sentiment.compound !== undefined ? ' ' + fmtScore(sentiment.compound, 2) : '';
  return `<span class="badge ${esc(label)}">${esc(names[label])}${esc(compound)}</span>`;
}

function renderReviewItem(r, options = {}) {
  rememberReview(r);
  const own = Boolean(isUser() && r.reviewerID === state.auth.reviewerID);
  const text = r.reviewText || '';
  const long = text.length > 700;
  const meta = [
    options.admin ? adminUserLink(r.reviewerID, r.display_name || r.reviewerName) : reviewerLink(r.reviewerID, r.display_name || r.reviewerName),
    esc(reviewDate(r)),
    r.vote ? `${fmtNum(r.vote)} người thấy hữu ích` : '',
    r.verified ? 'đã mua sản phẩm' : '',
    own ? '<b>đánh giá của bạn</b>' : '',
    options.showProduct ? 'Phim: ' + movieLink(r.asin, r.product_title) : '',
  ].filter(Boolean).join(' · ');
  const actions = [
    long ? `<button type="button" data-action="expand" data-id="${esc(r.review_id)}">Xem toàn bộ</button>` : '',
    own ? `<button type="button" data-action="edit-review" data-id="${esc(r.review_id)}">Sửa</button><button type="button" data-action="delete-review" data-id="${esc(r.review_id)}">Xóa</button>`
      : (options.admin ? '' : `<button type="button" data-action="vote" data-id="${esc(r.review_id)}">Hữu ích</button>`),
  ].join('');
  return `<article class="review">
    <div class="review-head"><span class="stars">${stars(r.overall)}</span> <b>${esc(r.summary || '')}</b> ${sentimentBadge(r.sentiment, options.admin)}</div>
    <div class="meta">${meta}</div>
    ${text ? `<p class="text" data-text="${esc(r.review_id)}">${esc(long ? text.slice(0, 700) + '…' : text)}</p>` : '<p class="muted small">(Chỉ chấm sao, không có lời nhận xét)</p>'}
    ${actions ? `<div class="actions">${actions}</div>` : ''}
  </article>`;
}

function reviewList(items, options = {}) {
  if (!items || !items.length) return `<p class="muted">${esc(options.empty || 'Chưa có đánh giá.')}</p>`;
  return items.map((r) => renderReviewItem(r, options)).join('');
}

function starBars(starCounts) {
  const counts = starCounts || {};
  const total = Object.values(counts).reduce((a, b) => a + (b || 0), 0) || 1;
  return [5, 4, 3, 2, 1].map((s) => {
    const n = counts[String(s)] || 0;
    return `<div class="bar-row"><span>${s} sao</span><div class="bar"><i style="width:${(n / total * 100).toFixed(1)}%"></i></div><span class="right">${fmtPct(n / total, 0)}</span></div>`;
  }).join('');
}

function opinionSummary(sentiment) {
  const s = sentiment || {};
  const pos = s.positive || 0; const neu = s.neutral || 0; const neg = s.negative || 0;
  const n = pos + neu + neg;
  if (!n) return '<p class="muted">Chưa có lời nhận xét để tổng hợp.</p>';
  const w = (x) => (x / n * 100).toFixed(1);
  return `<div class="stack"><i class="pos" style="width:${w(pos)}%"></i><i class="neu" style="width:${w(neu)}%"></i><i class="neg" style="width:${w(neg)}%"></i></div>
    <p><span class="badge positive">Khen ${fmtPct(pos / n, 0)}</span> <span class="badge neutral">Trung lập ${fmtPct(neu / n, 0)}</span> <span class="badge negative">Chê ${fmtPct(neg / n, 0)}</span>
      <span class="muted small">trên ${fmtNum(n)} lời nhận xét tiếng Anh</span></p>
    <p class="note">Phân loại tự động theo từ ngữ trong lời nhận xét, có thể sai với câu mỉa mai hoặc đoạn kể nội dung phim. Số sao ở bên trái là điểm người xem tự chấm.</p>`;
}

// ------------------------------------------------------------------ định tuyến
function parseHash() {
  const raw = (location.hash || '#/').replace(/^#/, '');
  const index = raw.indexOf('?');
  const path = index >= 0 ? raw.slice(0, index) : raw;
  const query = index >= 0 ? raw.slice(index + 1) : '';
  const parts = path.split('/').filter(Boolean).map((p) => decodeURIComponent(p));
  if (parts[0] === 'admin') {
    return { area: 'admin', name: parts[1] || 'overview', arg: parts[2] || '', params: new URLSearchParams(query) };
  }
  return { area: 'user', name: parts[0] || 'home', arg: parts[1] || '', params: new URLSearchParams(query) };
}

const USER_ROUTES = {
  home: pageHome, search: pageSearch, movie: pageMovie, 'for-you': pageForYou, account: pageAccount, reviewer: pageReviewer,
};
const ADMIN_ROUTES = {
  overview: adminOverview, recommend: adminRecommend, user: adminUser, graph: adminGraph, stats: adminStats,
  experiments: adminExperiments, communities: adminCommunities, community: adminCommunity,
};
const USER_NAV = [['home', '#/', 'Trang chủ'], ['search', '#/search', 'Tìm phim'], ['for-you', '#/for-you', 'Gợi ý cho bạn'], ['account', '#/account', 'Tài khoản']];
const ADMIN_NAV = [['overview', '#/admin', 'Hệ thống & dữ liệu'], ['recommend', '#/admin/recommend', 'Phân tích gợi ý'], ['graph', '#/admin/graph', 'Đồ thị Neo4j'],
  ['stats', '#/admin/stats', 'Thống kê review'], ['experiments', '#/admin/experiments', 'Thực nghiệm'], ['communities', '#/admin/communities', 'Cộng đồng phim']];
const NAV_OF = { movie: 'search', reviewer: 'search', user: 'recommend', community: 'communities' };

function renderNav(route) {
  const items = route.area === 'admin' ? ADMIN_NAV : USER_NAV;
  const active = NAV_OF[route.name] || route.name;
  const links = items.map(([key, href, label]) => `<a href="${href}" class="${key === active ? 'active' : ''}">${esc(label)}</a>`).join('');
  const switcher = route.area === 'admin'
    ? '<a href="#/" class="nav-switch">← Về trang người dùng</a>'
    : (isAdmin() ? '<a href="#/admin" class="nav-switch">Khu quản trị →</a>' : '');
  document.getElementById('nav').innerHTML = links + switcher;
  document.body.classList.toggle('admin-area', route.area === 'admin');
  document.getElementById('siteTitle').innerHTML = route.area === 'admin' ? 'Phim Amazon <span>· Quản trị</span>' : 'Phim Amazon';
}

function alive(token) {
  return token === state.seq;
}

function view(html) {
  document.getElementById('view').innerHTML = html;
}

async function render() {
  const route = parseHash();
  const token = ++state.seq;
  state.handlers = {};
  destroyVisuals();
  renderNav(route);
  view('<p class="muted">Đang tải…</p>');
  window.scrollTo(0, 0);
  try {
    if (route.area === 'admin') {
      if (!isAdmin()) { adminLogin(); return; }
      await (ADMIN_ROUTES[route.name] || adminOverview)(route, token);
    } else {
      await (USER_ROUTES[route.name] || pageHome)(route, token);
    }
  } catch (err) {
    if (!alive(token)) return;
    if (err.status === 403 || (route.area === 'admin' && err.status === 401)) { adminLogin(err.message); return; }
    view(`<h1>Không mở được trang</h1>${errorBox(err)}<p><a href="#/">Về trang chủ</a></p>`);
  }
}

// ================================================================== KHU NGƯỜI DÙNG
async function pageHome(route, token) {
  const tasks = [apiFetch('/api/home?limit=12').then((r) => r.data)];
  if (isUser()) tasks.push(apiFetch('/api/me/recommendations?limit=6').then((r) => r.data).catch(() => null));
  const [home, mine] = await Promise.all(tasks);
  if (!alive(token)) return;
  const c = home.counts || {};
  let personal = '';
  if (isUser() && mine) {
    personal = mine.needs_more_ratings
      ? `<section class="panel"><h2>Gợi ý cho bạn</h2><p>Bạn mới chấm ${fmtNum(mine.rated)} phim. Chấm thêm vài phim đã xem để nhận gợi ý đúng gu hơn.</p>
          <p><a class="btn primary" href="#/for-you">Chấm nhanh vài phim</a></p></section>`
      : `<section class="panel"><h2>Gợi ý cho bạn</h2>${movieTable(mine.items.map((i) => ({ ...i.product, _reasons: i.reasons })), { reasons: (p) => p._reasons })}
          <p><a href="#/for-you">Xem thêm gợi ý →</a></p></section>`;
  }
  view(`
    <h1>Tìm phim hay, đọc đánh giá thật</h1>
    <p class="lead">${fmtNum(c.works)} phim và ${fmtNum(c.reviews)} lượt đánh giá của ${fmtNum(c.users)} người xem trên Amazon.
      ${isUser() ? '' : '<a href="#/account">Đăng nhập</a> để chấm điểm phim và nhận gợi ý theo gu của bạn.'}</p>
    ${personal}
    <section class="panel"><h2>Thể loại</h2>
      <div class="chips">${(home.genres || []).map((g) => `<a class="chip" href="${hashFor('search', { category: g.name })}">${esc(g.name)} <small>${fmtNum(g.count)}</small></a>`).join('')}</div></section>
    <div class="grid2">
      <section class="panel"><h2>Được yêu thích nhất</h2><p class="note">Nhiều người chấm từ 4 sao nhất.</p>${movieTable(home.popular)}</section>
      <section class="panel"><h2>Điểm cao nhất</h2><p class="note">Điểm trung bình cao, đã tính đến số lượt đánh giá (phim ít đánh giá không chiếm chỗ chỉ nhờ vài điểm 5).</p>${movieTable(home.top_rated)}</section>
    </div>`);
}

// ------------------------------------------------------------------ Tìm kiếm
function optionList(items, selected, allLabel) {
  return `<option value="">${esc(allLabel)}</option>` + items.map((i) => `<option value="${esc(i.name)}" ${i.name === selected ? 'selected' : ''}>${esc(i.name)} (${fmtNum(i.count)})</option>`).join('');
}

const PRODUCT_SORTS = [['', 'Phù hợp nhất'], ['reviews', 'Nhiều đánh giá nhất'], ['rating', 'Điểm cao nhất'], ['price_asc', 'Giá thấp đến cao'], ['price_desc', 'Giá cao đến thấp']];

async function pageSearch(route, token) {
  const p = route.params;
  const mode = p.get('mode') === 'reviews' ? 'reviews' : 'movies';
  const facets = await loadFacets();
  if (!alive(token)) return;
  const tabs = `<div class="tabs"><a href="#/search" class="${mode === 'movies' ? 'active' : ''}">Tìm phim</a><a href="#/search?mode=reviews" class="${mode === 'reviews' ? 'active' : ''}">Tìm trong lời đánh giá</a></div>`;
  if (mode === 'movies') {
    view(`<h1>Tìm phim</h1>${tabs}
      <section class="panel"><form class="inline" data-form="movie-search">
        <label class="wide">Tên phim hoặc từ khóa<input name="q" value="${esc(p.get('q') || '')}" placeholder="ví dụ: star wars, friends, batman"></label>
        <label>Thể loại<select name="category">${optionList(facets.genres || facets.categories, p.get('category'), 'Tất cả thể loại')}</select></label>
        <label>Định dạng<select name="format">${optionList(facets.formats, p.get('format'), 'Tất cả định dạng')}</select></label>
        <label>Giá từ ($)<input name="min_price" type="number" min="0" step="0.01" value="${esc(p.get('min_price') || '')}" class="short"></label>
        <label>đến ($)<input name="max_price" type="number" min="0" step="0.01" value="${esc(p.get('max_price') || '')}" class="short"></label>
        <label>Sắp xếp<select name="sort">${PRODUCT_SORTS.map(([v, l]) => `<option value="${v}" ${v === (p.get('sort') || '') ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <button class="primary" type="submit">Tìm</button> <a class="btn" href="#/search">Xóa bộ lọc</a>
      </form>
      ${p.get('min_price') || p.get('max_price') ? '<p class="note">Khi lọc theo giá, phim không có thông tin giá sẽ không hiện.</p>' : ''}</section>
      <section class="panel" id="searchResults"><p class="muted">Đang tìm…</p></section>`);
    state.handlers['form:movie-search'] = (form) => go('search', Object.fromEntries(new FormData(form)));
    await runProductSearch(Object.fromEntries(p));
  } else {
    view(`<h1>Tìm trong lời đánh giá</h1>${tabs}
      <section class="panel"><form class="inline" data-form="review-search">
        <input type="hidden" name="mode" value="reviews">
        <label class="wide">Từ khóa (tiếng Anh) trong tiêu đề hoặc nội dung đánh giá<input name="q" value="${esc(p.get('q') || '')}" placeholder="ví dụ: masterpiece, plot twist" required></label>
        <label>Loại nhận xét<select name="sentiment">${[['', 'Tất cả'], ['positive', 'Khen'], ['neutral', 'Trung lập'], ['negative', 'Chê']].map(([v, l]) => `<option value="${v}" ${v === (p.get('sentiment') || '') ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label>Sắp xếp<select name="sort">${[['relevance', 'Phù hợp nhất'], ['recent', 'Mới nhất'], ['helpful', 'Hữu ích nhất']].map(([v, l]) => `<option value="${v}" ${v === (p.get('sort') || 'relevance') ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <button class="primary" type="submit">Tìm</button>
      </form></section>
      <section class="panel" id="searchResults">${p.get('q') ? '<p class="muted">Đang tìm…</p>' : '<p class="muted">Nhập từ khóa để tìm trong hơn 3 triệu lời đánh giá.</p>'}</section>`);
    state.handlers['form:review-search'] = (form) => go('search', Object.fromEntries(new FormData(form)));
    if (p.get('q')) await runReviewSearch(Object.fromEntries(p));
  }
}

async function runProductSearch(params) {
  const id = ++state.searchSeq;
  const page = Math.max(1, Number(params.page) || 1);
  const query = new URLSearchParams();
  ['q', 'category', 'format', 'min_price', 'max_price', 'sort'].forEach((k) => { if (params[k]) query.set(k, params[k]); });
  query.set('page', page);
  query.set('limit', 20);
  const target = document.getElementById('searchResults');
  try {
    const { data } = await apiFetch('/api/products?' + query.toString());
    if (id !== state.searchSeq) return;
    if (!data.items.length) {
      target.innerHTML = '<p class="muted">Không tìm thấy phim phù hợp. Thử bỏ bớt bộ lọc hoặc dùng từ khóa khác.</p>';
      return;
    }
    target.innerHTML = `<p class="muted">Tìm thấy ${fmtNum(data.total)} phim.</p>
      ${movieTable(data.items, { rank: false })}
      ${pagerLinks(page, data.total, data.limit, (n) => hashFor('search', { ...params, page: n }))}`;
  } catch (err) {
    if (id === state.searchSeq) target.innerHTML = errorBox(err);
  }
}

async function runReviewSearch(params) {
  const id = ++state.searchSeq;
  const page = Math.max(1, Number(params.page) || 1);
  const query = new URLSearchParams({ q: params.q, page, limit: 20, sort: params.sort || 'relevance' });
  if (params.sentiment) query.set('sentiment', params.sentiment);
  const target = document.getElementById('searchResults');
  try {
    const { data } = await apiFetch('/api/reviews?' + query.toString());
    if (id !== state.searchSeq) return;
    const summary = data.total_capped
      ? `<div class="msg warn">Có hơn ${fmtNum(data.total)} đánh giá chứa từ khóa này nên chưa xếp được theo mức phù hợp. Hãy thêm từ khóa hoặc chọn loại nhận xét để thu hẹp.</div>`
      : `<p class="muted">Tìm thấy ${fmtNum(data.total)} đánh giá.</p>`;
    target.innerHTML = `${summary}${reviewList(data.items, { showProduct: true })}
      ${pagerLinks(page, data.total, data.limit, (n) => hashFor('search', { ...params, page: n }))}`;
  } catch (err) {
    if (id === state.searchSeq) target.innerHTML = errorBox(err);
  }
}

// ------------------------------------------------------------------ Chi tiết phim
function keywordColumn(title, group) {
  if (!group || !group.items || !group.items.length) return `<div><h3>${esc(title)}</h3><p class="muted small">Chưa đủ đánh giá.</p></div>`;
  return `<div><h3>${esc(title)}</h3><div class="chips">${group.items.map((k) => `<span class="chip">${esc(k.keyword)}</span>`).join('')}</div></div>`;
}

function reviewForm(product) {
  if (isAdmin()) return '<p class="muted">Tài khoản quản trị không chấm điểm phim. Đăng xuất và đăng nhập tài khoản người dùng để thử.</p>';
  if (!isUser()) return `<p><a href="#/account">Đăng nhập hoặc tạo tài khoản</a> để chấm điểm và viết đánh giá.</p>`;
  return `<form data-form="review" id="reviewForm">
    <input type="hidden" name="review_id" value="">
    <div class="toolbar">
      <label>Số sao<select name="overall" required><option value="">Chọn…</option>${[5, 4, 3, 2, 1].map((s) => `<option value="${s}">${s} sao — ${['', 'Rất tệ', 'Tệ', 'Tạm được', 'Hay', 'Rất hay'][s]}</option>`).join('')}</select></label>
      <label class="wide">Tiêu đề (không bắt buộc)<input name="summary" maxlength="500" placeholder="Một câu tóm tắt cảm nhận"></label>
    </div>
    <label class="full" style="margin-top:8px">Nhận xét (không bắt buộc)<textarea name="reviewText" maxlength="20000" placeholder="Bạn thấy phim thế nào?"></textarea></label>
    <p class="note">Nhận xét bằng tiếng Anh sẽ được tự động xếp loại khen/chê; nhận xét tiếng Việt vẫn được lưu và hiển thị bình thường.</p>
    <div class="toolbar">
      <button class="primary" type="submit" id="reviewSubmit">Gửi đánh giá</button>
      <button type="button" class="hidden" id="cancelEdit" data-action="cancel-edit">Hủy sửa</button>
      <span class="muted small" id="reviewMode">Đánh giá cho “${esc(product.title)}”.</span>
    </div>
    <div id="reviewResult"></div>
  </form>`;
}

function fillReviewForm(r) {
  const form = document.getElementById('reviewForm');
  if (!form) return false;
  form.elements.review_id.value = r.review_id;
  form.elements.overall.value = String(Math.round(r.overall));
  form.elements.summary.value = r.summary || '';
  form.elements.reviewText.value = r.reviewText || '';
  document.getElementById('reviewSubmit').textContent = 'Lưu thay đổi';
  document.getElementById('cancelEdit').classList.remove('hidden');
  document.getElementById('reviewMode').textContent = 'Đang sửa đánh giá của bạn.';
  form.classList.remove('hidden');
  form.scrollIntoView({ behavior: 'smooth', block: 'center' });
  return true;
}

function editionsTable(product) {
  const editions = product.editions || [];
  if (editions.length < 2) return '';
  const rows = editions.map((e) => `<tr><td>${e.asin === product.asin ? `<b>${esc(e.title)}</b> <span class="muted small">(đang xem)</span>` : movieLink(e.asin, e.title)}</td>`
    + `<td>${esc((e.formats || []).join(', ') || '—')}</td><td class="num">${fmtPrice(e.price)}</td></tr>`).join('');
  return `<section class="panel"><h2>Các phiên bản đang bán (${editions.length})</h2>
    <p class="note">Cùng một phim phát hành ở nhiều phiên bản (DVD, Blu-ray, nhập khẩu…). Điểm và đánh giá bên dưới gộp mọi phiên bản, mỗi đánh giá chỉ tính một lần.</p>
    <div class="table-wrap"><table><thead><tr><th>Phiên bản</th><th>Định dạng</th><th class="num">Giá</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

async function pageMovie(route, token) {
  const asin = route.arg;
  const { data: product } = await apiFetch('/api/products/' + encodeURIComponent(asin));
  if (!alive(token)) return;
  const ws = product.work_stats || {};
  const work = product.work || asin;
  const image = (product.images || [])[0];
  const genre = deepestPath(product);
  view(`
    <p><a href="#" data-action="back">← Quay lại</a></p>
    <div class="movie-head">
      ${image ? `<img src="${esc(image)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ''}
      <div>
        <h1>${esc(product.title)}</h1>
        ${work !== asin ? `<p class="muted">Một phiên bản của ${movieLink(work, product.work_title)}.</p>` : ''}
        <dl class="facts">
          <dt>Diễn viên / thương hiệu</dt><dd>${esc(product.brand || '—')}</dd>
          <dt>Thể loại</dt><dd>${esc(genre || '—')}</dd>
          <dt>Định dạng</dt><dd>${esc((product.formats || []).join(', ') || '—')}</dd>
          <dt>Giá</dt><dd>${fmtPrice(product.price)}${product.price_any !== null && product.price_any !== undefined && product.price_any !== product.price ? ` <span class="muted small">(rẻ nhất trong các phiên bản: ${fmtPrice(product.price_any)})</span>` : ''}</dd>
        </dl>
        <div class="toolbar"><button type="button" data-action="scroll" data-target="write">Chấm điểm phim này</button><button type="button" data-action="scroll" data-target="related">Phim thường mua cùng</button></div>
      </div>
    </div>
    <div class="grid2" style="margin-top:14px">
      <section class="panel"><h2>Điểm người xem</h2>
        <p><span class="big">${fmtScore(ws.avg_rating, 1)}</span> / 5 <span class="stars">${stars(ws.avg_rating)}</span> · ${fmtNum(ws.reviews)} lượt đánh giá</p>${starBars(ws.stars)}</section>
      <section class="panel"><h2>Người xem nói gì</h2>${opinionSummary(ws.sentiment)}<div id="keywords"></div></section>
    </div>
    ${editionsTable(product)}
    <section class="panel" id="write"><h2>Đánh giá của bạn</h2><div id="myReviews"></div>${reviewForm(product)}</section>
    <section class="panel"><h2>Đánh giá của người xem</h2>
      <div class="toolbar">
        <label>Sắp xếp<select data-change="reviews-filter" id="revSort"><option value="helpful">Hữu ích nhất</option><option value="recent">Mới nhất</option></select></label>
        <label>Loại nhận xét<select data-change="reviews-filter" id="revSentiment"><option value="">Tất cả</option><option value="positive">Khen</option><option value="neutral">Trung lập</option><option value="negative">Chê</option></select></label>
      </div>
      <div id="reviewList"><p class="muted">Đang tải…</p></div></section>
    <section class="panel" id="related"><h2>Người mua phim này cũng mua hoặc xem</h2><div id="relatedList"><p class="muted">Đang tải…</p></div></section>`);

  const loadReviews = async (page) => {
    const sort = document.getElementById('revSort').value;
    const sentiment = document.getElementById('revSentiment').value;
    const q = new URLSearchParams({ work, sort, page, limit: 10 });
    if (sentiment) q.set('sentiment', sentiment);
    try {
      const { data } = await apiFetch('/api/reviews?' + q.toString());
      if (!alive(token)) return;
      setHTML('reviewList', `<p class="muted small">${fmtNum(data.total)} đánh giá</p>${reviewList(data.items)}${pagerButtons(page, data.total, data.limit, 'reviews-page')}`);
    } catch (err) { if (alive(token)) setHTML('reviewList', errorBox(err)); }
  };
  const loadRelated = async () => {
    try {
      const { data } = await apiFetch(`/api/products/${encodeURIComponent(asin)}/related?steps=2&limit=10`);
      if (!alive(token)) return;
      setHTML('relatedList', movieTable(data.items.filter((r) => r.product).map((r) => r.product), { empty: 'Chưa có dữ liệu mua cùng cho phim này.' }));
    } catch (err) { if (alive(token)) setHTML('relatedList', errorBox(err)); }
  };
  const loadMine = async () => {
    if (!isUser()) return;
    try {
      const { data } = await apiFetch(`/api/reviews?work=${encodeURIComponent(work)}&reviewerID=${encodeURIComponent(state.auth.reviewerID)}&limit=5`);
      if (!alive(token)) return;
      if (data.items.length) {
        setHTML('myReviews', reviewList(data.items));
        document.getElementById('reviewForm').classList.add('hidden');
        const edit = route.params.get('edit');
        if (edit && state.reviewIndex[edit]) fillReviewForm(state.reviewIndex[edit]);
      }
    } catch { /* bỏ qua: vẫn có thể viết đánh giá */ }
  };

  state.handlers['reviews-page'] = (el) => loadReviews(Number(el.dataset.page));
  state.handlers['change:reviews-filter'] = () => loadReviews(1);
  state.handlers['cancel-edit'] = () => render();
  state.handlers['form:review'] = async (form) => {
    const fd = new FormData(form);
    if (!fd.get('overall')) { setHTML('reviewResult', '<div class="msg warn">Hãy chọn số sao.</div>'); return; }
    const rid = fd.get('review_id');
    const payload = { asin, overall: Number(fd.get('overall')), summary: String(fd.get('summary') || ''), reviewText: String(fd.get('reviewText') || '') };
    const button = document.getElementById('reviewSubmit');
    button.disabled = true;
    try {
      const { data } = rid
        ? await apiFetch('/api/reviews/' + encodeURIComponent(rid), { method: 'PUT', body: payload })
        : await apiFetch('/api/reviews', { method: 'POST', body: payload });
      toast(data.synced ? 'Đã lưu đánh giá. Gợi ý cho bạn đã được cập nhật.' : 'Đã lưu đánh giá. Gợi ý sẽ cập nhật sau ít phút.');
      go('movie/' + encodeURIComponent(asin));
    } catch (err) {
      setHTML('reviewResult', errorBox(err));
      button.disabled = false;
    }
  };

  apiFetch(`/api/products/${encodeURIComponent(work)}/keywords`).then(({ data }) => {
    if (!alive(token)) return;
    const cols = [keywordColumn('Được nhắc nhiều', data.all), keywordColumn('Trong lời khen', data.positive), keywordColumn('Trong lời chê', data.negative)];
    setHTML('keywords', `<div class="grid3 small-grid">${cols.join('')}</div>`);
  }).catch(() => { if (alive(token)) setHTML('keywords', ''); });
  await Promise.all([loadReviews(1), loadRelated(), loadMine()]);
}

// ------------------------------------------------------------------ Trang một người đánh giá
async function pageReviewer(route, token) {
  const uid = route.arg;
  const page = Math.max(1, Number(route.params.get('page')) || 1);
  const { data } = await apiFetch(`/api/users/${encodeURIComponent(uid)}/profile?page=${page}&limit=20`);
  if (!alive(token)) return;
  const u = data.user;
  view(`<p><a href="#" data-action="back">← Quay lại</a></p>
    <h1>${esc(u.display_name)}</h1>
    <p class="lead">${fmtNum(data.total_reviews)} đánh giá · điểm trung bình đã chấm ${fmtScore(u.stats && u.stats.avg_rating, 1)} / 5</p>
    <section class="panel"><h2>Các đánh giá</h2>${reviewList(data.reviews, { showProduct: true })}
      ${pagerLinks(page, data.total_reviews, data.limit, (n) => hashFor('reviewer/' + encodeURIComponent(uid), { page: n }))}</section>`);
}

// ------------------------------------------------------------------ Gợi ý cho bạn
async function pageForYou(route, token) {
  if (isAdmin()) {
    view(`<h1>Gợi ý cho bạn</h1><div class="msg">Bạn đang đăng nhập tài khoản quản trị. Xem gợi ý của bất kỳ người dùng nào ở <a href="#/admin/recommend">Khu quản trị › Phân tích gợi ý</a>.</div>`);
    return;
  }
  if (!isUser()) {
    const { data: home } = await apiFetch('/api/home?limit=12');
    if (!alive(token)) return;
    view(`<h1>Gợi ý cho bạn</h1>
      <div class="msg"><a href="#/account">Đăng nhập hoặc tạo tài khoản</a> rồi chấm điểm vài phim đã xem: hệ thống sẽ gợi ý phim hợp gu dựa trên những người xem có sở thích giống bạn,
        những phim hay được mua cùng và cùng thể loại với phim bạn thích.</div>
      <section class="panel"><h2>Trong lúc chờ: phim được yêu thích nhất</h2>${movieTable(home.popular)}</section>`);
    return;
  }
  const { data } = await apiFetch('/api/me/recommendations?limit=15');
  if (!alive(token)) return;
  const intro = data.needs_more_ratings
    ? `<section class="panel"><h2>Chấm nhanh vài phim bạn đã xem</h2>
        <p>Bạn đã chấm <b id="ratedCount">${fmtNum(data.rated)}</b> phim. Chấm ít nhất ${fmtNum(data.min_ratings)} phim (nhấn số sao) để gợi ý đúng gu hơn. Bỏ qua phim bạn chưa xem.</p>
        <div id="toRate"><p class="muted">Đang tải…</p></div>
        <p><button type="button" class="primary" data-action="reload">Cập nhật gợi ý</button></p></section>`
    : '';
  const list = data.fallback_to_popular
    ? `<div class="msg warn">Chưa đủ thông tin về gu của bạn (cần vài phim được chấm từ 4 sao). Tạm thời đây là các phim được yêu thích nhất.</div>${movieTable(data.items.map((i) => i.product))}`
    : movieTable(data.items.map((i) => ({ ...i.product, _reasons: i.reasons })), { reasons: (p) => p._reasons });
  view(`<h1>Gợi ý cho bạn</h1>
    <p class="lead">Dựa trên ${fmtNum(data.rated)} phim bạn đã chấm. Phim bạn đã chấm (ở bất kỳ phiên bản nào) sẽ không được gợi ý lại.</p>
    ${intro}
    <section class="panel"><h2>Phim gợi ý</h2>${list}</section>`);
  state.handlers.reload = () => render();
  if (data.needs_more_ratings) {
    const { data: rate } = await apiFetch('/api/me/to-rate?limit=12');
    if (!alive(token)) return;
    setHTML('toRate', movieTable(rate.items, {
      rank: false,
      action: (p) => `<span class="rate-buttons" data-asin="${esc(p.asin)}">${[1, 2, 3, 4, 5].map((s) => `<button type="button" data-action="quick-rate" data-asin="${esc(p.asin)}" data-stars="${s}" title="${s} sao">${s}★</button>`).join('')}</span>`,
    }));
  }
}

// ------------------------------------------------------------------ Tài khoản
function loginForms(message) {
  return `${message ? `<div class="msg warn">${esc(message)}</div>` : ''}
    <div class="grid2">
      <section class="panel"><h2>Đăng nhập</h2><form data-form="login">
        <label class="full">Tên tài khoản<input name="username" autocomplete="username" required></label>
        <label class="full" style="margin-top:8px">Mật khẩu<input name="password" type="password" autocomplete="current-password" required></label>
        <p><button class="primary" type="submit">Đăng nhập</button></p><div id="loginMsg"></div></form></section>
      <section class="panel"><h2>Tạo tài khoản mới</h2><form data-form="register">
        <label class="full">Tên tài khoản (3–32 ký tự: chữ thường a–z, số, dấu _)<input name="username" pattern="[a-z0-9_]{3,32}" autocomplete="username" required></label>
        <label class="full" style="margin-top:8px">Tên hiển thị<input name="display_name" maxlength="100"></label>
        <label class="full" style="margin-top:8px">Mật khẩu (10–128 ký tự)<input name="password" type="password" minlength="10" maxlength="128" autocomplete="new-password" required></label>
        <p><button class="primary" type="submit">Tạo tài khoản</button></p><div id="registerMsg"></div></form></section>
    </div>`;
}

async function pageAccount(route, token) {
  if (!state.auth) {
    view(`<h1>Tài khoản</h1><p class="lead">Đăng nhập để chấm điểm phim, viết đánh giá và nhận gợi ý theo gu của bạn.</p>${loginForms()}`);
    return;
  }
  if (isAdmin()) {
    view(`<h1>Tài khoản quản trị</h1><section class="panel"><p>Đang đăng nhập: <b>${esc(state.auth.username)}</b> (quản trị).</p>
      <div class="toolbar"><a class="btn primary" href="#/admin">Vào khu quản trị</a><button type="button" data-action="logout">Đăng xuất</button></div></section>`);
    return;
  }
  const uid = state.auth.reviewerID;
  view(`<h1>Tài khoản của bạn</h1>
    <section class="panel"><dl class="facts"><dt>Tên hiển thị</dt><dd>${esc(state.auth.display_name || state.auth.username || '')}</dd><dt>Tên đăng nhập</dt><dd>${esc(state.auth.username || '')}</dd></dl>
      <div class="toolbar"><a class="btn primary" href="#/for-you">Gợi ý cho tôi</a><a class="btn" href="#/search">Tìm phim để chấm điểm</a><button type="button" data-action="logout">Đăng xuất</button></div></section>
    <section class="panel"><h2>Phim bạn đã chấm</h2><div id="myList"><p class="muted">Đang tải…</p></div></section>`);
  try {
    const { data } = await apiFetch(`/api/users/${encodeURIComponent(uid)}/profile?limit=100`);
    if (!alive(token)) return;
    setHTML('myList', data.reviews.length ? reviewList(data.reviews, { showProduct: true })
      : '<p class="muted">Bạn chưa chấm phim nào. Vào <a href="#/for-you">Gợi ý cho bạn</a> để chấm nhanh vài phim.</p>');
  } catch (err) { if (alive(token)) setHTML('myList', errorBox(err)); }
}

// ================================================================== KHU QUẢN TRỊ
const METHOD_INFO = {
  hybrid: { name: 'Lai (hybrid)', text: 'Điểm từng phương pháp chuẩn hóa về [0, 1] rồi cộng: 0,45 × CF + 0,25 × mua/xem cùng + 0,20 × nội dung + 0,10 × tỉ lệ review tích cực (VADER) của tác phẩm.' },
  collaborative: { name: 'Lọc cộng tác (CF)', text: 'Láng giềng = người cùng thích (≥ 4 sao) ít nhất 2 tác phẩm trong 100 tác phẩm thích gần nhất, giữ 30 người có Jaccard cao nhất. Chỉ đề xuất tác phẩm được đủ số láng giềng tối thiểu cùng thích. Điểm = TB người dùng + Σ sim × (sao − TB láng giềng) / (Σ sim + λ).' },
  related: { name: 'Mua/xem cùng', text: 'Từ 5 review ≥ 4 sao gần nhất, đi ALSO_BOUGHT / ALSO_VIEWED 1–2 bước; điểm = số đường đi / số bước ngắn nhất, cộng dồn qua các phim gốc; đích gộp theo tác phẩm.' },
  content: { name: 'Theo nội dung', text: 'Khớp danh mục chi tiết, Brand (với phim, Amazon ghi chủ yếu là diễn viên chính) và định dạng với 20 tác phẩm thích gần nhất; điểm = số phim gốc khớp + 0,2 × số thuộc tính chung.' },
  popular: { name: 'Phổ biến (mốc so sánh)', text: 'Số review ≥ 4 sao của tác phẩm (không tính bản sao giữa các ấn bản), bỏ tác phẩm người dùng đã review.' },
};
const SUPPORT_LABEL = { collaborative: 'Số láng giềng', content: 'Phim gốc khớp', related: 'Số đường đi', popular: 'Review ≥ 4 sao' };
const GRAPH_COLORS = {
  CenterProduct: '#1f5fbf', Product: '#7ea6dc', CenterUser: '#8a5a00', User: '#d9a531', Brand: '#7a4fb5', Format: '#2f8f6a', Category: '#8a8f98',
};
const EDGE_COLORS = {
  REVIEWED: '#c9a54a', ALSO_BOUGHT: '#1f5fbf', ALSO_VIEWED: '#8fb3e6', SIMILAR_TO: '#b42318', IN_CATEGORY: '#b9c1cb', BY_BRAND: '#b9a3d6', AVAILABLE_AS: '#9cc9b4',
};
const GRAPH_LABELS = {
  CenterProduct: 'Phim trung tâm', Product: 'Phim', CenterUser: 'Người dùng trung tâm', User: 'Người dùng', Brand: 'Brand (diễn viên/hãng)', Format: 'Định dạng', Category: 'Danh mục',
};

function adminLogin(message) {
  view(`<h1>Khu quản trị</h1><p class="lead">Khu dành cho nhóm phát triển: tình trạng CSDL, đối soát MongoDB – Neo4j, phân tích thuật toán và thực nghiệm.
    Tài khoản quản trị được tạo bằng lệnh <code>python -m amazon_movies create-admin</code> (mật khẩu ghi trong tệp .env).</p>
    ${isUser() ? '<div class="msg warn">Bạn đang đăng nhập tài khoản người dùng. Đăng nhập bằng tài khoản quản trị để tiếp tục.</div>' : ''}
    ${loginForms(message).replace(/<section class="panel"><h2>Tạo tài khoản mới[\s\S]*<\/section>\s*<\/div>$/, '</div>')}`);
}

function kpi(value, label) {
  return `<div class="kpi"><b>${typeof value === 'string' ? esc(value) : fmtNum(value)}</b><span>${esc(label)}</span></div>`;
}

function col(head, cell, cls = 'num') {
  return { head, cell, cls };
}

function productTable(items, options = {}) {
  if (!items || !items.length) return '<p class="muted">Không có dữ liệu.</p>';
  const extra = options.extra || [];
  const head = `<tr><th class="rank">#</th><th>Phim (ASIN)</th><th class="num">Điểm TB</th><th class="num">Review</th>${extra.map((c) => `<th class="${c.cls}">${esc(c.head)}</th>`).join('')}</tr>`;
  const rows = items.map((p, i) => {
    const s = workStats(p);
    return `<tr><td class="rank">${i + 1}</td><td>${movieLink(p.asin, p.title)} <span class="muted small">${esc(p.asin)}</span></td>`
      + `<td class="num">${fmtScore(s.avg)}</td><td class="num">${fmtNum(s.reviews)}</td>`
      + `${extra.map((c) => `<td class="${c.cls}">${c.cell(p, i)}</td>`).join('')}</tr>`;
  }).join('');
  return `<div class="table-wrap"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}

async function loadSampleUsers() {
  if (!state.sampleUsers) state.sampleUsers = (await apiFetch('/api/users/sample')).data.items;
  return state.sampleUsers;
}

// ------------------------------------------------------------------ Hệ thống & dữ liệu
function checkCell(ok) {
  return ok ? '<span class="ok">Khớp</span>' : '<b class="bad">Lệch</b>';
}

async function adminOverview(route, token) {
  const { data } = await apiFetch('/api/admin/overview');
  if (!alive(token)) return;
  const c = data.counts; const h = data.health; const live = data.live_reconciliation || {};
  const ed = data.editions || {}; const sync = data.sync; const rec = data.reconciliation || {};
  const liveRows = ['Product', 'User', 'REVIEWED'].map((k) => `<tr><td>${k}</td><td class="num">${fmtNum((live.mongodb || {})[k])}</td><td class="num">${fmtNum((live.neo4j || {})[k])}</td><td>${(live.match || {})[k] === undefined ? '—' : checkCell(live.match[k])}</td></tr>`).join('');
  const checks = rec.checks || {};
  view(`<h1>Hệ thống & dữ liệu</h1>
    <div class="kpis">
      ${kpi(h.mongodb === 'ok' ? 'Hoạt động' : 'Không kết nối', 'MongoDB')}${kpi(h.neo4j === 'ok' ? 'Hoạt động' : 'Không kết nối', 'Neo4j')}
      ${kpi(c.works, 'tác phẩm (phim)')}${kpi(c.products, 'mã sản phẩm (ấn bản)')}${kpi(c.reviews, 'review khác nhau')}${kpi(c.review_rows, 'dòng review lưu trữ')}
      ${kpi(c.real_users, 'người dùng trong dữ liệu')}${kpi(c.demo_users, 'tài khoản tạo trên web')}
    </div>
    <div class="grid2">
      <section class="panel"><h2>Đối soát MongoDB – Neo4j (đếm trực tiếp)</h2>
        <div class="table-wrap"><table><thead><tr><th>Đối tượng</th><th class="num">MongoDB</th><th class="num">Neo4j</th><th>Kết quả</th></tr></thead><tbody>${liveRows}</tbody></table></div>
        <p class="note">Neo4j đếm bằng count store; ngoài ra có ${fmtNum((live.neo4j || {}).ALSO_BOUGHT)} ALSO_BOUGHT, ${fmtNum((live.neo4j || {}).ALSO_VIEWED)} ALSO_VIEWED, ${fmtNum((live.neo4j || {}).SIMILAR_TO)} SIMILAR_TO.</p>
        <h3>Đối soát đầy đủ gần nhất</h3>
        ${rec.checks ? `<ul class="small">${Object.entries(checks).map(([k, v]) => `<li>${esc(k)}: ${v ? '<span class="ok">đạt</span>' : '<b class="bad">không đạt</b>'}</li>`).join('')}</ul>` : '<p class="muted">Chưa chạy.</p>'}
        <p><button type="button" data-action="run-verify">Chạy đối soát đầy đủ</button> <span class="muted small">(đếm mọi nhãn/quan hệ và kiểm tra trùng review_id, mất khoảng nửa phút)</span></p>
        <div id="verifyResult"></div></section>
      <section class="panel"><h2>Đồng bộ ghi từ website</h2>
        <table><tbody>
          <tr><td>Review đang chờ ghi sang Neo4j</td><td class="num">${fmtNum(sync.pending_reviews)}</td></tr>
          <tr><td>Review ghi lỗi (worker sẽ thử lại)</td><td class="num">${fmtNum(sync.reviews_with_error)}</td></tr>
          <tr><td>Tài khoản chờ đồng bộ</td><td class="num">${fmtNum(sync.pending_users)}</td></tr>
          <tr><td>Review do tài khoản web viết</td><td class="num">${fmtNum(c.demo_reviews)}</td></tr>
        </tbody></table>
        <p class="note">Ghi review: MongoDB (synced = false) → cập nhật thống kê → MERGE REVIEWED trong Neo4j → synced = true. Neo4j lỗi thì API trả 202 và worker <code>sync --watch</code> ghi lại sau.</p>
        <h2 style="margin-top:14px">Tham số gợi ý đang dùng</h2>
        <table><tbody>
          <tr><td>Hệ số co λ của CF</td><td class="num">${fmtScore(data.settings.cf_shrinkage, 0)}</td></tr>
          <tr><td>Số láng giềng tối thiểu cùng thích (CF)</td><td class="num">${fmtNum(data.settings.cf_min_support)}</td></tr>
          <tr><td>Chuẩn hóa điểm của Hybrid</td><td class="num">${esc(data.settings.hybrid_normalization)}</td></tr>
          <tr><td>Trọng số Hybrid</td><td class="num">${esc(Object.entries(data.settings.hybrid_weights).map(([k, v]) => `${k} ${v}`).join(', '))}</td></tr>
          <tr><td>Ngưỡng “thích”</td><td class="num">≥ ${fmtScore(data.settings.like_threshold, 0)} sao</td></tr>
        </tbody></table></section>
    </div>
    <section class="panel"><h2>Gộp ấn bản thành tác phẩm</h2>
      <p class="small">${esc(ed.rule || '')}</p>
      <table><tbody>
        <tr><td>Tác phẩm có từ 2 ấn bản</td><td class="num">${fmtNum(ed.works_with_several_editions)} (${fmtNum(ed.products_in_those_works)} mã)</td></tr>
        <tr><td>Dòng review lưu trữ</td><td class="num">${fmtNum(ed.review_rows)}</td></tr>
        <tr><td>Bản sao của cùng một review ở ấn bản khác (is_copy, không tính khi thống kê và gợi ý)</td><td class="num">${fmtNum(ed.copy_rows)}</td></tr>
        <tr><td>Review khác nhau</td><td class="num">${fmtNum(ed.unique_reviews)}</td></tr>
        <tr><td>Dòng giống hệt nhau ở hai tác phẩm khác nhau (giữ lại, không bị chia Train/Test)</td><td class="num">${fmtNum(ed.identical_rows_across_works)}</td></tr>
      </tbody></table>
      <details><summary>10 tác phẩm lớn nhất</summary><ul class="small">${(ed.largest_works || []).map((w) => `<li>${esc(w.title)}: ${w.editions.map((e) => `${movieLink(e.asin, e.title)} (${fmtNum(e.reviews)})`).join('; ')}</li>`).join('')}</ul></details></section>
    <section class="panel"><h2>Tệp kết quả</h2><div class="table-wrap"><table><thead><tr><th>Tệp trong reports/</th><th>Cập nhật lúc</th></tr></thead><tbody>
      ${Object.entries(data.reports || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(new Date(v).toLocaleString('vi-VN'))}</td></tr>`).join('')}</tbody></table></div></section>`);
  state.handlers['run-verify'] = async (el) => {
    el.disabled = true;
    setHTML('verifyResult', '<p class="muted">Đang đối soát…</p>');
    try {
      const { data: v } = await apiFetch('/api/admin/verify', { method: 'POST', body: {} });
      setHTML('verifyResult', `<div class="msg ${v.ok ? 'ok' : 'error'}">${v.ok ? 'Đạt mọi kiểm tra' : 'Có kiểm tra không đạt'} (${fmtScore(v.seconds, 1)} giây): `
        + `${Object.entries(v.checks).map(([k, ok]) => `${esc(k)} ${ok ? '✓' : '✗'}`).join(', ')}</div>`);
    } catch (err) { setHTML('verifyResult', errorBox(err)); }
    el.disabled = false;
  };
}

// ------------------------------------------------------------------ Phân tích gợi ý
async function loadSimilar(uid, targetId, token) {
  try {
    const { data } = await apiFetch(`/api/users/${encodeURIComponent(uid)}/similar`);
    if (!alive(token)) return;
    if (!data.items.length) { setHTML(targetId, '<p class="muted">Không có người dùng cùng thích ít nhất 2 tác phẩm.</p>'); return; }
    setHTML(targetId, `<p class="note">${esc(data.source)}</p><table><thead><tr><th>Người dùng</th><th class="num">Jaccard</th><th class="num">Review</th></tr></thead><tbody>`
      + data.items.map((u) => `<tr><td>${adminUserLink(u.reviewerID, u.display_name)}<div class="small muted">${esc(u.reviewerID)}</div></td><td class="num">${fmtScore(u.score, 3)}</td><td class="num">${fmtNum(u.review_count)}</td></tr>`).join('')
      + '</tbody></table>');
  } catch (err) { if (alive(token)) setHTML(targetId, errorBox(err)); }
}

async function adminRecommend(route, token) {
  const p = route.params;
  const user = (p.get('user') || '').trim();
  const method = METHOD_INFO[p.get('method')] ? p.get('method') : 'hybrid';
  const limit = [10, 20, 30].includes(Number(p.get('limit'))) ? Number(p.get('limit')) : 10;
  const samples = await loadSampleUsers();
  if (!alive(token)) return;
  view(`<h1>Phân tích gợi ý</h1>
    <section class="panel"><form class="inline" data-form="recommend">
      <label class="wide">Mã người dùng (reviewerID)<input name="user" list="userOptions" value="${esc(user)}" placeholder="ví dụ: ${esc(samples[0] ? samples[0].reviewerID : '')}" required></label>
      <datalist id="userOptions">${samples.map((s) => `<option value="${esc(s.reviewerID)}">${esc(s.display_name)} — ${fmtNum(s.stats && s.stats.review_count)} review</option>`).join('')}</datalist>
      <label>Phương pháp<select name="method">${Object.entries(METHOD_INFO).map(([k, v]) => `<option value="${k}" ${k === method ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></label>
      <label>Số phim<select name="limit">${[10, 20, 30].map((n) => `<option ${n === limit ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
      <button class="primary" type="submit">Gợi ý</button>
    </form>
    <p class="note"><b>${esc(METHOD_INFO[method].name)}:</b> ${esc(METHOD_INFO[method].text)}</p>
    ${user ? '' : `<p>Người dùng mẫu (30–120 review): ${samples.map((s) => `<a href="${hashFor('admin/recommend', { user: s.reviewerID })}">${esc(s.display_name)}</a>`).join(' · ')}</p>`}
    </section>
    ${user ? `<div class="split"><section class="panel"><h2>Kết quả</h2><div id="recList"><p class="muted">Đang truy vấn Neo4j…</p></div></section>
      <div><section class="panel"><h2>Người dùng</h2><div id="recUser"><p class="muted">Đang tải…</p></div></section>
      <section class="panel"><h2>Người dùng tương đồng</h2><div id="recSimilar"><p class="muted">Đang tính…</p></div></section></div></div>` : ''}`);
  state.handlers['form:recommend'] = (form) => go('admin/recommend', Object.fromEntries(new FormData(form)));
  if (!user) return;

  const recTask = apiFetch(`/api/recommendations/${encodeURIComponent(user)}?method=${method}&limit=${limit}`).then(({ data }) => {
    if (!alive(token)) return;
    const extra = [col('Điểm gợi ý', (item) => fmtScore(item.rec.score, 3))];
    if (method === 'hybrid') {
      [['collaborative', 'CF'], ['related', 'Mua cùng'], ['content', 'Nội dung'], ['sentiment', 'Cảm xúc']].forEach(([k, label]) => {
        extra.push(col(label, (item) => {
          const v = (item.rec.components || {})[k];
          return v === undefined ? '<span class="muted">–</span>' : fmtScore(v, 2);
        }));
      });
    } else {
      extra.push(col(SUPPORT_LABEL[method], (item) => fmtNum(item.rec.support)));
    }
    const items = data.items.map((r) => ({ ...r.product, rec: r }));
    setHTML('recList', `${method === 'hybrid' ? '<p class="note">Bốn cột cuối: điểm đã chuẩn hóa của từng phương pháp (– là phương pháp đó không đề xuất).</p>' : ''}
      ${data.fallback_to_popular ? '<div class="msg warn">Phương pháp này không có ứng viên cho người dùng; dùng Phổ biến thay thế (giống website).</div>' : ''}
      <p class="note">${data.cached ? 'Lấy từ bộ nhớ đệm.' : `Thời gian tính: ${fmtNum(data.elapsed_ms)} ms.`} Neo4j trả asin và điểm; MongoDB bổ sung tên phim và thống kê.</p>
      ${productTable(items, { extra })}`);
  }).catch((err) => { if (alive(token)) setHTML('recList', errorBox(err)); });

  const userTask = apiFetch(`/api/users/${encodeURIComponent(user)}/profile?limit=8`).then(({ data }) => {
    if (!alive(token)) return;
    const u = data.user;
    setHTML('recUser', `<dl class="facts"><dt>Mã</dt><dd>${esc(u.reviewerID)}</dd><dt>Tên</dt><dd>${esc(u.display_name || '—')}</dd>
      <dt>Số review</dt><dd>${fmtNum(data.total_reviews)}</dd><dt>Điểm TB đã chấm</dt><dd>${fmtScore(u.stats && u.stats.avg_rating)}</dd></dl>
      <h3>Review gần đây</h3>${data.reviews.length ? '<ul class="small">' + data.reviews.map((r) => `<li>${fmtScore(r.overall, 0)}★ — ${movieLink(r.asin, r.product_title)}</li>`).join('') + '</ul>' : '<p class="muted">Chưa có review.</p>'}
      <p>${adminUserLink(u.reviewerID, 'Toàn bộ lịch sử')} · <a href="${hashFor('admin/graph', { user: u.reviewerID })}">Đồ thị</a></p>`);
  }).catch((err) => { if (alive(token)) setHTML('recUser', err.status === 404 ? '<div class="msg warn">Không có người dùng này trong dữ liệu.</div>' : errorBox(err)); });

  await Promise.all([recTask, userTask, loadSimilar(user, 'recSimilar', token)]);
}

async function adminUser(route, token) {
  const uid = route.arg;
  const page = Math.max(1, Number(route.params.get('page')) || 1);
  const { data } = await apiFetch(`/api/users/${encodeURIComponent(uid)}/profile?page=${page}&limit=20`);
  if (!alive(token)) return;
  const u = data.user;
  view(`<h1>Người dùng ${esc(u.display_name)}</h1><p class="lead">${esc(u.reviewerID)}${u.is_demo ? ' · tài khoản tạo trên web' : ''}</p>
    <div class="kpis">${kpi(data.total_reviews, 'review (không tính bản sao)')}${kpi(fmtScore(u.stats && u.stats.avg_rating), 'điểm TB đã chấm')}</div>
    <div class="toolbar"><a class="btn primary" href="${hashFor('admin/recommend', { user: uid })}">Phân tích gợi ý</a><a class="btn" href="${hashFor('admin/graph', { user: uid })}">Xem trên đồ thị</a></div>
    <div class="split" style="margin-top:14px">
      <section class="panel"><h2>Lịch sử review</h2>${reviewList(data.reviews, { showProduct: true, admin: true })}${pagerLinks(page, data.total_reviews, data.limit, (n) => hashFor('admin/user/' + encodeURIComponent(uid), { page: n }))}</section>
      <section class="panel"><h2>Người dùng tương đồng</h2><div id="similarUsers"><p class="muted">Đang tính…</p></div></section>
    </div>`);
  await loadSimilar(uid, 'similarUsers', token);
}

// ------------------------------------------------------------------ Đồ thị
async function adminGraph(route, token) {
  const p = route.params;
  const kind = p.get('user') ? 'user' : 'asin';
  const value = p.get('user') || p.get('asin') || '';
  const samples = await loadSampleUsers();
  if (!alive(token)) return;
  view(`<h1>Khám phá đồ thị Neo4j</h1>
    <section class="panel"><form class="inline" data-form="graph">
      <label>Trung tâm là<select name="kind"><option value="asin" ${kind === 'asin' ? 'selected' : ''}>Phim (ASIN)</option><option value="user" ${kind === 'user' ? 'selected' : ''}>Người dùng (reviewerID)</option></select></label>
      <label class="wide">Mã<input name="value" value="${esc(value)}" required></label>
      <button class="primary" type="submit">Hiển thị</button>
    </form>
    <p class="note">Ví dụ: phim <a href="${hashFor('admin/graph', { asin: 'B00OV3VGP0' })}">B00OV3VGP0 (John Wick)</a>${samples[0] ? `, người dùng <a href="${hashFor('admin/graph', { user: samples[0].reviewerID })}">${esc(samples[0].display_name)}</a>` : ''}.
      Nhấp một nút để xem thuộc tính; nhấp đúp vào phim hoặc người dùng để lấy nút đó làm trung tâm. Người dùng hiện tên công khai trên Amazon; tên chung chung (“Amazon Customer”) kèm 6 ký tự cuối của mã.</p>
    <div class="legend">Nút: ${Object.entries(GRAPH_LABELS).map(([k, l]) => `<span><i style="background:${GRAPH_COLORS[k]}"></i>${esc(l)}</span>`).join('')}</div>
    <div class="legend" style="margin-top:4px">Cạnh: ${Object.entries(EDGE_COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${esc(k)}</span>`).join('')}</div></section>
    ${value ? `<div class="split"><div id="graphCanvas"></div><section class="panel"><h2>Chi tiết</h2><div id="graphInfo"><p class="muted">Nhấp vào một nút hoặc cạnh.</p></div><div id="graphSummary"></div></section></div>` : ''}`);
  state.handlers['form:graph'] = (form) => {
    const fd = new FormData(form);
    go('admin/graph', { [fd.get('kind')]: String(fd.get('value')).trim() });
  };
  if (!value) return;
  const { data } = await apiFetch(`/api/graph/ego?${kind === 'user' ? 'user' : 'asin'}=${encodeURIComponent(value)}&limit=25`);
  if (!alive(token)) return;
  if (!data.nodes.length) { setHTML('graphCanvas', '<div class="msg warn" style="margin:12px">Không tìm thấy nút này trong Neo4j.</div>'); return; }
  if (typeof vis === 'undefined') { setHTML('graphCanvas', '<div class="msg error" style="margin:12px">Không nạp được thư viện vẽ đồ thị (static/vendor/vis-network.min.js).</div>'); return; }
  const counts = {};
  data.edges.forEach((e) => { counts[e.label] = (counts[e.label] || 0) + 1; });
  setHTML('graphSummary', `<h3>Thành phần</h3><p class="small">${fmtNum(data.nodes.length)} nút, ${fmtNum(data.edges.length)} cạnh: ${Object.entries(counts).map(([k, n]) => `${esc(k)} ${n}`).join(', ')}</p>`);
  const nodes = new vis.DataSet(data.nodes.map((n) => ({
    id: n.id, label: n.label, title: n.full_title || n.reviewerID || n.label, shape: 'dot',
    size: n.group.startsWith('Center') ? 22 : (n.group === 'Product' || n.group === 'User' ? 12 : 9),
    color: { background: GRAPH_COLORS[n.group] || '#999', border: '#555' }, font: { size: 11, color: '#1f2933' }, raw: n,
  })));
  const edges = new vis.DataSet(data.edges.map((e, i) => ({
    id: i, from: e.from, to: e.to, title: e.label, arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    width: e.label === 'SIMILAR_TO' || e.label.startsWith('ALSO') ? 2 : 1,
    color: { color: EDGE_COLORS[e.label] || '#b9c1cb', highlight: '#1f2933' }, raw: e,
  })));
  state.network = new vis.Network(document.getElementById('graphCanvas'), { nodes, edges }, {
    physics: { solver: 'forceAtlas2Based', stabilization: { iterations: 200 } }, interaction: { hover: true }, edges: { smooth: false },
  });
  const describe = (obj) => `<dl class="facts">${Object.entries(obj).filter(([k, v]) => !['id', 'label', 'from', 'to'].includes(k) && v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(typeof v === 'number' ? fmtScore(v, Number.isInteger(v) ? 0 : 3) : v)}</dd>`).join('')}</dl>`;
  state.network.on('click', (ev) => {
    if (ev.nodes.length) {
      const n = nodes.get(ev.nodes[0]).raw;
      const link = n.asin ? movieLink(n.asin, 'Mở trang phim') : (n.reviewerID ? adminUserLink(n.reviewerID, 'Mở hồ sơ người dùng') : '');
      setHTML('graphInfo', `<p><b>${esc(GRAPH_LABELS[n.group] || n.group)}</b>: ${esc(n.full_title || n.name || n.reviewerID || n.label)}</p>${describe(n)}<p>${link}</p>`);
    } else if (ev.edges.length) {
      const e = edges.get(ev.edges[0]).raw;
      setHTML('graphInfo', `<p><b>Quan hệ ${esc(e.label)}</b></p>${describe(e)}`);
    }
  });
  state.network.on('doubleClick', (ev) => {
    if (!ev.nodes.length) return;
    const n = nodes.get(ev.nodes[0]).raw;
    if (n.asin) go('admin/graph', { asin: n.asin });
    else if (n.reviewerID) go('admin/graph', { user: n.reviewerID });
  });
}

// ------------------------------------------------------------------ Thống kê
function chart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas || typeof Chart === 'undefined') return;
  state.charts.push(new Chart(canvas, config));
}

async function adminStats(route, token) {
  const { data } = await apiFetch('/api/statistics' + (route.params.get('refresh') ? '?refresh=1' : ''));
  if (!alive(token)) return;
  const a = data.sentiment_alignment || {};
  const c = data.counts || {};
  view(`<h1>Thống kê review</h1>
    <p class="lead">MongoDB Aggregation Pipeline ($facet, $group, $bucket, $unwind) trên ${fmtNum(c.reviews)} review khác nhau (bỏ ${fmtNum(c.copy_rows)} bản sao giữa các ấn bản); kết quả lưu đệm. <a href="${hashFor('admin/stats', { refresh: 1 })}">Tính lại</a></p>
    ${typeof Chart === 'undefined' ? '<div class="msg error">Không nạp được Chart.js (static/vendor/chart.umd.js).</div>' : ''}
    <section class="panel"><h2>Kiểm chứng cảm xúc VADER với số sao</h2>
      <table><tbody>
        <tr><td>Review 4–5 sao được VADER gán nhãn tích cực</td><td class="num">${fmtPct(a.high_star_positive_rate)}</td></tr>
        <tr><td>Review 1–2 sao được gán nhãn tiêu cực</td><td class="num">${fmtPct(a.low_star_negative_rate)}</td></tr>
        <tr><td>Review 1–2 sao không bị gán tích cực</td><td class="num">${fmtPct(a.low_star_non_positive_rate)}</td></tr>
        <tr><td>Mức khớp cực tính chung (4–5 sao ↔ tích cực, 1–2 sao ↔ tiêu cực)</td><td class="num">${fmtPct(a.polarity_agreement_rate)}</td></tr>
      </tbody></table>
      <p class="note">VADER là từ điển tiếng Anh: khớp tốt với review khen, kém với review chê (châm biếm, kể nội dung phim). Review tiếng Việt viết trên web được gắn nhãn “không phải tiếng Anh”, không bị gán nhãn sai.</p></section>
    <div class="grid2">
      <section class="panel"><h2>Phân bố số sao</h2><div class="chart-box"><canvas id="cStars"></canvas></div></section>
      <section class="panel"><h2>Nhãn cảm xúc</h2><div class="chart-box"><canvas id="cSent"></canvas></div></section>
      <section class="panel"><h2>Cảm xúc theo số sao (%)</h2><div class="chart-box"><canvas id="cSentStar"></canvas></div></section>
      <section class="panel"><h2>Số review theo năm</h2><div class="chart-box"><canvas id="cYear"></canvas></div></section>
      <section class="panel"><h2>Thể loại có nhiều tác phẩm nhất</h2><p class="note">Bỏ các nút điều hướng chung của Amazon.</p><div class="chart-box tall"><canvas id="cCat"></canvas></div></section>
      <section class="panel"><h2>Định dạng được review nhiều nhất</h2><div class="chart-box tall"><canvas id="cFmt"></canvas></div></section>
    </div>`);
  if (typeof Chart === 'undefined') return;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = '#5f6b7a';
  const base = () => ({ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } });
  const starRows = (data.stars || []).filter((s) => s._id !== null);
  chart('cStars', { type: 'bar', data: { labels: starRows.map((s) => `${s._id} sao`), datasets: [{ data: starRows.map((s) => s.count), backgroundColor: '#c08a00' }] }, options: base() });
  const sentOrder = ['positive', 'neutral', 'negative', 'unavailable', 'unsupported_language'];
  const sentColors = { positive: '#1e7a3d', neutral: '#a0a7b1', negative: '#b42318', unavailable: '#d8dde3', unsupported_language: '#e8c766' };
  const sent = sentOrder.map((k) => ({ k, n: ((data.sentiment || []).find((s) => s._id === k) || {}).count || 0 })).filter((s) => s.n || ['positive', 'neutral', 'negative'].includes(s.k));
  chart('cSent', { type: 'bar', data: { labels: sent.map((s) => SENTIMENT_ADMIN[s.k]), datasets: [{ data: sent.map((s) => s.n), backgroundColor: sent.map((s) => sentColors[s.k]) }] }, options: base() });
  const byStar = data.sentiment_by_star || [];
  const share = (star, label) => {
    const rows = byStar.filter((r) => Number(r._id.star) === star && ['positive', 'neutral', 'negative'].includes(r._id.sentiment));
    const total = rows.reduce((t, r) => t + r.count, 0) || 1;
    return ((rows.find((r) => r._id.sentiment === label) || {}).count || 0) / total * 100;
  };
  chart('cSentStar', { type: 'bar', data: { labels: [1, 2, 3, 4, 5].map((s) => `${s} sao`), datasets: ['positive', 'neutral', 'negative'].map((l) => ({ label: SENTIMENT_ADMIN[l], data: [1, 2, 3, 4, 5].map((s) => share(s, l)), backgroundColor: sentColors[l] })) },
    options: { ...base(), plugins: { legend: { display: true, position: 'bottom' } }, scales: { x: { stacked: true }, y: { stacked: true, max: 100, ticks: { callback: (v) => v + '%' } } } } });
  const years = {};
  (data.timeline || []).forEach((t) => { if (t._id) { const y = t._id.slice(0, 4); years[y] = (years[y] || 0) + t.count; } });
  const ys = Object.keys(years).sort();
  chart('cYear', { type: 'bar', data: { labels: ys, datasets: [{ data: ys.map((y) => years[y]), backgroundColor: '#1f5fbf' }] }, options: base() });
  const cats = (data.categories || []).slice(0, 12);
  chart('cCat', { type: 'bar', data: { labels: cats.map((x) => x._id), datasets: [{ data: cats.map((x) => x.count), backgroundColor: '#5f6b7a' }] }, options: { ...base(), indexAxis: 'y' } });
  const fmts = (data.formats || []).slice(0, 10);
  chart('cFmt', { type: 'bar', data: { labels: fmts.map((x) => x._id), datasets: [{ data: fmts.map((x) => x.count), backgroundColor: '#2f8f6a' }] }, options: { ...base(), indexAxis: 'y' } });
}

// ------------------------------------------------------------------ Thực nghiệm
const METHOD_ORDER = ['popular', 'collaborative', 'related', 'content', 'hybrid'];

function metricRow(name, m, keys, best) {
  return `<tr><td>${esc(name)}</td>${keys.map((k) => {
    const v = (m || {})[k];
    return `<td class="num">${v === best[k] ? '<b>' : ''}${fmtScore(v, 4)}${v === best[k] ? '</b>' : ''}</td>`;
  }).join('')}`;
}

function evaluationSection(ev) {
  if (!ev || !ev.metrics) return '<p class="muted">Chưa chạy đánh giá.</p>';
  const pr = ev.protocol || {};
  const keys = ['precision@10', 'recall@10', 'ndcg@10', 'hit_rate@10'];
  const best = {};
  keys.forEach((k) => { best[k] = Math.max(...METHOD_ORDER.map((m) => (ev.metrics[m] || {})[k] || 0)); });
  const rows = METHOD_ORDER.filter((m) => ev.metrics[m]).map((m) => metricRow(METHOD_INFO[m].name, ev.metrics[m], keys, best)
    + `<td class="num">${m === 'popular' ? '—' : fmtPct((ev.personalized_coverage || {})[m])}</td></tr>`).join('');
  const cf = ev.cf_shrinkage; const hn = ev.hybrid_normalization; const parity = ev.parity_check; const leak = ev.residual_copy_leakage;
  const ms = ev.cf_min_support;
  const pop = (ev.metrics.popular || {})['ndcg@10']; const hyb = (ev.metrics.hybrid || {})['ndcg@10'];
  return `<ul class="small">
      <li>${esc(pr.unit || '')}</li><li>${esc(pr.split || '')}</li><li>${esc(pr.relevance || '')}</li><li>${esc(pr.eligible_users || '')}</li>
      <li>${esc(pr.implementation || '')}</li><li>${esc(pr.popular_baseline || '')}</li><li>${esc(pr.fallback || '')}</li>
      <li>${fmtNum(pr.test_users)} người dùng kiểm thử, ${fmtNum(pr.validation_users)} người dùng validation (tách rời), chọn ngẫu nhiên trong ${fmtNum(pr.total_eligible_users)} người dùng đủ điều kiện (seed ${esc(pr.seed)}); trung bình ${fmtScore(pr.avg_relevant_items_per_test_user, 2)} tác phẩm phù hợp mỗi người.</li>
    </ul>
    <div class="table-wrap"><table><thead><tr><th>Phương pháp</th><th class="num">Precision@10</th><th class="num">Recall@10</th><th class="num">NDCG@10</th><th class="num">HitRate@10</th><th class="num">Có gợi ý riêng</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note">"Có gợi ý riêng": tỉ lệ người dùng mà phương pháp tự tạo được danh sách (còn lại dùng Phổ biến). ${pop && hyb ? `NDCG@10 của Hybrid gấp ${fmtScore(hyb / pop, 1)} lần Phổ biến.` : ''}</p>
    ${leak ? `<p class="small">Kiểm tra rò rỉ: ${fmtNum(leak.identical_to_a_train_review)} / ${fmtNum(leak.relevant_test_reviews)} review phù hợp trong Test giống hệt một review Train của chính người đó (${fmtPct(leak.rate, 2)}).</p>` : ''}
    ${cf ? `<h3>Chọn hệ số co λ của CF trên tập validation</h3>
      <div class="table-wrap"><table><thead><tr><th>λ</th><th class="num">Precision@10</th><th class="num">Recall@10</th><th class="num">NDCG@10</th></tr></thead><tbody>
      ${Object.entries(cf.validation || {}).map(([s, m]) => `<tr><td>${fmtNum(Number(s))}${Number(s) === cf.selected ? ' <b>(chọn)</b>' : ''}</td><td class="num">${fmtScore(m['precision@10'], 4)}</td><td class="num">${fmtScore(m['recall@10'], 4)}</td><td class="num">${fmtScore(m['ndcg@10'], 4)}</td></tr>`).join('')}
      </tbody></table></div><p class="note">${esc(cf.selected_by)}. Website đang dùng λ = ${esc(cf.production_value)}${cf.production_matches ? ' (trùng giá trị đã chọn)' : ' — KHÁC giá trị đã chọn'}.</p>` : ''}
    ${ms ? `<h3>Chọn số láng giềng tối thiểu cùng thích của CF (validation, λ đã chọn)</h3>
      <div class="table-wrap"><table><thead><tr><th>Số láng giềng tối thiểu</th><th class="num">Precision@10</th><th class="num">Recall@10</th><th class="num">NDCG@10</th></tr></thead><tbody>
      ${Object.entries(ms.validation || {}).map(([n, m]) => `<tr><td>${esc(n)}${Number(n) === ms.selected ? ' <b>(chọn)</b>' : ''}</td><td class="num">${fmtScore(m['precision@10'], 4)}</td><td class="num">${fmtScore(m['recall@10'], 4)}</td><td class="num">${fmtScore(m['ndcg@10'], 4)}</td></tr>`).join('')}
      </tbody></table></div><p class="note">${esc(ms.meaning)} Website đang dùng ${esc(ms.production_value)}${ms.production_matches ? ' (trùng giá trị đã chọn)' : ' — KHÁC giá trị đã chọn'}.</p>` : ''}
    ${hn ? `<h3>Chọn cách chuẩn hóa điểm của Hybrid (validation)</h3>
      <div class="table-wrap"><table><thead><tr><th>Cách chuẩn hóa</th><th class="num">Precision@10</th><th class="num">Recall@10</th><th class="num">NDCG@10</th></tr></thead><tbody>
      ${Object.entries(hn.validation || {}).map(([k, m]) => `<tr><td>${esc((hn.options || {})[k] || k)}${k === hn.selected ? ' <b>(chọn)</b>' : ''}</td><td class="num">${fmtScore(m['precision@10'], 4)}</td><td class="num">${fmtScore(m['recall@10'], 4)}</td><td class="num">${fmtScore(m['ndcg@10'], 4)}</td></tr>`).join('')}
      </tbody></table></div><p class="note">Website đang dùng “${esc(hn.production_value)}”${hn.production_matches ? ' (trùng giá trị đã chọn)' : ' — KHÁC giá trị đã chọn'}.</p>` : ''}
    ${parity ? `<h3>Kiểm chứng bản Python trùng với Cypher của website</h3>
      <div class="table-wrap"><table><thead><tr><th>Phương pháp</th><th class="num">Top-10 giống hệt</th><th class="num">Jaccard Top-10 TB</th><th class="num">Thời gian Cypher TB</th></tr></thead><tbody>
      ${METHOD_ORDER.filter((m) => parity.methods[m]).map((m) => `<tr><td>${esc(METHOD_INFO[m].name)}</td><td class="num">${fmtPct(parity.methods[m].identical_top_k_rate)}</td><td class="num">${fmtScore(parity.methods[m].mean_jaccard_top_k, 3)}</td><td class="num">${fmtScore(parity.methods[m].avg_cypher_seconds, 2)} s</td></tr>`).join('')}
      </tbody></table></div><p class="note">${fmtNum(parity.users)} người dùng ngẫu nhiên, dữ liệu đầy đủ. ${esc(parity.note)}</p>` : ''}
    ${(ev.limitations || []).length ? `<h3>Hạn chế cần lưu ý</h3><ul class="small">${ev.limitations.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>` : ''}`;
}

function speedupText(q) {
  return Number(q.after.ms) === 0 ? `≥ ×${fmtNum(q.speedup)}` : `×${fmtScore(q.speedup, 1)}`;
}

function benchmarkSection(bm) {
  if (!bm || !bm.mongodb_explain || !bm.method) return '<p class="muted">Chưa chạy phép đo.</p>';
  const mongoRows = bm.mongodb_explain.flatMap((s) => Object.values(s.queries).map((q) => `<tr><td>${esc(s.scale)}</td><td class="num">${fmtNum(s.documents)}</td><td>${esc(q.description)}</td>
    <td class="num">${fmtMs(q.before.ms)}</td><td class="num">${fmtNum(q.before.docs_examined)}</td><td class="small">${esc(q.before.plan)}</td>
    <td class="num">${fmtMs(q.after.ms)}</td><td class="num">${fmtNum(q.after.keys_examined)} / ${fmtNum(q.after.docs_examined)}</td><td class="small">${esc(q.after.plan)}</td>
    <td class="num"><b>${speedupText(q)}</b></td></tr>`)).join('');
  const neoRows = bm.neo4j_profile.flatMap((s) => Object.values(s.queries).map((q) => `<tr><td>${esc(s.scale)}</td><td class="num">${fmtNum(s.relationships)} / ${fmtNum(s.products)}</td><td>${esc(q.description)}</td>
    <td class="num">${fmtMs(q.before.ms)}</td><td class="num">${fmtNum(q.before.db_hits)}</td><td class="small">${esc(q.before.plan)}</td>
    <td class="num">${fmtMs(q.after.ms)}</td><td class="num">${fmtNum(q.after.db_hits)}</td><td class="small">${esc(q.after.plan)}</td>
    <td class="num"><b>${speedupText(q)}</b></td></tr>`)).join('');
  const neoQueries = bm.neo4j_profile[0] ? Object.values(bm.neo4j_profile[0].queries) : [];
  return `<ul class="small"><li>${esc(bm.method.subsets)}</li><li>${esc(bm.method.measurement)}</li></ul>
    <h3>MongoDB — explain("executionStats")</h3>
    <div class="table-wrap"><table><thead><tr><th>Mức</th><th class="num">Số review</th><th>Truy vấn</th><th class="num">Trước</th><th class="num">Docs đọc</th><th>Kế hoạch</th><th class="num">Sau</th><th class="num">Keys / docs</th><th>Kế hoạch</th><th class="num">Nhanh hơn</th></tr></thead><tbody>${mongoRows}</tbody></table></div>
    <h3>Neo4j — PROFILE</h3>
    <div class="table-wrap"><table><thead><tr><th>Mức</th><th class="num">Quan hệ / phim</th><th>Truy vấn</th><th class="num">Trước</th><th class="num">DB hits</th><th>Kế hoạch</th><th class="num">Sau</th><th class="num">DB hits</th><th>Kế hoạch</th><th class="num">Nhanh hơn</th></tr></thead><tbody>${neoRows}</tbody></table></div>
    <details><summary>Truy vấn và index Neo4j đã dùng</summary>${neoQueries.map((q) => `<pre>${esc(q.query)}\n${esc(q.index)}</pre>`).join('')}</details>`;
}

function comparisonSection(cmp) {
  if (!cmp || !cmp.tasks) return '<p class="muted">Chưa chạy so sánh.</p>';
  const tasks = Object.values(cmp.tasks);
  const rows = tasks.map((t) => `<tr><td>${esc(t.description)}</td>
    <td class="num">${fmtMs(t.mongodb.median_ms)}</td><td class="num">${fmtNum(t.mongodb.stages_top_level)} (${fmtNum(t.mongodb.stages_total)} kể cả lồng)</td>
    <td class="num">${fmtMs(t.neo4j.median_ms)}</td><td class="num">${fmtNum(t.neo4j.cypher_clauses)}</td>
    <td>${t.results_match ? '<span class="ok">Khớp</span>' : '<b class="bad">Không khớp</b>'} (${fmtNum(t.rows)} dòng)</td><td><b>${esc(t.faster_engine)}</b> ×${fmtScore(t.speedup_ratio, 1)}</td></tr>`).join('');
  return `<p class="note">Thời gian là trung vị ${fmtNum(cmp.parameters.runs_per_query)} lần chạy sau 1 lần khởi động. Người dùng mẫu ${esc(cmp.parameters.user)}, phim mẫu ${esc(cmp.parameters.asin)}.</p>
    <div class="table-wrap"><table><thead><tr><th>Bài toán</th><th class="num">MongoDB</th><th class="num">Số stage</th><th class="num">Neo4j</th><th class="num">Mệnh đề Cypher</th><th>Kết quả</th><th>Nhanh hơn</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${tasks.map((t) => `<details><summary>${esc(t.description)} — xem hai truy vấn</summary><h3>MongoDB Aggregation</h3><pre>${esc(JSON.stringify(t.mongodb.pipeline, null, 2))}</pre><h3>Neo4j Cypher</h3><pre>${esc(t.neo4j.cypher || '')}</pre></details>`).join('')}`;
}

function communityTable(communities) {
  if (!communities || !communities.length) return '<p class="muted">Chưa chạy Louvain.</p>';
  const rows = communities.map((c) => {
    const cats = (c.distinctive_categories || []).map((d) => `${esc(d.category)} <small class="muted">×${fmtScore(d.lift, 1)}</small>`).join(', ');
    const samples = (c.sample_products || []).slice(0, 3).map((p) => movieLink(p.asin, p.title)).join('; ');
    return `<tr><td><a href="#/admin/community/${encodeURIComponent(c.community)}">#${esc(c.community)}</a></td><td class="num">${fmtNum(c.size)}</td>`
      + `<td class="num">${fmtScore(c.avg_rating)}</td><td>${cats || '—'}</td><td>${samples}</td></tr>`;
  }).join('');
  return `<div class="table-wrap"><table><thead><tr><th>Cộng đồng</th><th class="num">Số phim</th><th class="num">Điểm TB</th><th>Danh mục đặc trưng (độ nâng)</th><th>Phim tiêu biểu</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function analyticsSection(ga, sim) {
  if (!ga || !ga.pagerank) return '<p class="muted">Chưa chạy phân tích đồ thị.</p>';
  const pr = ga.pagerank; const lv = ga.louvain;
  return `<div class="grid2">
    <div><h3>PageRank (mạng ALSO_BOUGHT / ALSO_VIEWED có hướng)</h3>
      <p class="small">${fmtNum(pr.projection.nodeCount)} phim, ${fmtNum(pr.projection.relationshipCount)} cạnh; damping 0,85; ${fmtNum(pr.ranIterations)} vòng lặp; ${pr.didConverge ? 'đã hội tụ' : '<b>chưa hội tụ</b>'}.</p>
      ${productTable((pr.top_products || []).slice(0, 10).map((p) => ({ asin: p.asin, title: p.title, stats: { avg_rating: p.avg_rating, review_count: p.review_count, pagerank: p.pagerank }, degree: p.degree })),
        { extra: [col('PageRank', (p) => fmtScore(p.stats.pagerank, 2)), col('Liên kết', (p) => fmtNum(p.degree))] })}</div>
    <div><h3>Louvain (mạng vô hướng)</h3>
      <p class="small">Modularity ${fmtScore(lv.modularity, 3)}, ${fmtNum(lv.ranLevels)} mức; ${fmtNum(lv.communityCount)} cộng đồng, trong đó ${fmtNum(lv.isolated_products)} phim không có liên kết và
        ${fmtNum(lv.communities_with_5_or_more)} cộng đồng có từ 5 phim; 10 cộng đồng lớn nhất chứa ${fmtPct(lv.top10_share_of_connected)} số phim có liên kết.</p>
      ${sim ? `<h3>GDS Node Similarity (SIMILAR_TO)</h3><p class="small">Chiếu ${fmtNum(sim.projected && sim.projected.nodeCount)} nút (người dùng có ≥ ${fmtNum(sim.min_reviews_filter)} review và toàn bộ phim), Jaccard trên tác phẩm ≥ 4 sao,
        topK ${fmtNum(sim.topK)}, ngưỡng ${fmtScore(sim.similarityCutoff, 2)}: ghi ${fmtNum(sim.relationshipsWritten)} quan hệ cho ${fmtNum(sim.users_with_similar_to)} người dùng (${fmtPct(sim.coverage)}).</p>` : ''}</div></div>`;
}

async function adminExperiments(route, token) {
  const { data } = await apiFetch('/api/experiments');
  if (!alive(token)) return;
  const imp = data.import || {};
  const rec = data.reconciliation || {};
  const checks = rec.checks || {};
  const ed = data.editions || {};
  view(`<h1>Thực nghiệm</h1>
    <p class="lead">Số liệu đọc từ các tệp kết quả trong reports/, do <code>scripts/run_session4.py</code> và các lệnh <code>python -m amazon_movies …</code> sinh ra trên toàn bộ dữ liệu.</p>
    <section class="panel"><h2>1. Dữ liệu và đối soát hai CSDL</h2>
      <div class="grid2"><table><tbody>
        <tr><td>Dòng review nguồn (5-core)</td><td class="num">${fmtNum(imp.review_raw_rows)}</td></tr>
        <tr><td>Review không có metadata hợp lệ (bỏ)</td><td class="num">${fmtNum(imp.review_without_metadata)}</td></tr>
        <tr><td>Dòng trùng hệt nhau trong tệp nguồn (gộp)</td><td class="num">${fmtNum(imp.exact_duplicate_source_rows)}</td></tr>
        <tr><td>Dòng review trong MongoDB</td><td class="num">${fmtNum(ed.review_rows || imp.reviews)}</td></tr>
        <tr><td>— trong đó bản sao giữa các ấn bản</td><td class="num">${fmtNum(ed.copy_rows)}</td></tr>
        <tr><td>Review khác nhau</td><td class="num">${fmtNum(ed.unique_reviews)}</td></tr>
        <tr><td>Mã sản phẩm / tác phẩm / người dùng</td><td class="num">${fmtNum(imp.products)} / ${fmtNum(ed.works_total)} / ${fmtNum(imp.users)}</td></tr>
      </tbody></table>
      <table><thead><tr><th>Kiểm tra</th><th class="num">MongoDB</th><th class="num">Neo4j</th><th>Kết quả</th></tr></thead><tbody>
        ${['Product', 'User', 'REVIEWED'].map((k) => `<tr><td>${k}</td><td class="num">${fmtNum((rec.mongo || {})[k])}</td><td class="num">${fmtNum(k === 'REVIEWED' ? (rec.neo4j_relationships || {})[k] : (rec.neo4j_nodes || {})[k])}</td><td>${checks[k] ? 'Khớp' : '<b>Lệch</b>'}</td></tr>`).join('')}
        <tr><td>Không trùng review_id trong Neo4j</td><td></td><td></td><td>${checks.no_duplicate_review_ids ? 'Đạt' : '<b>Không đạt</b>'}</td></tr>
        <tr><td>Mọi review đã đồng bộ</td><td></td><td></td><td>${checks.all_reviews_synced ? 'Đạt' : '<b>Còn review chờ</b>'}</td></tr>
      </tbody></table></div></section>
    <section class="panel"><h2>2. Chất lượng gợi ý (Precision@10, Recall@10, NDCG@10)</h2>${evaluationSection(data.evaluation)}</section>
    <section class="panel"><h2>3. Hiệu năng truy vấn trước và sau khi tạo index (10%, 50%, 100% dữ liệu)</h2>${benchmarkSection(data.index_benchmark)}</section>
    <section class="panel"><h2>4. So sánh MongoDB và Neo4j trên cùng bài toán</h2>${comparisonSection(data.db_comparison)}</section>
    <section class="panel"><h2>5. Phân tích đồ thị (GDS)</h2>${analyticsSection(data.graph_analytics, data.similarity)}</section>`);
}

async function adminCommunities(route, token) {
  const { data } = await apiFetch('/api/analytics/communities');
  if (!alive(token)) return;
  view(`<h1>Cộng đồng phim (GDS Louvain)</h1>
    <p class="lead">Nhóm phim thường được mua/xem cùng nhau trong mạng ALSO_BOUGHT / ALSO_VIEWED. Danh mục đặc trưng là danh mục có tỉ lệ trong cộng đồng cao hơn hẳn toàn bộ dữ liệu (độ nâng).</p>
    <section class="panel">${analyticsSection(data, null)}</section>
    <section class="panel"><h2>10 cộng đồng lớn nhất</h2>${communityTable((data.louvain || {}).top_communities)}</section>`);
}

async function adminCommunity(route, token) {
  const { data } = await apiFetch(`/api/analytics/communities?community=${encodeURIComponent(route.arg)}&limit=50`);
  if (!alive(token)) return;
  view(`<p><a href="#/admin/communities">← Cộng đồng phim</a></p><h1>Cộng đồng #${esc(data.community)}</h1>
    <p class="lead">${fmtNum(data.size)} mã sản phẩm được Louvain gom vào cùng một nhóm. Dưới đây là 50 mã có PageRank cao nhất.</p>
    <section class="panel">${productTable(data.items, { extra: [col('PageRank', (p) => fmtScore(p.stats && p.stats.pagerank, 2)), col('Liên kết', (p) => fmtNum(p.stats && p.stats.copurchase_degree))] })}</section>`);
}

// ------------------------------------------------------------------ thao tác chung
const actions = {
  back() {
    if (history.length > 1) history.back();
    else go('');
  },
  async vote(el) {
    if (!isUser()) { toast('Hãy đăng nhập để bình chọn đánh giá hữu ích.'); return; }
    el.disabled = true;
    try {
      const { data } = await apiFetch(`/api/reviews/${encodeURIComponent(el.dataset.id)}/helpful`, { method: 'POST', body: {} });
      el.textContent = `Đã bình chọn (${fmtNum(data.vote)})`;
    } catch (err) {
      toast(err.message);
      el.disabled = false;
    }
  },
  'edit-review'(el) {
    const r = state.reviewIndex[el.dataset.id];
    if (!r) return;
    const form = document.getElementById('reviewForm');
    if (form && parseHash().name === 'movie') fillReviewForm(r);
    else go('movie/' + encodeURIComponent(r.asin), { edit: r.review_id });
  },
  async 'delete-review'(el) {
    const r = state.reviewIndex[el.dataset.id];
    if (!r || !window.confirm(`Xóa đánh giá ${fmtScore(r.overall, 0)} sao cho “${r.product_title || 'phim này'}”? Không thể hoàn tác.`)) return;
    el.disabled = true;
    try {
      await apiFetch('/api/reviews/' + encodeURIComponent(r.review_id), { method: 'DELETE' });
      toast('Đã xóa đánh giá.');
      render();
    } catch (err) {
      toast(err.message);
      el.disabled = false;
    }
  },
  async 'quick-rate'(el) {
    const group = el.closest('.rate-buttons');
    group.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    try {
      await apiFetch('/api/reviews', { method: 'POST', body: { asin: el.dataset.asin, overall: Number(el.dataset.stars), summary: '', reviewText: '' } });
      group.innerHTML = `<span class="ok">Đã chấm ${esc(el.dataset.stars)}★</span>`;
      const counter = document.getElementById('ratedCount');
      if (counter) counter.textContent = fmtNum(Number(counter.textContent.replace(/\D/g, '')) + 1);
    } catch (err) {
      toast(err.message);
      group.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  },
  scroll(el) {
    const target = document.getElementById(el.dataset.target);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  },
  expand(el) {
    const r = state.reviewIndex[el.dataset.id];
    const target = el.closest('.review').querySelector('.text');
    if (r && target) { target.textContent = r.reviewText; el.remove(); }
  },
  logout() {
    const wasAdmin = isAdmin();
    saveAuth(null);
    toast('Đã đăng xuất.');
    if (wasAdmin) go('');
    else render();
  },
  'form:top-search'(form) {
    const q = String(new FormData(form).get('q') || '').trim();
    go('search', q ? { q } : {});
  },
  async 'form:login'(form) {
    try {
      const { data } = await apiFetch('/api/auth/login', { method: 'POST', body: Object.fromEntries(new FormData(form)) });
      saveAuth({ token: data.token, role: data.role, reviewerID: data.reviewerID, username: data.username, display_name: data.display_name });
      toast(data.role === 'admin' ? 'Đã đăng nhập tài khoản quản trị.' : 'Đăng nhập thành công.');
      if (data.role === 'admin' && parseHash().area !== 'admin') go('admin');
      else render();
    } catch (err) { setHTML('loginMsg', errorBox(err)); }
  },
  async 'form:register'(form) {
    try {
      const { data } = await apiFetch('/api/auth/register', { method: 'POST', body: Object.fromEntries(new FormData(form)) });
      saveAuth({ token: data.token, role: 'user', reviewerID: data.reviewerID, username: data.username, display_name: data.display_name });
      toast(`Chào ${data.display_name}! Hãy chấm vài phim để nhận gợi ý.`);
      go('for-you');
    } catch (err) { setHTML('registerMsg', errorBox(err)); }
  },
};

function renderAccountBox() {
  const box = document.getElementById('accountBox');
  if (!box) return;
  if (!state.auth) { box.innerHTML = '<a href="#/account">Đăng nhập / Đăng ký</a>'; return; }
  const name = state.auth.display_name || state.auth.username || '';
  box.innerHTML = isAdmin()
    ? `Quản trị: <a href="#/admin">${esc(state.auth.username)}</a> · <a href="#" data-action="logout">Đăng xuất</a>`
    : `Xin chào, <a href="#/account">${esc(name)}</a> · <a href="#" data-action="logout">Đăng xuất</a>`;
}

function init() {
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const fn = state.handlers[el.dataset.action] || actions[el.dataset.action];
    if (fn) { e.preventDefault(); fn(el, e); }
  });
  document.addEventListener('submit', (e) => {
    const form = e.target.closest('form[data-form]');
    if (!form) return;
    e.preventDefault();
    const fn = state.handlers['form:' + form.dataset.form] || actions['form:' + form.dataset.form];
    if (fn) fn(form);
  });
  document.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change]');
    const fn = el && state.handlers['change:' + el.dataset.change];
    if (fn) fn(el);
  });
  window.addEventListener('hashchange', render);
  renderAccountBox();
  render();
}

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', init);
if (typeof module !== 'undefined') module.exports = { esc, parseHash, workStats, movieTable, reviewList, stars, fmtPrice, deepestPath, hashFor, renderReviewItem };
