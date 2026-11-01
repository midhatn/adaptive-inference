# SPDX-License-Identifier: Apache-2.0
"""Explicit same-boot Windows clock for installed cross-process deadlines.

CPython3.11 and3.14 use different Windows monotonic clocks. Their performance
counters both use QPC; never reinterpret an untagged saved deadline as QPC.
Local elapsed timers and asyncio's own clock keep their existing semantics.
"""
import math
import os
import time

CLOCK_ID = 'windows-qpc-seconds-v1'


def execution_now():
    return time.perf_counter()


def execution_observation():
    """Bracket adjustable UTC with this boot's interval clock, without rounding."""
    before = execution_now()
    utc_ns = time.time_ns()
    return {'utc_ns': utc_ns, 'qpc_before': before, 'qpc_after': execution_now()}


def verify_execution_clock():
    info = time.get_clock_info('perf_counter')
    if (os.name != 'nt' or info.implementation != 'QueryPerformanceCounter()'
            or info.monotonic is not True or info.adjustable is not False
            or not math.isfinite(info.resolution) or info.resolution <= 0):
        raise RuntimeError('Installed execution requires the explicit Windows QPC clock')
    return CLOCK_ID
