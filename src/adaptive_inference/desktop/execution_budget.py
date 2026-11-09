# SPDX-License-Identifier: Apache-2.0
"""Pure budget arithmetic for ordinary clean-Stop reopening across boots.

Reuse Temporal's fixed expiration across execution episodes, without its service:
https://github.com/temporalio/temporal/blob/e0233ff6658fcab7b4e7ecc1c16af40baf629b78/common/util.go#L588
https://github.com/temporalio/temporal/blob/e0233ff6658fcab7b4e7ecc1c16af40baf629b78/service/history/workflow/retry.go#L306
Temporal is MIT licensed; this adapts the policy, not copied implementation.

QPC is per boot, while UTC is adjustable. Callers supply observed clock brackets,
validate raw boot/profile/package identity, and persist under the existing owned
TaskStore transaction. This module neither observes clocks nor grants ownership.
It supports a normally maintained system clock, not arbitrary offline clock edits.
"""
from copy import deepcopy
from fractions import Fraction
import math
import re

BUDGET = 'adaptive_inference.execution_budget.v1'
MAX_SECONDS = 900
_NS = 1_000_000_000


class BudgetError(ValueError):
    """A new versioned budget cannot authorize the requested execution."""


def _require(value, message):
    if not value:
        raise BudgetError(message)


def _fields(value, names, label):
    _require(type(value) is dict and set(value) == set(names), label + ' fields differ')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _boot(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value),
             'Validated boot-observation digest required')


def _observation(value):
    _fields(value, ('utc_ns', 'qpc_before', 'qpc_after'), 'Clock observation')
    _require(type(value['utc_ns']) is int and value['utc_ns'] > 0
             and _number(value['qpc_before']) and _number(value['qpc_after'])
             and value['qpc_after'] >= value['qpc_before'], 'Invalid UTC/QPC bracket')
    return deepcopy(value)


def _remaining_ns(deadline, observation):
    # Fraction preserves the supplied float values without rounding time upward.
    interval = Fraction(deadline) - Fraction(observation['qpc_after'])
    return math.floor(interval * _NS)


def validate_budget(value):
    """Validate a persisted record without taking time or changing any state.

    Absence is not a request to manufacture a policy for legacy tasks. The caller
    must leave those records on their existing same-boot deadline rule.
    """
    _fields(value, ('schema', 'max_seconds', 'origin', 'expires_utc_ns',
                   'remaining_cap_ns', 'episode', 'last_observation', 'clean_stop'), 'Budget')
    _require(value['schema'] == BUDGET and type(value['max_seconds']) is int
             and value['max_seconds'] == MAX_SECONDS, 'Unknown execution-budget policy')
    origin, episode = value['origin'], value['episode']
    _fields(origin, ('boot_id', 'deadline', 'observation'), 'Budget origin')
    _fields(episode, ('index', 'boot_id', 'deadline', 'observation', 'granted_ns'), 'Budget episode')
    _boot(origin['boot_id']); _boot(episode['boot_id'])
    initial = _observation(origin['observation'])
    current = _observation(episode['observation'])
    latest = _observation(value['last_observation'])
    _require(_number(origin['deadline']) and _number(episode['deadline']), 'Invalid QPC deadline')
    original_ns = _remaining_ns(origin['deadline'], initial)
    _require(0 < original_ns <= MAX_SECONDS * _NS, 'Original grant exceeds task budget')
    _require(type(value['expires_utc_ns']) is int
             and value['expires_utc_ns'] == initial['utc_ns'] + original_ns,
             'Original UTC expiration changed')
    _require(type(episode['index']) is int and episode['index'] >= 0
             and type(episode['granted_ns']) is int and 0 < episode['granted_ns'] <= original_ns
             and type(value['remaining_cap_ns']) is int
             and 0 <= value['remaining_cap_ns'] <= episode['granted_ns']
             and type(value['clean_stop']) is bool, 'Invalid or refunded remaining budget')
    _require(current['utc_ns'] >= initial['utc_ns']
             and latest['utc_ns'] >= current['utc_ns']
             and latest['qpc_after'] >= current['qpc_after'], 'Budget observations went backwards')
    if episode['index'] == 0:
        _require(episode['boot_id'] == origin['boot_id']
                 and episode['deadline'] == origin['deadline']
                 and current == initial and episode['granted_ns'] == original_ns,
                 'Original boot episode changed')
    else:
        _require(episode['granted_ns'] <= value['expires_utc_ns'] - current['utc_ns']
                 and Fraction(episode['deadline']) <= Fraction(current['qpc_before'])
                    + Fraction(episode['granted_ns'], _NS), 'Rebased episode refunded time')
    _require(value['remaining_cap_ns'] <= max(0, _remaining_ns(episode['deadline'], latest))
             and value['remaining_cap_ns'] <= max(0, value['expires_utc_ns'] - latest['utc_ns']),
             'Remaining cap exceeds its recorded clocks')
    return deepcopy(value)


