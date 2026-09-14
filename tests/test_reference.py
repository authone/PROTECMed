"""Synthetic-only executable reference tests. No OpenFHE or web service is exercised."""
from __future__ import annotations
import base64
import copy
import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zipfile import ZipFile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/python"))
from cohort import *
from protocol import (canonical_bytes, parse_json, payload_hash, sha256, sign, verify,
                      gate_partials, Ed25519PrivateKey)
from iocn_audit import audit_rows, HEADERS
from jsonschema import Draft202012Validator

CAT = json.loads((ROOT / 'config/query-catalog.json').read_text())['queries']
EXAMPLES = json.loads((ROOT / 'fixtures/contract_examples.json').read_text())


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.rows = read_canonical_csv(ROOT / 'fixtures/synthetic_cohorts.csv')
    def test_fixture_totals(self):
        expected = json.loads((ROOT/'fixtures/synthetic_expected.json').read_text())['counts']
        self.assertEqual(summarize(self.rows, CAT), expected)
    def test_row_count_and_all_null_record(self):
        self.assertEqual(len(self.rows), 24)
        self.assertTrue(all(v is None for v in self.rows[-1].values()))
        self.assertEqual(count_query(self.rows, CAT[0], CAT)['count'],24)
    def test_splits_cover_indices(self):
        for n in (2,3):
            parts=split_rows(list(range(24)), n)
            self.assertEqual(sorted(sum(parts,[])),list(range(24)))
            self.assertEqual(len(set(sum(parts,[]))),24)
    def test_no_is_false(self):
        for value in ['No','false','NU','0',0,False]:
            self.assertIs(normalize('toxicity_wbc_ge2',value),False)
    def test_missing_is_not_false(self):
        for value in ['',None,'NA','n/a','NULL']:
            self.assertIsNone(normalize('toxicity_wbc_ge2',value))
    def test_yes_is_true(self):
        for value in [' Yes ','DA',True,1,1.0]:
            self.assertIs(normalize('toxicity_wbc_ge2',value),True)
    def test_invalid_bool(self):
        for value in [2,'maybe',-1,0.2]:
            with self.assertRaises(ValueError):normalize('toxicity_wbc_ge2',value)
    def test_integer_age(self):
        for value in [11,11.0,' 11 ']:self.assertEqual(normalize('age_at_rt',value),11)
    def test_invalid_age(self):
        for value in [11.5,True,'11.5',121,-1,float('nan')]:
            with self.assertRaises(ValueError):normalize('age_at_rt',value)
    def test_unknown_enum(self):
        with self.assertRaises(ValueError):normalize('diagnosis','UNREVIEWED')
    def test_blank_vs_na_admission(self):
        rows, skipped=project_raw_rows([{f:'' for f in FIELDS},{f:'NA' for f in FIELDS}])
        self.assertEqual((len(rows),skipped),(1,1))
    def test_missing_only_required(self):
        row={f:None for f in FIELDS};row['diagnosis']='MBL'
        self.assertEqual(count_query([row],CAT[1],CAT)['count'],1)
        self.assertEqual(count_query([row],CAT[3],CAT)['excluded_missing'],1)
    def test_local_limit(self):
        with self.assertRaises(ValueError):count_query([self.rows[0]]*10001,CAT[0],CAT)
    def test_query_boolean_as_age(self):
        q=copy.deepcopy(CAT[4]);q['filters'][0]['value']=True
        with self.assertRaises(ValueError):validate_query(q)
    def test_query_integer_as_bool(self):
        q=copy.deepcopy(CAT[3]);q['filters'][2]['value']=1
        with self.assertRaises(ValueError):validate_query(q)
    def test_unknown_extra_key(self):
        q=copy.deepcopy(CAT[1]);q['expression']='anything'
        with self.assertRaises(ValueError):validate_query(q)
    def test_modified_catalogue_query_denied(self):
        q=copy.deepcopy(CAT[1]);q['filters'][0]['value']='PNET'
        with self.assertRaises(ValueError):assert_catalogue_member(q,CAT)
    def test_canonical_row_type_not_coerced(self):
        row=copy.deepcopy(self.rows[0]);row['toxicity_wbc_ge2']='NO'
        with self.assertRaises(ValueError):count_query([row],CAT[0],CAT)
    def test_wrong_csv_header(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.csv';p.write_text('diagnosis,diagnosis\nMBL,MBL\n')
            with self.assertRaises(ValueError):read_canonical_csv(p)


class CanonicalTests(unittest.TestCase):
    def test_order_invariant_object(self):
        self.assertEqual(canonical_bytes({'b':2,'a':1}),b'{"a":1,"b":2}')
    def test_array_order_matters(self):
        self.assertNotEqual(payload_hash([1,2]),payload_hash([2,1]))
    def test_duplicate_key(self):
        with self.assertRaises(ValueError):parse_json(b'{"a":1,"a":2}')
    def test_float_forbidden(self):
        with self.assertRaises(ValueError):parse_json(b'{"a":1.0}')
    def test_unicode_forbidden(self):
        with self.assertRaises(ValueError):canonical_bytes({'label':'ț'})
    def test_integer_range(self):
        with self.assertRaises(ValueError):canonical_bytes(2**53)
    def test_nan_forbidden(self):
        with self.assertRaises(ValueError):parse_json(b'{"a":NaN}')
    def test_depth_limit(self):
        v=0
        for _ in range(20):v=[v]
        with self.assertRaises(ValueError):canonical_bytes(v)
    def test_signature_purpose_and_tamper(self):
        k=Ed25519PrivateKey.generate();keys={'party-a':k.public_key()}
        e=sign({'x':1},'party-a','partial',k)
        self.assertEqual(verify(e,'partial',keys),{'x':1})
        with self.assertRaises(ValueError):verify(e,'encrypted-count',keys)
        e['payload']['x']=2
        with self.assertRaises(Exception):verify(e,'partial',keys)
    def test_unknown_signer(self):
        k=Ed25519PrivateKey.generate();e=sign({'x':1},'unknown','partial',k)
        with self.assertRaises(ValueError):verify(e,'partial',{})


class PartialGateTests(unittest.TestCase):
    def setUp(self):
        self.request=copy.deepcopy(EXAMPLES['decryption-request'])
        self.now=datetime(2026,9,5,10,30,tzinfo=timezone.utc)
        self.private={p:Ed25519PrivateKey.generate() for p in self.request['required_parties']}
        self.public={p:k.public_key() for p,k in self.private.items()}
        self.artifacts={};self.envelopes=[]
        for i,p in enumerate(self.request['required_parties']):
            raw=('synthetic-not-an-fhe-partial-'+p).encode();h=sha256(raw);self.artifacts[h]=raw
            payload=dict(schema_version='2.0',party_id=p,request_sha256=payload_hash(self.request),
                aggregate_sha256=self.request['aggregate_sha256'],epoch_sha256=self.request['epoch_sha256'],
                role='lead' if i==0 else 'main',decision='APPROVE',approved_at='2026-09-05T10:10:00Z',
                partial_sha256=h,partial_size=len(raw))
            self.envelopes.append(sign(payload,p,'partial',self.private[p]))
    def gate(self):return gate_partials(self.request,self.envelopes,self.artifacts,self.public,self.now)
    def resign(self,i):
        p=self.envelopes[i]['signer_id'];self.envelopes[i]=sign(self.envelopes[i]['payload'],p,'partial',self.private[p])
    def test_complete_three(self):self.assertEqual(len(self.gate()),3)
    def test_complete_two(self):
        self.request['required_parties']=self.request['required_parties'][:2];self.request['threshold']=2
        self.envelopes=self.envelopes[:2]
        for i in range(2):self.envelopes[i]['payload']['request_sha256']=payload_hash(self.request);self.resign(i)
        self.assertEqual(len(self.gate()),2)
    def test_missing(self):
        self.envelopes.pop()
        with self.assertRaises(ValueError):self.gate()
    def test_duplicate(self):
        self.envelopes[2]=copy.deepcopy(self.envelopes[1])
        with self.assertRaises(ValueError):self.gate()
    def test_wrong_role(self):
        self.envelopes[1]['payload']['role']='lead';self.resign(1)
        with self.assertRaises(ValueError):self.gate()
    def test_wrong_aggregate(self):
        self.envelopes[1]['payload']['aggregate_sha256']='0'*64;self.resign(1)
        with self.assertRaises(ValueError):self.gate()
    def test_wrong_epoch(self):
        self.envelopes[1]['payload']['epoch_sha256']='0'*64;self.resign(1)
        with self.assertRaises(ValueError):self.gate()
    def test_expired(self):
        self.now+=timedelta(hours=1)
        with self.assertRaises(ValueError):self.gate()
    def test_future_approval(self):
        self.envelopes[1]['payload']['approved_at']='2026-09-05T10:45:00Z';self.resign(1)
        with self.assertRaises(ValueError):self.gate()
    def test_different_request_nonce(self):
        self.request['nonce']='1'*64
        with self.assertRaises(ValueError):self.gate()
    def test_corrupt_partial_bytes(self):
        h=self.envelopes[1]['payload']['partial_sha256'];self.artifacts[h]=b'corrupted'
        with self.assertRaises(ValueError):self.gate()
    def test_threshold_drop_denied(self):
        self.request['threshold']=2
        with self.assertRaises(ValueError):self.gate()
    def test_boolean_threshold_denied(self):
        self.request['threshold']=True
        with self.assertRaises(ValueError):self.gate()
    def test_wrong_signer_claim(self):
        self.envelopes[1]['payload']['party_id']='party-a';self.resign(1)
        with self.assertRaises(ValueError):self.gate()
    def test_future_request(self):
        self.now-=timedelta(hours=1)
        with self.assertRaises(ValueError):self.gate()
    def test_naive_clock(self):
        self.now=self.now.replace(tzinfo=None)
        with self.assertRaises(ValueError):self.gate()


def make_minimal_xlsx(path, formula=True, cache='1', error=False, duplicate=False, macro=False):
    # Independently invented OOXML fixture for the narrow audit utility only.
    cols={'diagnosis':'I','rt_technique':'Q','toxicity_wbc_ge2':'LY','age_at_rt':'H','surgery_type':'M'}
    head=''.join(f'<c r="{cols[f]}1" t="inlineStr"><is><t>{escape(HEADERS[f])}</t></is></c>' for f in FIELDS)
    if duplicate:head+='<c r="J1" t="inlineStr"><is><t>Diagnostic</t></is></c>'
    row='<c r="I2" t="inlineStr"><is><t>MBL</t></is></c><c r="Q2" t="inlineStr"><is><t>IMRT</t></is></c>'
    row+='<c r="H2"><v>9</v></c><c r="M2" t="inlineStr"><is><t>GTR</t></is></c>'
    typ='e' if error else 'b'
    row+=f'<c r="LY2" t="{typ}">'+('<f>1=1</f>' if formula else '')
    if cache is not None:row+=f'<v>{escape(cache)}</v>'
    row+='</c>'
    with ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        '<sheet name="Date - craniospinal irradiation" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{head}</row><row r="2">{row}</row></sheetData></worksheet>')
        if macro:z.writestr('xl/vbaProject.bin',b'not-a-real-macro')


