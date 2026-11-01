# SPDX-License-Identifier: Apache-2.0
# Exact function ASTs retained from baseline/audit_expiry.py; no clock conversion.
import math
CLOCK_ID='windows-qpc-seconds-v1'

def finite_time(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0

def qpc_bracket(row,before,after):
    return (row.get('deadline_clock')==CLOCK_ID and finite_time(row.get(before))
            and finite_time(row.get(after)) and row[before]<=row[after])