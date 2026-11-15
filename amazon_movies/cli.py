import argparse, hashlib, json, re, sys, time
from pathlib import Path
from .config import settings
from .data import SOURCES, eda, write_json

def download(config):
    import requests
    config.raw('x').parent.mkdir(parents=True,exist_ok=True)
    results={}
    for name, source in SOURCES.items():
        target=config.raw(name)
        if not target.exists():
            partial=target.with_suffix(target.suffix+'.part'); offset=partial.stat().st_size if partial.exists() else 0
            with requests.get(source['url'],headers={'Range':f'bytes={offset}-'} if offset else {},stream=True,timeout=(15,90)) as response:
                response.raise_for_status(); append=offset>0 and response.status_code==206
                with partial.open('ab' if append else 'wb') as output:
                    for chunk in response.iter_content(1024*1024): output.write(chunk)
            partial.replace(target)
        with target.open('rb') as handle: sha=hashlib.file_digest(handle,'sha256').hexdigest()
        results[name]={'url':source['url'],'bytes':target.stat().st_size,'sha256':sha}
    write_json(config.report_dir/'sources_downloaded.json',results)
    return results

def create_admin(username='admin'):
    """Tạo (hoặc đổi) mật khẩu quản trị ngẫu nhiên và ghi vào .env. Không in mật khẩu ra màn hình."""
    import secrets
    from .config import PROJECT
    path=PROJECT/'.env'
    lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    values={'ADMIN_USERNAME':username,'ADMIN_PASSWORD':secrets.token_urlsafe(15)}
    kept=[line for line in lines if line.split('=',1)[0].strip() not in values]
    path.write_text('\n'.join(kept+[f'{k}={v}' for k,v in values.items()])+'\n',encoding='utf-8')
    return {'admin_username':username,'password':'đã ghi vào .env (ADMIN_PASSWORD), không in ra màn hình','restart_api':True}

