"""Bằng: đọc gzip theo luồng, chuẩn hóa và EDA; không nạp cả tệp vào RAM."""
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import gzip, hashlib, html, json, re, time

SOURCES = {
    'Movies_and_TV_5.json.gz': {'url': 'https://mcauleylab.ucsd.edu/public_datasets/data/amazon_v2/categoryFilesSmall/Movies_and_TV_5.json.gz', 'expected_rows': 3410019},
    'meta_Movies_and_TV.json.gz': {'url': 'https://mcauleylab.ucsd.edu/public_datasets/data/amazon_v2/metaFiles2/meta_Movies_and_TV.json.gz', 'expected_rows': 203970},
}

def rows(path, limit=0):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if limit and number > limit:
                break
            try:
                yield number, json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f'{Path(path).name}, dòng {number}: JSON không hợp lệ') from exc

def batches(items, size=2000):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

def text(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return '\n'.join(text(v) for v in value if v)
    return html.unescape(str(value)).strip()

def integer(value, default=0):
    try:
        return max(0, int(str(value).replace(',', '').strip()))
    except (ValueError, TypeError):
        return default

def price(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value >= 0 else None
    value = text(value)
    if not re.fullmatch(r'\$?\s*\d[\d,]*(?:\.\d{1,2})?', value):
        return None
    return float(value.replace('$', '').replace(',', '').strip())

# Giá trị brand không mang thông tin (đo trên dữ liệu: "Various" 1.605 phim, "." 537, "n/a" 138, "-" 132, "*" 92, "None" 67).
JUNK_BRANDS = {'various', 'various artists', 'n/a', 'na', 'none', 'null', 'unknown', 'not applicable', 'not available', 'tbd', 'tba'}

def brand_name(value):
    cleaned = re.sub(r'\s+', ' ', text(value)).strip(' -|,;:')
    if cleaned.lower().startswith('by ') and len(cleaned) > 3:
        cleaned = cleaned[3:].strip()
    if cleaned.lower() in JUNK_BRANDS or not re.search(r'[0-9A-Za-zÀ-ỹ]', cleaned):
        return ''
    return cleaned

HTML_TAG = re.compile(r'<\s*/?\s*[A-Za-z][^>]*>?')

def strip_html(value):
    """Bỏ thẻ HTML lẫn trong dữ liệu Amazon (ví dụ tiêu đề '<span class=...'); giữ '<1953>'."""
    return re.sub(r'\s+', ' ', HTML_TAG.sub(' ', value)).strip()

def formats(style):
    if not isinstance(style, dict):
        return []
    return sorted({re.sub(r'\s+', ' ', text(v)) for k, v in style.items() if str(k).strip().rstrip(':').lower() == 'format' and text(v)})

def category_paths(category):
    if not isinstance(category, list) or not category:
        return []
    candidates = category if isinstance(category[0], list) else [category]
    return [[text(part) for part in path if text(part)] for path in candidates if isinstance(path, list)]

def product(raw):
    asin, title = text(raw.get('asin')), strip_html(text(raw.get('title')))
    if not asin or not title:
        return None
    paths = category_paths(raw.get('category', raw.get('categories', [])))
    return {'_id': asin, 'asin': asin, 'title': title, 'description': text(raw.get('description')),
            'feature': [text(v) for v in raw.get('feature', [])] if isinstance(raw.get('feature'), list) else [],
            'brand': brand_name(raw.get('brand')), 'category_paths': paths,
            'categories': sorted({part for path in paths for part in path}),
            'main_cat': strip_html(text(raw.get('main_cat'))), 'price': price(raw.get('price')), 'price_raw': text(raw.get('price')),
            'rank': text(raw.get('rank')), 'date_raw': text(raw.get('date')),
            'images': [text(v) for v in raw.get('imageURL', [])] if isinstance(raw.get('imageURL'), list) else ([text(raw['imageURL'])] if raw.get('imageURL') else []),
            'also_buy': list(dict.fromkeys(text(v) for v in raw.get('also_buy', []) if text(v))),
            'also_view': list(dict.fromkeys(text(v) for v in raw.get('also_view', raw.get('also_viewed', [])) if text(v))),
            'formats': [], 'source': 'amazon_2018', 'active': False}

@lru_cache(maxsize=1)
def analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    return SentimentIntensityAnalyzer()

VIETNAMESE = re.compile(r'[ăâđêôơưĂÂĐÊÔƠƯàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]')

@lru_cache(maxsize=10000)
def sentiment(value):
    if not value.strip():
        return {'label': 'unavailable', 'compound': None, 'model': 'vader-3.3.2', 'language': 'en'}
    if VIETNAMESE.search(value):
        # VADER chỉ có từ điển tiếng Anh: không gán nhãn sai cho review tiếng Việt.
        return {'label': 'unsupported_language', 'compound': None, 'model': 'vader-3.3.2', 'language': 'vi'}
    scores = analyzer().polarity_scores(value)
    compound = float(scores['compound'])
    return {**scores, 'label': 'positive' if compound >= .05 else 'negative' if compound <= -.05 else 'neutral', 'model': 'vader-3.3.2', 'language': 'en'}

def review(raw, with_sentiment=True):
    user, asin = text(raw.get('reviewerID')), text(raw.get('asin'))
    try:
        rating, timestamp = float(raw['overall']), int(raw['unixReviewTime'])
        if not user or not asin or not 1 <= rating <= 5 or timestamp < 0:
            return None
        date = datetime.fromtimestamp(timestamp, timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    # A source row is an event, not a unique user-product pair. Exact source duplicates share this key.
    rid = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    body = text(raw.get('reviewText'))
    return {'_id': rid, 'review_id': rid, 'reviewerID': user, 'asin': asin, 'reviewerName': text(raw.get('reviewerName')),
            'overall': rating, 'summary': text(raw.get('summary')), 'reviewText': body,
            'vote': integer(raw.get('vote')), 'source_vote':integer(raw.get('vote')), 'demo_vote_count':0, 'verified': raw.get('verified') is True,
            'style': raw.get('style') if isinstance(raw.get('style'), dict) else {}, 'formats': formats(raw.get('style')),
            'timestamp': timestamp, 'review_date': date,
            'sentiment': sentiment(body) if with_sentiment else {'label': 'pending', 'compound': None},
            'source': 'amazon_2018', 'is_demo': False, 'is_copy': False, 'version': 1, 'synced_version': 0, 'synced': False}

def normalize_review_batch(group, with_sentiment=True):
    docs=[]; invalid=0
    for number, raw in group:
        doc=review(raw,with_sentiment)
        if doc is None: invalid+=1
        else:
            doc['source_line']=number
            docs.append(doc)
    return docs,invalid

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temp.replace(path)

def eda(config, limit=0):
    started = time.time()
    result = {'sample_limit_per_file': limit or None, 'is_full_scan': not bool(limit), 'sources': SOURCES, 'files': {}}
    for filename in SOURCES:
        users, items, stars, present, nonempty, form = set(), set(), Counter(), Counter(), Counter(), Counter()
        count, invalid = 0, 0
        min_timestamp = max_timestamp = None
        lengths = []
        for number, raw in rows(config.raw(filename), limit):
            count += 1; present.update(raw.keys()); nonempty.update(k for k,v in raw.items() if v)
            items.add(str(raw.get('asin', '')))
            if 'overall' in raw:
                users.add(str(raw.get('reviewerID', ''))); stars[str(raw['overall'])] += 1
                form.update(formats(raw.get('style')))
                if len(lengths) < 100000: lengths.append(len(text(raw.get('reviewText'))))
                if raw.get('unixReviewTime') is not None:
                    timestamp = int(raw['unixReviewTime'])
                    min_timestamp = timestamp if min_timestamp is None else min(min_timestamp, timestamp)
                    max_timestamp = timestamp if max_timestamp is None else max(max_timestamp, timestamp)
            elif not product(raw): invalid += 1
            if count % 250000 == 0: print(f'EDA {filename}: {count:,}', flush=True)
        import pandas as pd
        result['files'][filename] = {'raw_rows':count, 'distinct_asin':len(items), 'distinct_users':len(users) if users else None,
             'field_presence':dict(present), 'nonempty':dict(nonempty), 'stars':dict(stars), 'formats':dict(form),
             'invalid_metadata':invalid, 'min_timestamp':min_timestamp, 'max_timestamp':max_timestamp,
             'text_length_first_100000':pd.Series(lengths,dtype='float64').describe().to_dict() if lengths else None,
             'matches_published_rows':count == SOURCES[filename]['expected_rows'] if not limit else None}
    result['seconds'] = round(time.time()-started, 2)
    write_json(config.report_dir/'buoi1_eda.json', result)
    return result
