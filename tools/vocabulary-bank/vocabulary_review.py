"""Private live vocabulary review. Stdlib only, no lexicon/model changes."""
import argparse
import contextlib
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import tarfile
import time
import threading
from urllib.parse import parse_qs, urlparse

import vocabulary_bank as bank
import technical_terms
import review_groups
from stt_dictionary import apply_dictionary,normalize_plugin
from voice_corpus import MAX_BYTES, MIN_FREE_BYTES

SAMPLE_ID = re.compile(r"[0-9]{20}-[a-f0-9]{32}\Z")


class ReviewError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,client_address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


def connect(root, write=False):
    path = Path(root) / bank.DB_NAME
    journal=Path(root)/(bank.DB_NAME+"-journal")
    if journal.exists() or journal.is_symlink():
        info=journal.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid():
            raise ReviewError(503,"Небезопасный журнал базы")
    if path.is_symlink() or not path.is_file():
        raise ReviewError(503, "Словарь ещё не готов")
    info=path.lstat()
    if info.st_nlink!=1 or info.st_uid!=os.getuid():raise ReviewError(503,"Небезопасная база")
    connection=sqlite3.connect(f"file:{path}?mode={'rw' if write else 'ro'}", uri=True, timeout=0.2)
    connection.create_function("fold",1,lambda value: value.casefold() if isinstance(value,str) else "")
    return connection


def fingerprint(kind, row):
    return hashlib.sha256(json.dumps([kind, row], ensure_ascii=False).encode()).hexdigest()


def has_feedback(connection):
    return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone())


def rule_preview(root,text):
    config=Path(root).parent/'config/stt-dictionary.json'
    preview,metadata=apply_dictionary(text,config)
    return {'text':preview,'status':metadata['status'],'active_rules':metadata.get('active_rules',[]),
            'changes':len(metadata['changes']),'basis':'current_rule_preview_not_historical_output'}


def summary(root):
    with contextlib.closing(connect(root)) as connection:
        result = bank.status(connection)
        result["feedback_count"] = connection.execute("SELECT count(*) FROM feedback").fetchone()[0] if has_feedback(connection) else 0
        result["latest_import_ns"] = connection.execute("SELECT max(imported_at) FROM sources").fetchone()[0]
        result["source_kinds"] = dict(connection.execute("SELECT kind,count(*) FROM sources GROUP BY kind"))
    result['dictionary']=rule_preview(root,'')
    return result


def term_list(root, query="", page=0, only="all"):
    if not isinstance(page, int) or not 0 <= page <= 1_000_000 or len(query) > 100:
        raise ReviewError(400, "Неверный поиск")
    with contextlib.closing(connect(root)) as connection:
        where = "WHERE instr(t.normalized,?)>0"
        if only == "confirmed": where += " AND t.confirmed=1"
        elif only == "candidates": where += " AND t.confirmed=0"
        elif only != "all": raise ReviewError(400, "Неверный фильтр")
        total = connection.execute(f"SELECT count(*) FROM terms t {where}", (bank.normalize(query),)).fetchone()[0]
        rows = connection.execute(f"SELECT t.normalized,t.display,t.confirmed FROM terms t {where} "
                                  "ORDER BY t.confirmed DESC,t.normalized LIMIT 40 OFFSET ?",
                                  (bank.normalize(query),page*40)).fetchall()
        items=[]
        for row in rows:
            normalized, display, confirmed = row
            count, sources = connection.execute("SELECT coalesce(sum(count),0),count(distinct source) FROM observations WHERE term=?",(normalized,)).fetchone()
            categories = [r[0] for r in connection.execute("SELECT distinct category FROM observations WHERE term=? LIMIT 8",(normalized,))]
            decision = None
            if has_feedback(connection):
                last=connection.execute("SELECT decision,value FROM feedback WHERE target_kind='term' AND target_key=? ORDER BY created_ns DESC LIMIT 1",(normalized,)).fetchone()
                if last:decision={"decision":last[0],"value":last[1]}
            items.append({"key":normalized,"text":display,"confirmed":bool(confirmed),"occurrences":count,
                          "sources":sources,"categories":categories,"decision":decision,"revision":fingerprint("term",row)})
    return {"items":items,"total":total,"page":page,"page_size":40}


