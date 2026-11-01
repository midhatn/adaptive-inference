# SPDX-License-Identifier: Apache-2.0
"""Prospective deadline regressions using the full existing synthetic fixture."""
from copy import deepcopy
import math
import unittest

from checks import check_continuation, digest
from test_checks import fixture


def evidence_at(authorized_at):
    """Rebase the existing fixture coherently; the producer adds exactly 900."""
    e=fixture();g=e['grant'];deadline=authorized_at+900
    g.update(authorized_at=authorized_at,deadline_monotonic=deadline)
    for name in ('selected_initial','selected'):
        e[name]['state']['deadline_monotonic']=deadline
    g['successor_initial_state_sha256']=digest(e['selected_initial']['state'])
    e['authority_history'][-1]['payload']['event_data']['result']['cleanup']['state_sha256']=digest(e['selected']['state'])
    ready=e['readiness']
    ready.update(started_qpc=authorized_at+1,finished_qpc=authorized_at+2,
                 readiness_deadline_monotonic=authorized_at+240)
    ready['boot']['deadline_monotonic']=deadline
    e['wire_after'][-1].update(started_at=authorized_at+3,finished_at=authorized_at+4)
    return e


class DeadlineArithmeticTests(unittest.TestCase):
    error='one_exact_grant'

    def test_observed_exponent_boundary_passes_the_complete_predicate(self):
        e=evidence_at(16108.3548623);before=deepcopy(e)
        self.assertEqual(e['grant']['deadline_monotonic'],17008.354862300002)
        self.assertNotEqual(e['grant']['deadline_monotonic']-e['grant']['authorized_at'],900)
        self.assertGreaterEqual(len(check_continuation(e)),16)
        self.assertEqual(e,before)

    def test_altered_deadline_is_refused_without_tolerance(self):
        e=evidence_at(16108.3548623)
        e['grant']['deadline_monotonic']=math.nextafter(e['grant']['deadline_monotonic'],math.inf)
        with self.assertRaisesRegex(AssertionError,self.error):check_continuation(e)

    def test_changed_budget_is_refused_even_with_matching_payload_digest(self):
        e=evidence_at(16108.3548623);g=e['grant'];g['payload']['budget_s']=901
        g['payload_sha256']=digest(g['payload'])
        with self.assertRaisesRegex(AssertionError,self.error):check_continuation(e)

    def test_invalid_values_are_refused_before_identity_arithmetic(self):
        for key in ('authorized_at','deadline_monotonic'):
            for value in (math.nan,math.inf,True,'16108.3548623'):
                with self.subTest(key=key,value=value):
                    e=evidence_at(16108.3548623);e['grant'][key]=value
                    with self.assertRaisesRegex(AssertionError,self.error):check_continuation(e)
        e=evidence_at(16108.3548623)
        e['grant'].update(authorized_at=math.inf,deadline_monotonic=math.inf)
        with self.assertRaisesRegex(AssertionError,self.error):check_continuation(e)

    def test_nonincreasing_deadline_is_refused_even_when_addition_rounds_away(self):
        e=evidence_at(16108.3548623)
        e['grant'].update(authorized_at=1e308,deadline_monotonic=1e308)
        self.assertEqual(1e308+900,1e308)
        with self.assertRaisesRegex(AssertionError,self.error):check_continuation(e)


if __name__=='__main__':unittest.main()
