import copy
import concurrent.futures
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
from tradeops.app import create_app, calculate

BODY={'currency':'USD','discount_pct':'5','payment_days':30,'valid_until':'2099-11-20','destination':'Hong Kong','lines':[{'sku':'DEMO-A','qty':100,'unit_price':'20.00','unit_cost':'14.00'}]}

class PostgreSQLAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app(Path('.env.local').read_text().strip());cls.client=TestClient(cls.app); cls.db=cls.app.state.db
    def headers(self,user='sales'): return {'Authorization':'Bearer '+self.app.state.tokens[user]}
    def create(self,user='sales',body=None,customer='DEMO-TEST'):
        r=self.client.post('/api/inquiries',json={'customer':customer,'raw_text':'Synthetic test'},headers=self.headers(user));self.assertEqual(r.status_code,201,r.text)
        r=self.client.post('/api/inquiries/'+r.json()['id']+'/quotes',json=body or BODY,headers=self.headers(user));self.assertEqual(r.status_code,201,r.text);return r.json()
    def act(self,q,name,user='sales',**extra):
        return self.client.post('/api/quotes/'+str(q['id'])+'/actions/'+name,json={'version':q['version'],'expected_lock_version':q['lock_version'],'reason':'Synthetic acceptance',**extra},headers=self.headers(user))
    def submit(self,q):
        r=self.act(q,'submit');self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_01_02_incomplete_draft(self):
        b=copy.deepcopy(BODY);b['destination']='';q=self.create(body=b)
        self.assertEqual(q['status'],'Draft');self.assertEqual(self.act(q,'submit').status_code,422)
    def test_03_decimal_example(self):
        r=calculate(BODY);self.assertEqual(r['net'],'1900.00');self.assertEqual(r['net_hkd'],'14820.00');self.assertEqual(r['review_flags'],['amount'])
    def test_04_05_boundaries(self):
        b=copy.deepcopy(BODY);b.update(currency='HKD',discount_pct='0');b['lines'][0].update(unit_price='100.00',unit_cost='80.00')
        self.assertEqual(calculate(b)['review_flags'],[]);b['lines'][0]['unit_cost']='85.00';self.assertEqual(calculate(b)['review_flags'],['margin'])
    def test_06_invalid_quantity(self):
        for qty in [0,-1,1.5,True]:
            b=copy.deepcopy(BODY);b['lines'][0]['qty']=qty
            with self.assertRaises(HTTPException):calculate(b)
    def test_07_bad_discount_currency(self):
        for value in ['-1','51','NaN']:
            with self.assertRaises(HTTPException):calculate({**BODY,'discount_pct':value})
        with self.assertRaises(HTTPException):calculate({**BODY,'currency':'EUR'})
    def test_08_self_approval(self):
        q=self.create(user='manager');r=self.act(q,'submit','manager').json();self.assertEqual(self.act(r,'approve','manager').status_code,403)
    def test_09_concurrent_decisions(self):
        q=self.submit(self.create())
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda u:self.act(q,'approve',u).status_code,['manager','manager2']))
        self.assertEqual(sorted(results),[200,409])
        with self.db.connect() as c:self.assertEqual(c.execute('SELECT count(*) n FROM approval_decision WHERE quote_id=%s',(q['id'],)).fetchone()['n'],1)
    def test_10_stale_version(self):
        old=self.submit(self.create());new=self.act(old,'revise').json();self.assertEqual(new['version'],2);self.assertEqual(self.act(old,'approve','manager').status_code,409)
    def test_11_optimistic_edit(self):
        q=self.create();self.assertEqual(self.act(q,'edit',body=BODY).status_code,200);self.assertEqual(self.act(q,'edit',body=BODY).status_code,409)
    def test_12_org_boundary(self):
        q=self.create();self.assertEqual(self.client.get('/api/quotes/'+q['id'],headers=self.headers('other')).status_code,404)
        self.assertEqual(self.client.get('/api/reports',headers=self.headers('other')).json()['counts'],[])
    def test_13_audit_failure_rolls_back(self):
        q=self.submit(self.create())
        with patch.object(self.db,'audit',side_effect=RuntimeError('controlled audit failure')):
            with self.assertRaises(RuntimeError):self.act(q,'approve','manager')
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM quote_version WHERE quote_id=%s',(q['id'],)).fetchone()['status'],'Pending')
            self.assertEqual(c.execute('SELECT count(*) n FROM approval_decision WHERE quote_id=%s',(q['id'],)).fetchone()['n'],0)
    def test_14_strict_48h_sql(self):
        a=self.submit(self.create());b=self.submit(self.create())
        with self.db.connect() as c:
            c.execute("UPDATE quote_version SET submitted_at=now()-interval '48 hours' WHERE quote_id=%s",(a['id'],))
            c.execute("UPDATE quote_version SET submitted_at=now()-interval '48 hours 1 second' WHERE quote_id=%s",(b['id'],))
            count=c.execute("SELECT count(*) n FROM quote_version WHERE quote_id IN (%s,%s) AND submitted_at<now()-interval '48 hours'",(a['id'],b['id'])).fetchone()['n'];self.assertEqual(count,1)
    def test_15_currency_groups(self):
        for currency in ['USD','HKD']:
            q=self.submit(self.create(body={**BODY,'currency':currency}));self.assertEqual(self.act(q,'approve','manager').status_code,200)
        r=self.client.get('/api/reports',headers=self.headers('manager')).json()
        self.assertEqual({x['currency'] for x in r['approved_by_currency']},{'USD','HKD'})
    def test_16_17_export_guard_formula(self):
        q=self.create(customer='=HYPERLINK("example")');url='/api/quotes/'+q['id']+'/export'
        self.assertEqual(self.client.get(url,headers=self.headers()).status_code,409)
        q=self.submit(q);self.act(q,'approve','manager');r=self.client.get(url,headers=self.headers())
        self.assertEqual(r.status_code,200);self.assertIn('Demo—not a commercial offer',r.text);self.assertIn("'=HYPERLINK",r.text)
    def test_18_readonly_and_origin(self):
        q=self.create();self.assertEqual(self.act(q,'submit','reviewer').status_code,403)
        self.assertEqual(self.client.post('/api/inquiries',json={},headers={'Origin':'https://untrusted.example'}).status_code,403)
    def test_operations_cannot_read_draft(self):
        q=self.create();self.assertEqual(self.client.get('/api/quotes/'+q['id'],headers=self.headers('operations')).status_code,404)
    def test_unknown_identity(self):
        self.assertEqual(self.client.get('/api/quotes',headers={'Authorization':'Bearer manager'}).status_code,401)

if __name__=='__main__':unittest.main(verbosity=2)