def has_mentions(connection):
    return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='name_mentions'").fetchone())


def mention_row(connection,key):
    if not has_mentions(connection):raise ReviewError(404,"Очередь ещё собирается")
    row=connection.execute("SELECT m.id,m.source,m.stage,m.canonical,m.start,m.end,m.surface,m.reason,m.label,d.text,d.sample_ref,d.text_hash FROM name_mentions m JOIN name_documents d ON d.source=m.source AND d.stage=m.stage WHERE m.id=?",(key,)).fetchone()
    if not row:raise ReviewError(404,"Упоминание не найдено")
    return row


def name_list(root,query="",page=0,pending=True,canonical="GitHub"):
    if canonical not in {"GitHub","Omarchy","плагины","Смотри","Разработка","Linux"}:raise ReviewError(400,"Неизвестная очередь")
    if len(query)>100 or not 0<=page<=1_000_000:raise ReviewError(400,"Неверный поиск")
    with contextlib.closing(connect(root)) as connection:
        if not has_mentions(connection):return {"items":[],"total":0,"page":page,"page_size":20,"variants":[],"scanned_sources":0}
        groups,grouping=review_groups.group_rows(connection,canonical)
        all_groups=groups
        groups=[g for g in groups if query.casefold() in g['row'][6].casefold() or query.casefold() in g['row'][9].casefold()]
        if pending:groups=[g for g in groups if g['decision'] is None]
        total=len(groups);items=[]
        for group in groups[page*20:(page+1)*20]:
            row=group['row']
            identity,source,stage,row_canonical,start,end,surface,reason,label,text,sample,digest=row
            decision=group['decision']
            preview=rule_preview(root,text)
            recorded_final=None
            if isinstance(sample,str) and SAMPLE_ID.fullmatch(sample):
                try:recorded_final=bank.read_metadata(Path(root)/(sample+'.tar')).get('final_text')
                except (OSError,ValueError,tarfile.TarError,KeyError):pass
            normalized,plugin_changes=normalize_plugin(surface)
            items.append({"rule_preview":preview,"recorded_final_text":recorded_final,
                "member_keys":[str(r[0]) for r in group["members"]],"evidence_count":len(group["members"]),"evidence_stages":sorted(set(r[2] for r in group["members"])),"feedback_conflict":group["conflict"],
                "known_plugin_rule":bool(plugin_changes or surface=='plugin') and 'plugin' in preview['active_rules'],
                "normalized_surface":normalized,"key":str(identity),"canonical":row_canonical,"surface":surface,"reason":reason,"label":label,
                "stage":stage,"text":text,"range":[start,end],"sample_id":sample,
                "suggestions":technical_terms.suggestions(surface,canonical) if canonical in technical_terms.TOPICS else [],
                "topic_queue":canonical in technical_terms.TOPICS,
                "audio_available":bool(isinstance(sample,str) and SAMPLE_ID.fullmatch(sample) and (Path(root)/(sample+'.tar')).is_file()),
                "decision":decision,"revision":group["revision"]})
        variant_counts={}
        for group in all_groups:
            surface=group['row'][6];variant_counts[surface]=variant_counts.get(surface,0)+1
        variants=[{'surface':surface,'count':count} for surface,count in sorted(variant_counts.items(),key=lambda pair:(-pair[1],pair[0]))[:50]]
        scanned=connection.execute("SELECT count(*) FROM name_scans").fetchone()[0]
        scanned_stt=connection.execute("SELECT count(*) FROM sources s JOIN name_scans n ON s.source=n.source WHERE s.kind='stt'").fetchone()[0]
        speech_documents=connection.execute("SELECT count(*) FROM name_documents d WHERE stage='stt_raw' AND EXISTS(SELECT 1 FROM name_mentions m WHERE m.source=d.source AND m.stage=d.stage AND m.canonical=?)",(canonical,)).fetchone()[0]
    return {"items":items,"total":total,"page":page,"page_size":20,"variants":variants,"scanned_sources":scanned,"scanned_stt":scanned_stt,"matched_stt_records":speech_documents,"grouping":grouping}


