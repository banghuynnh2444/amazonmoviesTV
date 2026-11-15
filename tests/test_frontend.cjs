// Kiểm thử giao diện bằng Node.js (không cần trình duyệt hay CSDL).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../amazon_movies/static/app.js'), 'utf8');

function sandbox(stored, hash = '#/') {
  const elements = {};
  const context = {
    console, Intl, Date, setTimeout, clearTimeout, URLSearchParams,
    location: { hash },
    localStorage: { getItem: () => stored, setItem() {}, removeItem() {} },
    document: {
      addEventListener() {},
      getElementById: (id) => elements[id] || (elements[id] = { innerHTML: '', textContent: '', classList: { add() {}, remove() {}, toggle() {} } }),
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, elements };
}

const { context } = sandbox(null);
assert.equal(context.formatDate('Sun, 01 Mar 2015 00:00:00 GMT'), '01/03/2015');
assert.equal(context.formatDate(1425168000000), '01/03/2015');
assert.equal(context.formatDate('invalid'), '');
assert.equal(context.formatDate(null), '');
assert.equal(context.esc(`<a href="x" onclick='y'>&`), '&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;');
assert.equal(context.hashFor('search', { q: 'star wars', category: '', page: 2 }), '#/search?q=star+wars&page=2');
assert.equal(context.stars(4.6), '★★★★★');
assert.equal(context.stars(3.2), '★★★☆☆');
console.log('PASS: định dạng ngày, escape HTML, đường dẫn, số sao.');

// Định tuyến: khu người dùng và khu quản trị tách riêng.
{
  const user = sandbox(null, '#/movie/B00X?edit=r1').context.parseHash();
  assert.equal(user.area, 'user'); assert.equal(user.name, 'movie'); assert.equal(user.arg, 'B00X'); assert.equal(user.params.get('edit'), 'r1');
  const admin = sandbox(null, '#/admin/user/A123').context.parseHash();
  assert.equal(admin.area, 'admin'); assert.equal(admin.name, 'user'); assert.equal(admin.arg, 'A123');
  assert.equal(sandbox(null, '#/admin').context.parseHash().name, 'overview');
  console.log('PASS: định tuyến #/… (người dùng) và #/admin/… (quản trị).');
}

// Phiên đăng nhập: phiên cũ không có role được coi là người dùng thường; phiên hỏng bị bỏ.
assert.equal(sandbox('{invalid stored session').context.readStoredAuth(), null);
assert.equal(sandbox(JSON.stringify({ token: 't', reviewerID: 'DEMO_X' })).context.readStoredAuth().role, 'user');
assert.equal(sandbox(JSON.stringify({ token: 't', role: 'admin', username: 'admin' })).context.readStoredAuth().role, 'admin');

// Danh sách phim cho người dùng: điểm theo tác phẩm, có lý do gợi ý, không lộ mã ASIN hay thuật ngữ kỹ thuật.
{
  const html = context.movieTable([{ asin: 'B00SECRET', title: 'Alien <1979>', brand: 'Sigourney Weaver', formats: ['DVD'], price_any: 9.5,
    stats: { avg_rating: 2, review_count: 99, work_avg: 4.6, work_reviews: 1234 }, _reasons: ['Thường được mua/xem cùng “Aliens”'] }],
    { reasons: (p) => p._reasons });
  assert.match(html, /Alien &lt;1979&gt;/);
  assert.match(html, /1\.234/);
  assert.match(html, /4,6/);
  assert.match(html, /\$9\.50/);
  assert.match(html, /Thường được mua\/xem cùng/);
  assert.doesNotMatch(html, />B00SECRET</);
  assert.doesNotMatch(html, /PageRank|ASIN|Neo4j|MongoDB|Cypher/);
  console.log('PASS: bảng phim dùng điểm tác phẩm, hiện lý do, không lộ ASIN/thuật ngữ.');
}

// Đánh giá: nút sửa/xóa cho đánh giá của mình, nút hữu ích cho người khác, escape nội dung.
vm.runInContext("state.auth = {reviewerID:'DEMO_TEST', token:'t', role:'user'}", context);
const review = { review_id: 'r1', reviewerID: 'DEMO_TEST', display_name: 'Tôi', asin: 'B00000JNTX', overall: 5, vote: 3,
  summary: `It's "great" & <b>safe</b>`, reviewText: 'x'.repeat(800), review_date: 'Sun, 01 Mar 2015 00:00:00 GMT',
  sentiment: { label: 'positive', compound: 0.9 } };
const own = context.renderReviewItem(review);
assert.match(own, /data-action="edit-review" data-id="r1"/);
assert.match(own, /data-action="delete-review" data-id="r1"/);
assert.match(own, /data-action="expand"/);
assert.doesNotMatch(own, /<b>safe<\/b>/);
assert.match(own, /&lt;b&gt;safe&lt;\/b&gt;/);
assert.doesNotMatch(own, /onclick=/);
assert.match(own, /01\/03\/2015/);
assert.doesNotMatch(own, /0,90/);  // người dùng không thấy điểm compound
const other = context.renderReviewItem({ ...review, review_id: 'r2', reviewerID: 'A1', display_name: 'Amazon Customer ·ABC123', reviewText: 'short' });
assert.match(other, /data-action="vote" data-id="r2"/);
assert.match(other, /#\/reviewer\/A1/);
assert.match(other, /Amazon Customer ·ABC123/);
assert.doesNotMatch(other, /edit-review|delete-review/);
const adminView = context.renderReviewItem({ ...review, review_id: 'r3', reviewerID: 'A1', reviewText: 'short', sentiment: { label: 'unsupported_language', compound: null } }, { admin: true });
assert.match(adminView, /#\/admin\/user\/A1/);
assert.match(adminView, /Không phải tiếng Anh/);
assert.doesNotMatch(adminView, /data-action="vote"/);
console.log('PASS: nút sửa/xóa/bình chọn, tên người đánh giá, nhãn cảm xúc ở hai khu.');

async function latestSearchWins() {
  const { context: ctx, elements } = sandbox(null);
  const pending = [];
  ctx.apiFetch = () => new Promise((resolve) => pending.push(resolve));
  const older = ctx.runProductSearch({ q: 'older' });
  const newer = ctx.runProductSearch({ q: 'newer' });
  pending[1]({ data: { items: [{ asin: 'NEW', title: 'New result', stats: {} }], total: 1, page: 1, limit: 20 } });
  await newer;
  pending[0]({ data: { items: [{ asin: 'OLD', title: 'Old result', stats: {} }], total: 1, page: 1, limit: 20 } });
  await older;
  assert.match(elements.searchResults.innerHTML, /New result/);
  assert.doesNotMatch(elements.searchResults.innerHTML, /Old result/);
  assert.doesNotMatch(elements.searchResults.innerHTML, /Trang sau/);
  console.log('PASS: phản hồi tìm kiếm đến muộn không ghi đè kết quả mới.');
}
latestSearchWins().catch((error) => { console.error(error); process.exitCode = 1; });
