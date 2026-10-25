# SPDX-License-Identifier: Apache-2.0
"""Read-only preview of the existing owner guards and RAM cache proposal.

This helper never samples hardware, launches anything, changes the durable task,
or reserves resources. Trusted host code must supply the verified owner planner,
the existing reader validators, and one bounded paired observation. A candidate
means the existing checks passed; full native model-load feasibility is unproved.
"""
from copy import deepcopy
import math

# These are the exact existing MemoryMonitor.sample guard thresholds, not
# estimates of model memory. Source identity and provenance are in README.
RAM_GUARD_GIB = 3
VRAM_GUARD_MIB = 250
MAX_OBSERVATION_AGE_S = 2
_CAPACITY_ERRORS = frozenset((
    'Startup lacks space for overhead, headroom and a 1 GiB resident cache',
    'Startup resident cache is below the supported policy minimum',
))


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        # Python integers are unbounded, but the clocks use finite C doubles.
        return False


def preview(config, host, gpu, *, observation_started_at, now_monotonic,
            now_wall, demand_state, startup_unresolved,
            plan_startup_cache, checked_host_sample, checked_gpu_sample):
    """Project existing controls using trusted observations, without applying.

    Callbacks are verified in-process owner/reader functions, not plugin or HTTP
    input. The real owner recomputes on fresh data before its authoritative load.
    The caller still owns foreground, parked identity and startup-error fences.
    """
    base = {'model_load_proved': False, 'resource_reservation': False,
            'native_launch_attempted': False}

    def result(state, reason, **fields):
        return {**base, 'state': state, 'reason': reason, **fields}

    if type(startup_unresolved) is not bool:
        return result('unknown', 'startup_outcome_not_classified')
    if startup_unresolved:
        return result('reconciliation_required', 'previous_startup_outcome_unresolved')
    if demand_state in ('absent', 'busy'):
        return result('not_requested', 'no_eligible_restoration_demand')
    if demand_state != 'eligible':
        return result('unknown', 'durable_demand_unknown')
    if (not all(_number(value) for value in (observation_started_at, now_monotonic, now_wall))
            or not 0 <= now_monotonic - observation_started_at <= MAX_OBSERVATION_AGE_S):
        return result('unknown', 'observation_stale_or_clock_invalid')
    try:
        # These are the existing actual validators, not inferred replacements.
        host = checked_host_sample(deepcopy(host))
        gpu = checked_gpu_sample(deepcopy(gpu))
        if not 0 <= now_wall - host['sampled_at'] <= MAX_OBSERVATION_AGE_S:
            return result('unknown', 'host_wall_clock_stale_or_regressed')
    except Exception as exc:
        return result('unknown', 'capacity_observation_invalid', error_type=type(exc).__name__)
    # Same unit/schema projection as MemoryMonitor.sample. This is telemetry
    # normalization, not a new model-memory formula or allocator.
    reading = {'sampled_at': host['sampled_at'], 'ram_total': host['total_ram_gib']*2**30,
        'ram_used': (host['total_ram_gib']-host['available_ram_gib'])*2**30,
        'ram_commit_required': True, 'ram_commit_available': host['available_commit_gib']*2**30,
        'gpu_mem_total': gpu['total_bytes'], 'gpu_mem_used': gpu['used_bytes']}
    capacity_refused = False
    try:
        # The existing function mutates its cfg args. It gets a private copy;
        # the real owner will plan again against its immutable verified profile.
        # Its existing profile validation must precede capacity classification:
        # a bad/disabled profile cannot become valid by waiting for more RAM.
        plan = plan_startup_cache(deepcopy(config), reading, now_wall)
    except Exception as exc:
        if type(exc) is RuntimeError and str(exc) in _CAPACITY_ERRORS:
            capacity_refused = True
        else:
            return result('unknown', 'existing_startup_planner_refused', error_type=type(exc).__name__)
    if (min(host['available_ram_gib'], host['available_commit_gib']) < RAM_GUARD_GIB
            or gpu['free_bytes']/2**20 < VRAM_GUARD_MIB):
        return result('waiting_capacity', 'existing_owner_emergency_guard_would_refuse')
    if capacity_refused:
        return result('waiting_capacity', 'existing_startup_cache_budget_does_not_fit')
    return result('candidate', 'existing_owner_guards_and_cache_proposal_passed',
                  observed_at_monotonic=observation_started_at,
                  observed_at_wall=host['sampled_at'], cache_plan=deepcopy(plan),
                  scope='RAM/cache proposal only; native GPU/workspace allocation remains authoritative')