def dispute_alignment(primary, teacher, left, right):
    """Conservative textual correspondence, never acoustic word alignment."""
    fallback={"reliable":False,"mode":"sentence","reason":"Нельзя надёжно сопоставить отдельные слова. Сравни целые фразы.",
              "primary_range":None,"teacher_range":None,"audio_timestamps":False}
    if not all(isinstance(x,str) for x in [primary,teacher,left,right]) or not primary or not teacher:
        return {**fallback,"reason":"Не сохранился полный контекст; отдельные слова не сопоставлены."}
    a=list(bank.TOKEN.finditer(primary[:bank.MAX_TEXT]));b=list(bank.TOKEN.finditer(teacher[:bank.MAX_TEXT]))
    if max(len(a),len(b))>1000:return fallback
    av=[bank.normalize(x.group()) for x in a];bv=[bank.normalize(x.group()) for x in b]
    lv=[bank.normalize(x) for x in bank.TOKEN.findall(left)];rv=[bank.normalize(x) for x in bank.TOKEN.findall(right)]
    matcher=bank.SequenceMatcher(None,av,bv,autojunk=False)
    if matcher.ratio()<0.55:return fallback
    operations=matcher.get_opcodes()
    found=[]
    for index,(operation,i,j,x,y) in enumerate(operations):
        if operation=='equal' or av[i:j]!=lv or bv[x:y]!=rv:continue
        # Only unique stored spans; repeated words can match a different occurrence.
        if lv and sum(av[k:k+len(lv)]==lv for k in range(len(av)-len(lv)+1))!=1:continue
        if rv and sum(bv[k:k+len(rv)]==rv for k in range(len(bv)-len(rv)+1))!=1:continue
        prefix=index>0 and operations[index-1][0]=='equal'
        suffix=index+1<len(operations) and operations[index+1][0]=='equal'
        if not (prefix or suffix) or max(j-i,y-x)>6:continue
        # Text moved elsewhere is not a replacement at this position.
        if set(lv)&set(bv[:x]+bv[y:]) or set(rv)&set(av[:i]+av[j:]):continue
        def char_range(matches,start,end,text):
            if start==end:
                point=matches[start].start() if start<len(matches) else len(text)
                return [point,point]
            return [matches[start].start(),matches[end-1].end()]
        found.append({"reliable":True,"mode":"fragment","reason":"Сопоставлено по соседним словам; это не временная разметка аудио.",
                      "operation":operation,"primary_range":char_range(a,i,j,primary),
                      "teacher_range":char_range(b,x,y,teacher),"audio_timestamps":False})
    return found[0] if len(found)==1 else fallback


def dispute_context(root,row):
    metadata={}
    try:metadata=bank.read_metadata(Path(root)/row[1])
    except (OSError,ValueError,tarfile.TarError,KeyError):pass
    primary=metadata.get("primary_text","");teacher=metadata.get("teacher_text","")
    return primary,teacher,dispute_alignment(primary,teacher,row[2],row[3])


def dispute_revision(row,primary,teacher,alignment):
    return fingerprint("dispute-v2",[row,primary,teacher,alignment])


def get_dispute(connection, key):
    row=connection.execute("SELECT rowid,source,primary_span,teacher_span,hinted,sample_ref FROM disputes WHERE rowid=?",(key,)).fetchone()
    if not row:raise ReviewError(404,"Фрагмент не найден")
    return row


