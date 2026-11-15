import pytest
from amazon_movies.data import price, integer, product, review, sentiment, formats
from amazon_movies.recommend import rank_hybrid
from amazon_movies.session4 import compute_ranking_metrics

@pytest.mark.parametrize('value,expected',[('$1,234.50',1234.5),('',None),('$12 - $24',None),('unknown',None),(0,0.),(-1,None)])
def test_price_handles_missing_and_ranges(value,expected):
    assert price(value)==expected

def test_stable_review_key_preserves_distinct_events_for_same_pair():
    source={'reviewerID':'u','asin':'a','overall':5,'unixReviewTime':1500000000,'reviewText':'Good.'}
    reordered=dict(reversed(list(source.items())))
    assert review(source,False)['_id']==review(reordered,False)['_id']
    assert review(source,False)['_id']!=review({**source,'unixReviewTime':1500000001},False)['_id']

def test_missing_text_keeps_rating_without_inventing_sentiment():
    doc=review({'reviewerID':'u','asin':'a','overall':4,'unixReviewTime':1500000000})
    assert doc['overall']==4 and doc['sentiment']['label']=='unavailable'

def test_missing_identifiers_and_invalid_rating_are_rejected():
    assert review({'reviewerID':'','asin':'a','overall':5,'unixReviewTime':1}) is None
    assert review({'reviewerID':'u','asin':'a','overall':6,'unixReviewTime':1}) is None

def test_metadata_html_and_category_paths():
    doc=product({'asin':'a','title':'Film &amp; TV','brand':' by  Warner   Home Video - ','category':['Movies & TV','Movies'],'description':['A &amp; B'],'price':''})
    assert doc['title']=='Film & TV' and doc['description']=='A & B' and doc['brand']=='Warner Home Video'
    assert doc['category_paths']==[['Movies & TV','Movies']] and doc['price'] is None
    assert formats({' Format: ':' Blu-ray '})==['Blu-ray']
    assert integer('1,234')==1234

def test_vader_handles_negation_and_empty_text():
    assert sentiment('I love this wonderful film.')['label']=='positive'
    assert sentiment('This is awful and terrible.')['label']=='negative'
    assert sentiment('')['compound'] is None

def test_hybrid_does_not_let_large_raw_related_scores_dominate():
    ranked=rank_hybrid({'collaborative':[{'asin':'a','score':5}], 'related':[{'asin':'b','score':100000}]})
    assert ranked[0]['asin']=='a'
    assert ranked[0]['score']==pytest.approx(.45)

def test_junk_brand_and_html_in_title_are_cleaned():
    from amazon_movies.data import brand_name, strip_html
    assert brand_name('Various') == '' and brand_name(' . ') == '' and brand_name('n/a') == ''
    assert brand_name('by  Tom Hanks') == 'Tom Hanks'
    assert strip_html('<span class="a">Alien</span> <1979>') == 'Alien <1979>'


def test_vietnamese_review_is_not_labelled_by_english_vader():
    result = sentiment('Phim rất hay, diễn viên đóng tốt.')
    assert result['label'] == 'unsupported_language' and result['compound'] is None


def test_generic_amazon_names_get_a_distinguishing_suffix():
    from amazon_movies.graph import user_label
    assert user_label('Amazon Customer', 'A1B2C3D4E5F6') == 'Amazon Customer ·D4E5F6'
    assert user_label('', 'A1B2C3D4E5F6') == 'Người dùng ·D4E5F6'
    assert user_label('Grady Harp', 'AXYZ') == 'Grady Harp'


def test_split_keeps_identical_reviews_on_the_same_side():
    from amazon_movies.session4 import _split
    # (timestamp, _id, asin, rating, label, work, dup_group): r7 và r8 là cùng một review dán vào hai tác phẩm.
    events = [(t, f'r{t}', f'a{t}', 5., 'positive', f'w{t}', None) for t in range(1, 7)]
    events += [(7, 'r7', 'a7', 5., 'positive', 'w7', 'g'), (7, 'r8', 'a8', 5., 'positive', 'w8', 'g'), (9, 'r9', 'a9', 4., 'positive', 'w9', None)]
    # 9 review → 80% = 7 review đầu vào Train; r8 cùng nhóm với r7 nên cũng phải vào Train.
    train, test = _split(events)
    assert [e[1] for e in test] == ['r9']
    assert {'r7', 'r8'} <= {e[1] for e in train} and len(train) == 8


def test_ranking_metrics_precision_recall_ndcg():
    recs=['a','b','c','d','e','f','g','h','i','j']
    rel={'a','c','z'}
    m=compute_ranking_metrics(recs,rel,k=10)
    assert m['precision']==pytest.approx(0.2)
    assert m['recall']==pytest.approx(2/3)
    assert m['hit']==1.0
    assert 0.5 < m['ndcg'] < 1.0
