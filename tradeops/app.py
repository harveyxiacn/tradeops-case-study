"""Loopback-only synthetic quotation portfolio. No production authentication."""
import csv
import io
import os
import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

USERS = {'sales': ('demo', 'Sales'), 'manager': ('demo', 'Manager'), 'manager2': ('demo', 'Manager'), 'operations': ('demo','Operations'), 'reviewer': ('demo','Reviewer'), 'admin': ('demo','Admin'), 'other': ('other','Manager')}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS inquiry(id uuid PRIMARY KEY, org text NOT NULL, owner text NOT NULL, customer text NOT NULL, raw_text text NOT NULL, destination text NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS quote(id uuid PRIMARY KEY, inquiry_id uuid NOT NULL REFERENCES inquiry, org text NOT NULL, owner text NOT NULL, current_version int NOT NULL);
CREATE TABLE IF NOT EXISTS quote_version(quote_id uuid NOT NULL REFERENCES quote, version int NOT NULL, status text NOT NULL CHECK(status IN ('Draft','Pending','Approved','Rejected','Withdrawn','Superseded')), lock_version int NOT NULL DEFAULT 0, body jsonb NOT NULL, net numeric(18,2), net_hkd numeric(18,2), submitted_at timestamptz, PRIMARY KEY(quote_id,version));
CREATE TABLE IF NOT EXISTS approval_decision(quote_id uuid, version int, actor text NOT NULL, decision text NOT NULL, reason text NOT NULL, PRIMARY KEY(quote_id,version), FOREIGN KEY(quote_id,version) REFERENCES quote_version);
CREATE TABLE IF NOT EXISTS audit_event(id bigserial PRIMARY KEY, org text NOT NULL, actor text NOT NULL, quote_id uuid NOT NULL, version int NOT NULL, action text NOT NULL, reason text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(), correlation_id uuid NOT NULL);
CREATE TABLE IF NOT EXISTS followup(id bigserial PRIMARY KEY, quote_id uuid REFERENCES quote, actor text NOT NULL, note text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS quote_org ON quote(org);
CREATE INDEX IF NOT EXISTS pending_time ON quote_version(submitted_at) WHERE status='Pending';
'''

def fail(code, message, fields=None):
    raise HTTPException(code, {'message':message, 'field_errors':fields or {}})

def money(value, field):
    try:
        if isinstance(value, (float,bool)):
            raise ValueError()
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result > 100000000 or result.as_tuple().exponent < -2:
            raise ValueError()
        return result
    except (InvalidOperation, TypeError, ValueError):
        fail(422, 'Invalid decimal amount', {field:'Use a non-negative decimal string, maximum two decimal places'})

def calculate(body, complete=True):
    if not isinstance(body,dict): fail(422,'Quotation body must be an object')
    currency = body.get('currency')
    if currency not in ('HKD','USD'): fail(422,'Invalid currency',{'currency':'HKD or USD'})
    discount = money(body.get('discount_pct','0'), 'discount_pct')
    if discount > 50: fail(422,'Discount outside 0–50',{'discount_pct':'0–50'})
    days = body.get('payment_days',0)
    if type(days) is not int or not 0 <= days <= 365: fail(422,'Invalid payment days')
    lines = body.get('lines',[])
    if not isinstance(lines,list) or not 1 <= len(lines) <= 50: fail(422,'Supply 1–50 lines')
    gross = cost = Decimal('0')
    for line in lines:
        if not isinstance(line,dict) or line.get('sku') not in ('DEMO-A','DEMO-B','SKU-DEMO-A','SKU-DEMO-B'): fail(422,'Unknown demo SKU')
        qty = line.get('qty')
        if type(qty) is not int or not 1 <= qty <= 1000000: fail(422,'Quantity must be a positive integer',{'qty':'1–1000000'})
        gross += (qty*money(line.get('unit_price'),'unit_price')).quantize(Decimal('.01'), ROUND_HALF_UP)
        cost += (qty*money(line.get('unit_cost'),'unit_cost')).quantize(Decimal('.01'), ROUND_HALF_UP)
    net = gross - (gross*discount/100).quantize(Decimal('.01'), ROUND_HALF_UP)
    if net <= 0: fail(422,'Net amount must exceed zero')
    if complete:
        if not isinstance(body.get('destination'),str) or not body['destination'].strip(): fail(422,'Destination required',{'destination':'Required'})
        try:
            if date.fromisoformat(body.get('valid_until','')) < date.today(): raise ValueError()
        except (TypeError, ValueError): fail(422,'Valid future date required',{'valid_until':'YYYY-MM-DD'})
    fx = Decimal('1') if currency == 'HKD' else Decimal('7.80')
    hkd = (net*fx).quantize(Decimal('.01'), ROUND_HALF_UP)
    if hkd > Decimal('9999999999999999.99') or net > Decimal('9999999999999999.99'): fail(422,'Quotation amount exceeds storage limit')
    margin = (net-cost)/net
    return {'gross':str(gross),'net':str(net),'cost':str(cost),'margin_pct':str((margin*100).quantize(Decimal('.01'))),'fx_to_hkd':str(fx),'net_hkd':str(hkd),'review_flags': [name for name,yes in [('amount',hkd>10000),('margin',margin<Decimal('.2')),('payment',days>30)] if yes]}

class Store:
    def __init__(self, dsn):
        self.dsn=dsn
        with self.connect() as c: c.execute(SCHEMA)
    def connect(self): return psycopg.connect(self.dsn,row_factory=dict_row)
    def audit(self,c,user,q,version,action,reason):
        c.execute('INSERT INTO audit_event(org,actor,quote_id,version,action,reason,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s)',(USERS[user][0],user,q,version,action,reason,str(uuid.uuid4())))
    def get(self,c,q,user,lock=False):
        r=c.execute('SELECT q.*,v.version,v.status,v.lock_version,v.body,v.submitted_at FROM quote q JOIN quote_version v ON v.quote_id=q.id AND v.version=q.current_version WHERE q.id=%s AND q.org=%s'+(' FOR UPDATE OF q,v' if lock else ''),(q,USERS[user][0])).fetchone()
        if not r or (USERS[user][1]=='Sales' and r['owner']!=user) or (USERS[user][1]=='Operations' and r['status']!='Approved'): fail(404,'Quote not found')
        return r
    def change(self,q,user,action,data):
        with self.connect() as c:
            r=self.get(c,q,user,True)
            if data.get('expected_lock_version') != r['lock_version'] or data.get('version') != r['version']: fail(409,'Version changed; refresh before retrying')
            version=r['version']; status=r['status']; body=r['body']; role=USERS[user][1]
            if action in ('edit','submit','revise') and (r['owner']!=user or role not in ('Sales','Manager')): fail(403,'Only the owner may change this quote')
            reason=str(data.get('reason','')).strip()[:500]
            if action=='edit':
                if status!='Draft': fail(409,'Only drafts may be edited')
                body=data.get('body',{}); calculate(body,False)
            elif action=='submit':
                if status!='Draft': fail(409,'Only drafts may be submitted')
                body={**body,'totals':calculate(body)}; status='Pending'
            elif action in ('approve','reject'):
                if role!='Manager' or user==r['owner']: fail(403,'An independent manager must decide')
                if status!='Pending': fail(409,'Quote is no longer pending')
                if not reason: fail(422,'Decision reason required')
                c.execute('INSERT INTO approval_decision VALUES(%s,%s,%s,%s,%s)',(q,version,user,action,reason))
                status='Approved' if action=='approve' else 'Rejected'
            elif action=='revise':
                if status not in ('Pending','Approved','Rejected') or not reason: fail(409,'Revision requires a submitted version and reason')
                oldstatus='Superseded' if status=='Approved' else 'Withdrawn' if status=='Pending' else 'Rejected'
                c.execute('UPDATE quote_version SET status=%s,lock_version=lock_version+1 WHERE quote_id=%s AND version=%s',(oldstatus,q,version))
                self.audit(c,user,q,version,'revise',reason)
                version+=1; body={k:v for k,v in body.items() if k!='totals'}
                c.execute("INSERT INTO quote_version(quote_id,version,status,body) VALUES(%s,%s,'Draft',%s)",(q,version,Jsonb(body)))
                c.execute('UPDATE quote SET current_version=%s WHERE id=%s',(version,q))
                return {'id':q,'version':version,'status':'Draft','lock_version':0}
            else: fail(404,'Unknown action')
            totals=body.get('totals',{})
            c.execute('UPDATE quote_version SET status=%s,body=%s,lock_version=lock_version+1,net=%s,net_hkd=%s,submitted_at=CASE WHEN %s THEN now() ELSE submitted_at END WHERE quote_id=%s AND version=%s',(status,Jsonb(body),totals.get('net'),totals.get('net_hkd'),action=='submit',q,version))
            self.audit(c,user,q,version,action,reason)
            return {'id':q,'version':version,'status':status,'lock_version':r['lock_version']+1}

def create_app(dsn=None):
    db=Store(dsn or os.environ['TRADEOPS_DSN'])
    app=FastAPI(title='TradeOps — synthetic local demo')
    app.state.db=db
    tokens={secrets.token_urlsafe(32):u for u in USERS}
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
    @app.middleware('http')
    async def guard(request,call_next):
        if request.headers.get('sec-fetch-site')=='cross-site': return JSONResponse({'detail':'Cross-site access denied'},403)
        if request.headers.get('origin') and request.headers['origin']!=str(request.base_url).rstrip('/'): return JSONResponse({'detail':'Origin mismatch'},403)
        if len(await request.body())>65536: return JSONResponse({'detail':'Body too large'},413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    def actor(request):
        user=tokens.get(request.headers.get('authorization','').removeprefix('Bearer '))
        if not user: fail(401,'Choose a local DEMO session')
        return user
    @app.get('/api/demo-session')
    def session(): return {'warning':'LOCAL DEMO: simulated roles, not production login','tokens':{u:t for t,u in tokens.items() if u!='other'}}
    app.state.tokens={u:t for t,u in tokens.items()}
    @app.post('/api/inquiries',status_code=201)
    def inquiry(body:dict,request:Request):
        user=actor(request)
        if USERS[user][1] not in ('Sales','Manager'): fail(403,'Sales or Manager required')
        if not body.get('customer') or not body.get('raw_text'): fail(422,'Customer code and enquiry text required')
        key=str(uuid.uuid4())
        with db.connect() as c: c.execute('INSERT INTO inquiry VALUES(%s,%s,%s,%s,%s,%s)',(key,USERS[user][0],user,str(body['customer'])[:120],str(body['raw_text'])[:6000],str(body.get('destination',''))[:120]))
        return {'id':key}
    @app.post('/api/inquiries/{key}/quotes',status_code=201)
    def quote(key:uuid.UUID,body:dict,request:Request):
        user=actor(request); calculate(body,False); q=str(uuid.uuid4())
        with db.connect() as c:
            inquiry=c.execute('SELECT * FROM inquiry WHERE id=%s AND org=%s AND owner=%s',(key,USERS[user][0],user)).fetchone()
            if not inquiry or USERS[user][1] not in ('Sales','Manager'): fail(404,'Inquiry not found')
            c.execute('INSERT INTO quote VALUES(%s,%s,%s,%s,1)',(q,key,USERS[user][0],user))
            c.execute("INSERT INTO quote_version(quote_id,version,status,body) VALUES(%s,1,'Draft',%s)",(q,Jsonb(body)))
            db.audit(c,user,q,1,'create','Synthetic draft')
        return {'id':q,'version':1,'lock_version':0,'status':'Draft'}
    @app.get('/api/quotes')
    def listing(request:Request,status:str|None=None,page:int=1):
        user=actor(request)
        if not 1<=page<=10000: fail(422,'Invalid page')
        query='SELECT q.id,q.owner,v.version,v.status,v.lock_version,v.body FROM quote q JOIN quote_version v ON v.quote_id=q.id AND v.version=q.current_version WHERE q.org=%s'
        args=[USERS[user][0]]
        if USERS[user][1]=='Sales': query+=' AND q.owner=%s'; args.append(user)
        if USERS[user][1]=='Operations': query+=" AND v.status='Approved'"
        if status: query+=' AND v.status=%s'; args.append(status)
        query+=' ORDER BY q.id LIMIT 50 OFFSET %s'; args.append((page-1)*50)
        with db.connect() as c: return c.execute(query,args).fetchall()
    @app.get('/api/quotes/{q}')
    def detail(q:uuid.UUID,request:Request):
        user=actor(request)
        with db.connect() as c:
            result=db.get(c,q,user)
            result['history']=c.execute('SELECT version,status,lock_version,body FROM quote_version WHERE quote_id=%s ORDER BY version',(q,)).fetchall()
            result['audit']=c.execute('SELECT actor,version,action,reason,occurred_at,correlation_id FROM audit_event WHERE quote_id=%s ORDER BY id',(q,)).fetchall()
            result['followup']=c.execute('SELECT actor,note,occurred_at FROM followup WHERE quote_id=%s ORDER BY id',(q,)).fetchall()
            return result
    @app.post('/api/quotes/{q}/actions/{action}')
    def change(q:uuid.UUID,action:str,body:dict,request:Request): return db.change(q,actor(request),action,body)
    @app.post('/api/quotes/{q}/followup')
    def followup(q:uuid.UUID,body:dict,request:Request):
        user=actor(request)
        if USERS[user][1]!='Operations': fail(403,'Operations role required')
        note=str(body.get('note','')).strip()
        if not note or len(note)>1000: fail(422,'Supply a note of 1–1000 characters')
        with db.connect() as c:
            r=db.get(c,q,user,True)
            c.execute('INSERT INTO followup(quote_id,actor,note) VALUES(%s,%s,%s)',(q,user,note)); db.audit(c,user,q,r['version'],'followup','Synthetic operations follow-up')
        return {'saved':True}
    @app.get('/api/reports')
    def report(request:Request):
        user=actor(request)
        if USERS[user][1] not in ('Manager','Reviewer','Admin','Operations'): fail(403,'Report permission required')
        with db.connect() as c:
            rows=c.execute("SELECT v.status,count(*) AS count FROM quote q JOIN quote_version v ON v.quote_id=q.id AND v.version=q.current_version WHERE q.org=%s GROUP BY v.status",(USERS[user][0],)).fetchall()
            totals=c.execute("SELECT v.body->>'currency' currency,sum(v.net) net,sum(v.net_hkd) net_hkd FROM quote q JOIN quote_version v ON v.quote_id=q.id AND v.version=q.current_version WHERE q.org=%s AND v.status='Approved' GROUP BY v.body->>'currency'",(USERS[user][0],)).fetchall()
            overdue=c.execute("SELECT count(*) AS count FROM quote q JOIN quote_version v ON v.quote_id=q.id AND v.version=q.current_version WHERE q.org=%s AND v.status='Pending' AND v.submitted_at<now()-interval '48 hours'",(USERS[user][0],)).fetchone()
            for item in totals:
                item['net']=str(item['net']); item['net_hkd']=str(item['net_hkd'])
            return {'counts':rows,'approved_by_currency':totals,'pending_over_48_hours':overdue['count'],'clock':'UTC; strictly more than 48 hours'}
    @app.get('/api/quotes/{q}/export')
    def export(q:uuid.UUID,request:Request):
        user=actor(request)
        with db.connect() as c:
            r=db.get(c,q,user)
            if r['status']!='Approved': fail(409,'Only current approved versions may be exported')
            customer=c.execute('SELECT customer FROM inquiry WHERE id=%s',(r['inquiry_id'],)).fetchone()['customer']
        if customer.lstrip().startswith(('=','+','-','@','\t','\r','\n')): customer="'"+customer
        output=io.StringIO(); writer=csv.writer(output)
        writer.writerow(['Demo—not a commercial offer','quote_id','version','customer','currency','net_amount','fx_to_hkd','net_hkd','status'])
        t=r['body']['totals']; writer.writerow(['SYNTHETIC',q,r['version'],customer,r['body']['currency'],t['net'],t['fx_to_hkd'],t['net_hkd'],r['status']])
        return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="demo-quote.csv"'})
    static=Path(__file__).parent/'static'
    if static.exists(): app.mount('/',StaticFiles(directory=static,html=True),name='demo')
    return app