def dispute_list(root, query="", page=0, pending=True):
    if len(query)>100 or not 0<=page<=1_000_000:raise ReviewError(400,"Неверный поиск")
    with contextlib.closing(connect(root)) as connection:
        condition="WHERE (instr(fold(d.primary_span),?)>0 OR instr(fold(d.teacher_span),?)>0)"
        if pending and has_feedback(connection):
            condition+=" AND NOT EXISTS(SELECT 1 FROM feedback f WHERE f.target_kind='dispute' AND f.target_key=cast(d.rowid as text))"
        args=(query.lower(),query.lower())
        total=connection.execute(f"SELECT count(*) FROM disputes d {condition}",args).fetchone()[0]
        rows=connection.execute(f"SELECT d.rowid,d.source,d.primary_span,d.teacher_span,d.hinted,d.sample_ref FROM disputes d {condition} ORDER BY d.hinted DESC,d.rowid DESC LIMIT 20 OFFSET ?",(*args,page*20)).fetchall()
        items=[]
        for row in rows:
            identity,source,left,right,hinted,sample=row
            context_primary,context_teacher,alignment=dispute_context(root,row)
            audio=bool(isinstance(sample,str) and SAMPLE_ID.fullmatch(sample) and (Path(root)/(sample+".tar")).is_file())
            decision=None
            if has_feedback(connection):
                last=connection.execute("SELECT decision,value FROM feedback WHERE target_kind='dispute' AND target_key=? ORDER BY created_ns DESC LIMIT 1",(str(identity),)).fetchone()
                if last:decision={"decision":last[0],"value":last[1]}
            items.append({"key":str(identity),"primary":left,"teacher":right,"hinted":bool(hinted),
                          "context_primary":context_primary,"context_teacher":context_teacher,"alignment":alignment,
                          "sample_id":sample,"audio_available":audio,"decision":decision,"revision":dispute_revision(row,context_primary,context_teacher,alignment)})
    return {"items":items,"total":total,"page":page,"page_size":20}