def main(argv=None):
    parser=argparse.ArgumentParser(description='Đồ án Amazon Movies & TV — buổi 1–6')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor'); sub.add_parser('download'); p=sub.add_parser('create-admin'); p.add_argument('--username',default='admin'); sub.add_parser('mongo-init'); sub.add_parser('graph-init')
    p=sub.add_parser('eda'); p.add_argument('--limit',type=int,default=0)
    p=sub.add_parser('import-mongo'); p.add_argument('--limit',type=int,default=0); p.add_argument('--batch-size',type=int,default=2000); p.add_argument('--workers',type=int,default=4); p.add_argument('--defer-sentiment',action='store_true')
    p=sub.add_parser('import-graph'); p.add_argument('--batch-size',type=int,default=2000)
    p=sub.add_parser('sentiment'); p.add_argument('--limit',type=int,default=0)
    p=sub.add_parser('sync'); p.add_argument('--limit',type=int,default=0); p.add_argument('--watch',action='store_true'); p.add_argument('--interval',type=float,default=10.)
    p=sub.add_parser('verify'); p.add_argument('--exhaustive',action='store_true')
    p=sub.add_parser('gds-similarity'); p.add_argument('--top-k',type=int,default=20); p.add_argument('--min-reviews',type=int,default=5); p.add_argument('--degree-cutoff',type=int,default=3); p.add_argument('--memory-limit-gib',type=float,default=4.)
    p=sub.add_parser('graph-analytics'); p.add_argument('--top-n',type=int,default=20)
    p=sub.add_parser('evaluate'); p.add_argument('--sample-users',type=int,default=1200); p.add_argument('--k',type=int,default=10); p.add_argument('--parity-users',type=int,default=20)
    sub.add_parser('benchmark')
    p=sub.add_parser('session4'); p.add_argument('--sample-users',type=int,default=1200)
    p=sub.add_parser('recommend'); p.add_argument('user'); p.add_argument('--method',choices=['collaborative','related','content','hybrid','popular'],default='hybrid'); p.add_argument('--limit',type=int,default=10)
    p=sub.add_parser('serve'); p.add_argument('--port',type=int,default=settings.api_port)
    sub.add_parser('stats'); sub.add_parser('rebuild-stats'); sub.add_parser('editions'); sub.add_parser('clean-data'); sub.add_parser('work-sync'); sub.add_parser('dup-groups'); p=sub.add_parser('keyword-idf'); p.add_argument('--sample',type=int,default=300000)
    args=parser.parse_args(argv)
    for name in ['limit','batch_size','top_k','workers','top_n','sample_users','k','sample']:
        if hasattr(args,name) and (getattr(args,name)<0 or (name!='limit' and getattr(args,name)==0)): parser.error(name+' không hợp lệ')
    if hasattr(args,'interval') and args.interval<1: parser.error('interval tối thiểu 1 giây')
    if args.command=='download': result=download(settings)
    elif args.command=='create-admin':
        if not re.fullmatch(r'[a-z0-9_]{3,32}',args.username): parser.error('username gồm 3–32 ký tự a–z, 0–9, _')
        result=create_admin(args.username)
    elif args.command=='eda': result=eda(settings,args.limit)
    else:
        from . import mongo,graph
        if args.command=='doctor':
            result={'data_dir':str(settings.data_dir),'raw_files':{name:settings.raw(name).exists() for name in SOURCES}}
            try:
                client,db=mongo.connect(); result['mongodb']={'ok':True,'version':client.server_info()['version']}; client.close()
            except Exception as exc: result['mongodb']={'ok':False,'error':type(exc).__name__}
            try:
                with graph.connect() as driver:
                    result['neo4j']={'ok':True,**graph.run(driver,'CALL dbms.components() YIELD versions RETURN versions[0] AS version')[0],**graph.run(driver,'RETURN gds.version() AS gds')[0]}
            except Exception as exc: result['neo4j']={'ok':False,'error':type(exc).__name__}
            write_json(settings.report_dir/'buoi1_environment.json',result)
        elif args.command=='serve':
            from .api import create_app
            create_app(warmup=True).run(host=settings.api_host,port=args.port,debug=False,use_reloader=False,threaded=True)
            return
        else:
            client,db=mongo.connect()
            try:
                if args.command=='mongo-init': result=mongo.initialize(db)
                elif args.command=='import-mongo': result=mongo.import_data(db,limit=args.limit,batch_size=args.batch_size,with_sentiment=not args.defer_sentiment,workers=args.workers)
                elif args.command=='sentiment': result=mongo.sentiment_backfill(db,args.limit)
                elif args.command=='rebuild-stats': mongo.rebuild_stats(db); result={'ok':True}
                elif args.command=='stats': result=mongo.dashboard(db)
                elif args.command=='dup-groups':
                    from . import editions
                    result=editions.mark_duplicate_groups(db)
                elif args.command=='keyword-idf':
                    from . import keywords
                    result=keywords.build_idf(db,args.sample)
                else:
                    with graph.connect() as driver:
                        if args.command=='graph-init': result=graph.initialize(driver)
                        elif args.command=='import-graph': result=graph.import_graph(db,driver,batch_size=args.batch_size)
                        elif args.command=='verify':
                            result=graph.verify(db,driver,exhaustive=args.exhaustive)
                            if not result['ok']: print(json.dumps(result,ensure_ascii=False,indent=2)); sys.exit(1)
                        elif args.command=='sync':
                            while True:
                                try: result=graph.sync_pending(db,driver,limit=args.limit)
                                except Exception as exc:
                                    if not args.watch: raise
                                    result={'retry_error':type(exc).__name__}
                                if not args.watch: break
                                print(json.dumps(result),flush=True); time.sleep(args.interval)
                        elif args.command=='clean-data':
                            from . import editions
                            result=editions.clean_existing(db,driver)
                        elif args.command=='editions':
                            from . import editions
                            result=editions.build_works(db,driver)
                        elif args.command=='work-sync':
                            from . import editions
                            result=editions.sync_work_fields(db,driver)
                        elif args.command=='gds-similarity': result=graph.gds_similarity(driver,top_k=args.top_k,min_reviews=args.min_reviews,degree_cutoff=args.degree_cutoff,memory_limit_gib=args.memory_limit_gib)
                        elif args.command=='evaluate':
                            from . import session4
                            result=session4.evaluate_recommendations(db,sample_users=args.sample_users,k=args.k,driver=driver,parity_users=args.parity_users)
                        elif args.command=='graph-analytics':
                            from . import session4
                            result=session4.run_graph_analytics(db,driver,top_n=args.top_n)
                        elif args.command=='benchmark':
                            from . import session4
                            result={'index_benchmark':session4.benchmark_indexes(db,driver),'db_comparison':session4.compare_databases(db,driver)}
                        elif args.command=='session4':
                            from . import session4
                            result={
                                'graph_analytics':session4.run_graph_analytics(db,driver),
                                'evaluation':session4.evaluate_recommendations(db,sample_users=args.sample_users,driver=driver,parity_users=20),
                                'index_benchmark':session4.benchmark_indexes(db,driver),
                                'db_comparison':session4.compare_databases(db,driver),
                            }
                        elif args.command=='recommend':
                            from .recommend import recommend
                            result=recommend(db,driver,args.user,args.method,args.limit)
            finally: client.close()
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__': main()