class CacheTests(unittest.TestCase):
    def run_case(self,mode,**kwargs):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'synthetic.xlsx';make_minimal_xlsx(p,**kwargs)
            return audit_rows(p,mode)
    def test_formula_literal_mode_rejects(self):
        with self.assertRaisesRegex(ValueError,'FORMULA_NOT_ALLOWED'):self.run_case('literal-only')
    def test_valid_cache(self):
        rows,m=self.run_case('reviewed-cached-values')
        self.assertEqual(count_query(rows,CAT[3],CAT)['count'],1)
        self.assertEqual(m['selected_formula_cells']['toxicity_wbc_ge2'],1)
    def test_false_cache_not_missing(self):
        rows,m=self.run_case('reviewed-cached-values',cache='0')
        self.assertIs(rows[0]['toxicity_wbc_ge2'],False)
    def test_missing_cache_rejects(self):
        with self.assertRaisesRegex(ValueError,'FORMULA_CACHE_MISSING'):self.run_case('reviewed-cached-values',cache=None)
    def test_error_cache_rejects(self):
        with self.assertRaisesRegex(ValueError,'EXCEL_ERROR_CELL'):self.run_case('reviewed-cached-values',cache='#REF!',error=True)
    def test_literal_cells(self):
        rows,m=self.run_case('literal-only',formula=False)
        self.assertEqual(len(rows),1)
    def test_duplicate_header(self):
        with self.assertRaisesRegex(ValueError,'REQUIRED_HEADER'):self.run_case('reviewed-cached-values',duplicate=True)
    def test_macro_rejected(self):
        with self.assertRaisesRegex(ValueError,'MACRO_WORKBOOK'):self.run_case('reviewed-cached-values',macro=True)


class SchemaTests(unittest.TestCase):
    def test_schemas_self_validate(self):
        for f in (ROOT/'contracts').glob('*.schema.json'):
            Draft202012Validator.check_schema(json.loads(f.read_text()))
    def test_synthetic_examples_validate(self):
        for name,instance in EXAMPLES.items():
            s=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text())
            Draft202012Validator(s).validate(instance)
    def test_query_catalogue(self):
        s=json.loads((ROOT/'contracts/query.schema.json').read_text())
        for q in CAT:Draft202012Validator(s).validate(q);validate_query(q)
    def test_real_signature_envelope_schema(self):
        k=Ed25519PrivateKey.generate();e=sign(EXAMPLES['partial'],'party-a','partial',k)
        s=json.loads((ROOT/'contracts/envelope.schema.json').read_text())
        Draft202012Validator(s).validate(e)


if __name__=='__main__':unittest.main()