def save_feedback(root, payload):
    if not isinstance(payload,dict):raise ReviewError(400,"Неверный формат")
    kind,key,decision=payload.get("kind"),payload.get("key"),payload.get("decision")
    rid,revision=payload.get("request_id"),payload.get("revision")
    if kind not in ["term","dispute","name_occurrence"] or not isinstance(key,str) or len(key)>200:
        raise ReviewError(400,"Неверная запись")
    if not isinstance(rid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}",rid):raise ReviewError(400,"Неверный ID")
    allowed={"name_occurrence":{"yes","no","unsure","custom","as_heard"},"term":{"confirm","reject","skip","custom"},"dispute":{"primary","teacher","skip","custom","sentence_primary","sentence_teacher","sentence_custom"}}
    if decision not in allowed[kind]:raise ReviewError(400,"Неверное решение")
    value=payload.get("value","")
    if not isinstance(value,str) or len(value)>(2048 if decision=="sentence_custom" else 160) or (decision in {"custom","sentence_custom"} and not value.strip()) or any(ord(c)<32 for c in value):
        raise ReviewError(400,"Неверное написание")
    root=Path(root);fd=os.open(root/".lock",os.O_RDWR|os.O_NOFOLLOW)
    connection=None;old=os.umask(0o077)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ReviewError(409,"Архив занят; попробуйте ещё раз")
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ReviewError(503,"Небезопасный lock")
        connection=connect(root,write=True)
        if has_feedback(connection):
            saved=connection.execute("SELECT target_kind,target_key,decision,value FROM feedback WHERE request_id=?",(rid,)).fetchone()
            if saved:
                if saved!=(kind,key,decision,value.strip()):raise ReviewError(409,"ID уже использован другим решением")
                return {"saved":True,"duplicate":True,"request_id":rid}
        if kind=="term":
            row=connection.execute("SELECT normalized,display,confirmed FROM terms WHERE normalized=?",(key,)).fetchone()
            if not row:raise ReviewError(404,"Слово не найдено")
        elif kind=="name_occurrence":
            if not key.isdigit():raise ReviewError(400,"Неверное упоминание")
            row=mention_row(connection,key)
            if row[3]=='Смотри' and decision=='yes':
                raise ReviewError(400,"Для начала фразы выбери явно Ну/Смотри, исходное слово или своё написание")
            if row[3] in technical_terms.TOPICS and decision=='yes':
                raise ReviewError(400,"Для тематической карточки выбери точное слово или своё написание")
        else:
            if not key.isdigit():raise ReviewError(400,"Неверный фрагмент")
            row=get_dispute(connection,key)
        expected=fingerprint(kind,row)
        members=[row]
        if kind=="name_occurrence":members,expected=review_groups.for_row(connection,row)
        if kind=="dispute":
            primary,teacher,alignment=dispute_context(root,row)
            expected=dispute_revision(row,primary,teacher,alignment)
            if not alignment["reliable"] and decision in {"primary","teacher","custom"}:
                raise ReviewError(409,"Слова не сопоставлены. Выбери целую фразу или пропусти.")
            if decision in {"sentence_primary","sentence_teacher","sentence_custom"} and not (primary and teacher):
                raise ReviewError(409,"Полного контекста нет; можно только пропустить")
        if revision!=expected:raise ReviewError(409,"Запись изменилась. Обновите список")
        total=0
        for entry in root.iterdir():
            info=entry.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ReviewError(503,"Небезопасный файл архива")
            total+=info.st_size
        db_size=(root/bank.DB_NAME).stat().st_size
        reserve=db_size+bank.RESERVE
        if total+reserve>MAX_BYTES or shutil.disk_usage(root).free-reserve<MIN_FREE_BYTES:
            raise ReviewError(507,"Нет места в общей квоте")
        page_size=connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={min(bank.DB_LIMIT,db_size+bank.RESERVE//4)//page_size}")
        connection.execute("PRAGMA synchronous=FULL")
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS feedback_context(request_id TEXT PRIMARY KEY,context_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS feedback(request_id TEXT PRIMARY KEY,target_kind TEXT NOT NULL,target_key TEXT NOT NULL,decision TEXT NOT NULL,value TEXT NOT NULL,created_ns INTEGER NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS feedback_target ON feedback(target_kind,target_key,created_ns)")
            connection.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?)",(rid,kind,key,decision,value.strip(),time.time_ns()))
            if kind=="dispute":
                connection.execute("INSERT INTO feedback_context VALUES(?,?)",(rid,json.dumps({"scope":"sentence" if decision.startswith("sentence_") else "fragment", "primary":primary,"teacher":teacher,"alignment":alignment},ensure_ascii=False)))
            if kind=="name_occurrence":
                shared_time=time.time_ns()
                for member in members:
                    if str(member[0])==key:continue
                    member_rid=rid+'_m'+str(member[0])
                    connection.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?)",(member_rid,kind,str(member[0]),decision,value.strip(),shared_time))
                connection.execute("INSERT INTO feedback_context VALUES(?,?)",(rid,json.dumps({"scope":"named_occurrence_group","member_keys":[str(m[0]) for m in members],"canonical":row[3],"surface":row[6],"range":[row[4],row[5]],"text":row[9],"stage":row[2],"source":row[1],"sample_id":row[10],"alias_approved":False},ensure_ascii=False)))
            # A term click approves vocabulary existence, not utterance correctness.
            if kind=="term" and decision=="confirm":connection.execute("UPDATE terms SET confirmed=1 WHERE normalized=?",(key,))
            if kind=="term" and decision=="reject":connection.execute("UPDATE terms SET confirmed=0 WHERE normalized=?",(key,))
        return {"saved":True,"duplicate":False,"request_id":rid,"training_approved":False,"autocorrection":False}
    finally:
        if connection:connection.close()
        os.close(fd);os.umask(old)


def audio_bytes(root,sample):
    if not SAMPLE_ID.fullmatch(sample):raise ReviewError(400,"Неверная запись")
    path=Path(root)/(sample+".tar")
    if path.is_symlink() or not path.is_file():raise ReviewError(404,"Запись уже удалена ротацией")
    info=path.lstat()
    if info.st_nlink!=1:raise ReviewError(400,"Небезопасное аудио")
    with tarfile.open(path) as archive:
        member=archive.getmember("original.wav")
        if not member.isfile() or member.size>10*1024*1024:raise ReviewError(400,"Неверное аудио")
        return archive.extractfile(member).read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def setup(self):super().setup();self.connection.settimeout(10)
    def send(self,status,body,mime="application/json"):
        if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type",mime);self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(body)
    def boundary(self,write=False):
        ip=self.client_address[0]
        if not (ip.startswith("100.") and 64<=int(ip.split('.')[1])<=127) and ip not in self.server.test_peers:
            raise ReviewError(403,"Доступ только из Tailscale")
        host=self.headers.get("Host","")
        if host not in self.server.hosts:raise ReviewError(403,"Неверный Host")
        if write:
            if self.headers.get("Origin")!="http://"+host:raise ReviewError(403,"Неверный Origin")
            if not secrets.compare_digest(self.headers.get("X-CSRF-Token",""),self.server.csrf):raise ReviewError(403,"Неверный CSRF")
    def do_GET(self):
        try:
            self.boundary();parsed=urlparse(self.path);query=parse_qs(parsed.query)
            if parsed.path in ["/","/index.html","/github","/omarchy","/plugins","/opening","/development","/linux","/app.js","/style.css"]:
                name={"/":"index.html","/github":"index.html","/omarchy":"index.html","/plugins":"index.html","/opening":"index.html","/development":"index.html","/linux":"index.html"}.get(parsed.path,parsed.path.lstrip('/'))
                body=(self.server.assets/name).read_bytes()
                mime={"index.html":"text/html; charset=utf-8","app.js":"text/javascript; charset=utf-8","style.css":"text/css; charset=utf-8"}[name]
                return self.send(200,body,mime)
            if parsed.path=="/api/status":return self.send(200,{**summary(self.server.root),"csrf":self.server.csrf})
            page=int(query.get("page",["0"])[0]);q=query.get("q",[""])[0]
            name_routes={"/api/github":"GitHub","/api/omarchy":"Omarchy","/api/plugins":"плагины","/api/opening":"Смотри","/api/development":"Разработка","/api/linux":"Linux"}
            if parsed.path in name_routes:return self.send(200,name_list(self.server.root,q,page,query.get("pending",["1"])[0]=="1",name_routes[parsed.path]))
            if parsed.path=="/api/terms":return self.send(200,term_list(self.server.root,q,page,query.get("filter",["all"])[0]))
            if parsed.path=="/api/disputes":return self.send(200,dispute_list(self.server.root,q,page,query.get("pending",["1"])[0]=="1"))
            if parsed.path.startswith("/audio/"):return self.send(200,audio_bytes(self.server.root,parsed.path.removeprefix("/audio/")),"audio/wav")
            raise ReviewError(404,"Не найдено")
        except ReviewError as e:self.send(e.status,{"error":e.message})
        except (ValueError,KeyError,tarfile.TarError):self.send(400,{"error":"Неверный запрос"})
        except (sqlite3.Error,OSError):self.send(503,{"error":"База временно занята"})
    def do_POST(self):
        try:
            self.boundary(write=True)
            if self.path!="/api/feedback":raise ReviewError(404,"Не найдено")
            if self.headers.get("Transfer-Encoding"):raise ReviewError(411,"Нужна длина запроса")
            size=int(self.headers.get("Content-Length","0"))
            if not 1<=size<=4096:raise ReviewError(413,"Слишком большой запрос")
            self.send(200,save_feedback(self.server.root,json.loads(self.rfile.read(size))))
        except ReviewError as e:self.send(e.status,{"error":e.message})
        except (ValueError,KeyError):self.send(400,{"error":"Неверный запрос"})
        except (sqlite3.Error,OSError):self.send(503,{"error":"Сохранение недоступно; решение не подтверждено"})


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True);parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--host",default="100.110.84.30");parser.add_argument("--port",type=int,default=3219)
    args=parser.parse_args()
    if not (args.host.startswith("100.") and 64<=int(args.host.split('.')[1])<=127):raise SystemExit("Tailnet bind required")
    server=Server((args.host,args.port),Handler)
    server.slots=threading.BoundedSemaphore(8)
    server.root=args.root;server.assets=args.assets;server.hosts={f"{args.host}:{args.port}"}
    server.csrf=secrets.token_urlsafe(32);server.test_peers=set();server.daemon_threads=True
    server.serve_forever()
