import gzip
import json
from types import SimpleNamespace
from amazon_movies.data import eda, SOURCES


def test_eda_preserves_time_bounds_including_unix_epoch(tmp_path):
    source = [
        {'reviewerID':'u1','asin':'p','overall':5,'unixReviewTime':10},
        {'reviewerID':'u2','asin':'p','overall':4,'unixReviewTime':0},
        {'reviewerID':'u3','asin':'p','overall':3,'unixReviewTime':7},
    ]
    for name in SOURCES:
        values=source if name.startswith('Movies') else [{'asin':'p','title':'Film'}]
        with gzip.open(tmp_path/name,'wt',encoding='utf-8') as handle:
            for value in values: handle.write(json.dumps(value)+'\n')
    config=SimpleNamespace(raw=lambda name:tmp_path/name,report_dir=tmp_path/'reports')
    report=eda(config)
    reviews=report['files']['Movies_and_TV_5.json.gz']
    assert reviews['raw_rows']==3 and reviews['distinct_users']==3
    assert reviews['min_timestamp']==0 and reviews['max_timestamp']==10
    assert reviews['stars']=={'5':1,'4':1,'3':1}