def create_budget(*, boot_id, deadline, observation, max_seconds=MAX_SECONDS):
    """Bind a new policy to time already granted by the ordinary task launcher."""
    _boot(boot_id); observed = _observation(observation)
    _require(type(max_seconds) is int and max_seconds == MAX_SECONDS
             and _number(deadline), 'Original 900-second policy and finite deadline required')
    remaining = _remaining_ns(deadline, observed)
    _require(0 < remaining <= MAX_SECONDS * _NS, 'Initial grant is expired or exceeds 900 seconds')
    return validate_budget({
        'schema': BUDGET, 'max_seconds': max_seconds,
        'origin': {'boot_id': boot_id, 'deadline': deadline, 'observation': observed},
        'expires_utc_ns': observed['utc_ns'] + remaining,
        'remaining_cap_ns': remaining,
        'episode': {'index': 0, 'boot_id': boot_id, 'deadline': deadline,
                    'observation': observed, 'granted_ns': remaining},
        'last_observation': observed, 'clean_stop': False})


def _next_observation(budget, observation, *, same_boot):
    observed = _observation(observation)
    previous = budget['last_observation']
    _require(observed['utc_ns'] >= previous['utc_ns'], 'System UTC moved backwards')
    if same_boot:
        _require(observed['qpc_before'] >= previous['qpc_after'], 'Current-boot QPC moved backwards')
    return observed


def _cap(budget, observed):
    return max(0, min(budget['remaining_cap_ns'],
                      _remaining_ns(budget['episode']['deadline'], observed),
                      budget['expires_utc_ns'] - observed['utc_ns']))


def tighten_budget(budget, *, boot_id, observation):
    """Record clean Stop after the caller verifies the existing safe boundary."""
    value = validate_budget(budget); _boot(boot_id)
    _require(boot_id == value['episode']['boot_id'], 'Clean Stop belongs to the current boot')
    observed = _next_observation(value, observation, same_boot=True)
    value.update(remaining_cap_ns=_cap(value, observed), last_observation=observed, clean_stop=True)
    return validate_budget(value)


def reopen_budget(budget, *, boot_id, observation):
    """Prepare a copied episode for an owned commit before fresh paused startup.

    Same-boot reopening never changes its QPC deadline. Every execution consumes
    the clean-Stop marker so an earlier Stop cannot authorize an unclean reboot.
    """
    value = validate_budget(budget); _boot(boot_id)
    same_boot = boot_id == value['episode']['boot_id']
    observed = _next_observation(value, observation, same_boot=same_boot)
    if same_boot:
        remaining = _cap(value, observed)
    else:
        _require(value['clean_stop'], 'Changed boot requires a recorded clean Stop')
        grant = min(value['remaining_cap_ns'], value['expires_utc_ns'] - observed['utc_ns'])
        _require(grant > 0, 'Original execution budget expired')
        exact_deadline = Fraction(observed['qpc_before']) + Fraction(grant, _NS)
        deadline = float(exact_deadline)
        if Fraction(deadline) > exact_deadline:
            deadline = math.nextafter(deadline, -math.inf)
        value['episode'] = {'index': value['episode']['index'] + 1, 'boot_id': boot_id,
                            'deadline': deadline, 'observation': observed, 'granted_ns': grant}
        remaining = _cap(value, observed)
    _require(remaining > 0, 'Original execution budget expired')
    value.update(remaining_cap_ns=remaining, last_observation=observed, clean_stop=False)
    return validate_budget(value)
