# BSD-3-Clause. Copyright (c) 2020, the river developers.
# Exact selected upstream statements; see LICENSE.river and source-lock.json.
import numpy as np
from river import drift

np.random.seed(12345)
data_stream_3 = np.concatenate(
    (
        np.random.normal(0.0, 0.1, 500) > 0,
        np.random.normal(0.25, 0.1, 500) > 0,
        np.random.normal(0.0, 0.1, 500) > 0,
        np.random.normal(0.25, 0.1, 500) > 0,
    )
).astype(int)

def test_page_hinkley():
    expected_indices = [588, 1681]
    detected_indices = perform_test(drift.PageHinkley(mode="up"), data_stream_3)

    assert detected_indices == expected_indices

    expected_indices = [1172]
    detected_indices = perform_test(drift.PageHinkley(mode="down"), data_stream_3)

    assert detected_indices == expected_indices

    expected_indices = [588, 1097, 1585]
    detected_indices = perform_test(drift.PageHinkley(mode="both"), data_stream_3)

    assert detected_indices == expected_indices

def perform_test(drift_detector, data_stream):
    detected_indices = []
    for i, val in enumerate(data_stream):
        drift_detector.update(val)
        if drift_detector.drift_detected:
            detected_indices.append(i)
    return detected_indices
