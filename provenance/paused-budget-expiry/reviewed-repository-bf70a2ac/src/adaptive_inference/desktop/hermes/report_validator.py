# SPDX-License-Identifier: Apache-2.0
"""Qualification oracle adapter; no expected answers are returned as feedback."""
import hashlib
import json
from pathlib import Path
from adaptive_inference.feedback import Verdict

VERSION='orders-report-before-effect.v1'

def identity(expected):
    return {'version':VERSION,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'oracle_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()}

def distinct_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result

def validator(expected):
    # Freeze the caller's existing oracle without placing arithmetic in Recovery.
    expected=json.loads(json.dumps(expected))
    def validate(name,args):
        if name!='write_file':raise ValueError('Unexpected validation capability')
        try:
            answer=json.loads(args['content'],object_pairs_hook=distinct_object)
            if (type(answer) is not dict or set(answer)!=set(expected)
                    or any(type(answer[key]) is not int for key in ('rows','units','total_cents'))
                    or type(answer['by_item']) is not dict
                    or set(answer['by_item'])!=set(expected['by_item'])
                    or any(type(value) is not int for value in answer['by_item'].values())):
                raise ValueError('Report schema differs')
        except (ValueError,TypeError,KeyError):
            return Verdict(False,'Report schema rejected. Use exactly rows, units, total_cents and by_item, '
                'JSON integers, one entry per original CSV item, no duplicate keys or extra text. '
                'Recompute from orders.csv and submit corrected write_file arguments. No file was written.')
        failed=[key for key in ('rows','units','total_cents','by_item') if answer[key]!=expected[key]]
        if failed:
            return Verdict(False,'Report arithmetic rejected in fields: '+', '.join(failed)+'. '
                'Recount rows, sum quantities, multiply quantity by unit_cents for each row, '
                'group repeated items and sum item totals. Recompute from orders.csv and submit '
                'corrected write_file arguments. No file was written.')
        return Verdict(True)
    return validate
