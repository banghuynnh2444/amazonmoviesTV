"""Từ khóa nổi bật trong review: TF-IDF theo tần suất tài liệu.

Bảng IDF được ước lượng một lần trên mẫu ngẫu nhiên review (lệnh `keyword-idf`) và lưu ở
collection meta. Với mỗi phim: điểm = (số review của phim có từ đó / số review) × IDF, tính
riêng cho toàn bộ review, review tích cực và review tiêu cực (nhãn VADER).
"""
from collections import Counter
from datetime import datetime, timezone
import math, re, time

TOKEN = re.compile(r'[a-z]{3,}')
STOPWORDS = set('''
a about above after again against all almost alone along already also although always am among an and another any anybody
anyone anything anyway anywhere are aren around as at back be became because become becomes been before behind being below
beside besides between beyond both but by can cannot could couldn did didn do does doesn doing don done down during each
either else enough even ever every everyone everything except few find first for former from further get gets getting give
given go goes going gone got had hadn has hasn have haven having he her here hers herself him himself his how however i if in
into is isn it its itself just keep last least less let like likely made make makes many may maybe me might mine more most
mostly much must my myself near need neither never next no nobody none nor not nothing now of off often on once one only onto
or other others otherwise our ours ourselves out over own per perhaps please put quite rather really said same say says see
seem seemed seems seen several shall she should shouldn show since so some somehow someone something sometimes somewhat
still such take than that the their theirs them themselves then there therefore these they thing things think this those
though through thus to together too toward towards under until up upon us use used using very via was wasn way we well were
weren what whatever when whenever where whether which while who whoever whole whom whose why will with within without won
would wouldn yet you your yours yourself yourselves ive ill youre theyre thats theres whats isnt dont doesnt didnt cant wont
lot lots bit yes etc get also ever anyone else another let lets got gotten saw seen watch watched watching watches view viewed
movie movies film films dvd dvds blu ray bluray disc discs video videos amazon prime buy bought purchase purchased order ordered
copy version edition release released time times year years day days people person way ways part parts end one two three four
five first second third star stars review reviews rating rated thing stuff guy guys series season seasons episode episodes
show shows'''.split())


def tokens(text):
    return {t for t in TOKEN.findall((text or '').lower()) if t not in STOPWORDS}


def build_idf(db, sample=150000):
    started = time.time()
    df = Counter()
    documents = 0
    cursor = db.reviews.aggregate([{'$match': {'is_demo': False}}, {'$sample': {'size': sample}}, {'$project': {'reviewText': 1}}], allowDiskUse=True)
    for doc in cursor:
        if doc.get('reviewText'):
            df.update(tokens(doc['reviewText']))
            documents += 1
    kept = {t: c for t, c in df.items() if c >= 3}
    db.meta.replace_one({'_id': 'keyword_idf'}, {'_id': 'keyword_idf', 'documents': documents, 'df': kept,
                                                'built_at': datetime.now(timezone.utc)}, upsert=True)
    return {'documents': documents, 'vocabulary': len(kept), 'seconds': round(time.time() - started, 2)}


class KeywordIndex:
    def __init__(self, db):
        doc = db.meta.find_one({'_id': 'keyword_idf'}) or {}
        self.documents = doc.get('documents', 0)
        self.df = doc.get('df', {})

    @property
    def ready(self):
        return bool(self.documents)

    def idf(self, token):
        return math.log((self.documents + 1) / (self.df.get(token, 0) + 1)) + 1

    def for_product(self, db, asin, limit=12, sample=500):
        groups = {'all': [], 'positive': [], 'negative': []}
        cursor = db.reviews.find({'asin': asin}, {'reviewText': 1, 'sentiment.label': 1}).sort('vote', -1).limit(sample)
        for doc in cursor:
            if not doc.get('reviewText'):
                continue
            found = tokens(doc['reviewText'])
            groups['all'].append(found)
            label = doc.get('sentiment', {}).get('label')
            if label in groups:
                groups[label].append(found)
        result = {}
        for name, docs in groups.items():
            n = len(docs)
            counts = Counter()
            for found in docs:
                counts.update(found)
            minimum = max(2, math.ceil(.03 * n))
            scored = sorted(((c / n) * self.idf(t), t, c) for t, c in counts.items() if c >= minimum)
            result[name] = {'reviews': n, 'items': [{'keyword': t, 'review_count': c, 'score': round(s, 4)} for s, t, c in reversed(scored[-limit:])]}
        return {'method': 'tf-idf' if self.ready else 'document-frequency (chưa dựng bảng IDF)', 'idf_documents': self.documents, **result}
