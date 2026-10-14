from tools.benchmark.report import render_report


def record(expected, predicted, score, latency=0.03, origin="real", failed=False, sheet="s/1"):
    return {
        "expected": expected,
        "predicted": predicted,
        "score": score,
        "latency_seconds": latency,
        "origin": origin,
        "source": "dipel-x",
        "header": "H",
        "sheet": sheet,
        "failed": failed,
    }


def collected(device="cuda"):
    return {
        "meta": {
            "created": "2026-10-14T12:00:00",
            "device_requested": "auto",
            "device_used": device,
            "gpu": "RTX 4060 Laptop",
            "seed": 0,
            "validation_columns": 4,
            "held_out_columns": 4,
        },
        "classifiers": {
            "heuristics": {
                "validation": [record("code", "code", 0.9, None, "synthetic")] * 4,
                "held_out": [record("code", "code", 0.9, None)] * 3 + [record("ignore", "code", 0.7, None)],
            },
            "laya_finetuned": {
                "validation": [record("code", "code", 0.95, origin="synthetic")] * 4,
                "held_out": [record("code", "code", 0.9)] * 2 + [record("ignore", "ignore", 0.8)] * 2,
            },
            "gemma": {
                "validation": [record("code", "code", 0.9, 12.0, "synthetic")] * 4,
                "held_out": [record("code", "code", 0.9, 12.0)] * 3 + [record("ignore", "ignore", 0.9, 12.0, failed=True)],
            },
        },
    }


CALIBRATION = {
    "calibrated_on": "2026-10-14",
    "method": "lowest validation confidence with precision >= 0.95 and support >= 20",
    "target_precision": 0.95,
    "min_support": 20,
    "validation": {"n": 4, "real": 0, "synthetic": 4},
    "stages": {
        "laya": {"threshold": 0.5, "n": 4, "support": 4, "precision": 1.0, "reason": "met",
                 "real_only": {"support": 0, "precision": None}},
        "gemma": {"threshold": None, "n": 4, "support": 0, "precision": None, "reason": "too little support"},
    },
}

SUMMARY = {
    "total": 4,
    "resolved_by": {"laya": 3, "gemma": 0, "user": 1},
    "auto_resolved": 3,
    "auto_correct": 3,
    "auto_accuracy": 1.0,
    "escalation_rate": 0.25,
    "escalated_best_guess_correct": 1,
}
CASCADE = {
    "default_order": "laya>gemma",
    "chosen_order": "laya>gemma",
    "validation_orders": {"laya>gemma": SUMMARY},
    "held_out_replay": {"laya>gemma": SUMMARY},
    "real_held_out": {"order": "laya>gemma", "thresholds": {"laya": 0.5, "gemma": 0.75}, "summary": SUMMARY},
}


def test_the_held_out_table_reports_accuracy_per_classifier():
    text = render_report(collected(), None, CALIBRATION, CASCADE)

    assert "| Laya fine-tuned | 4 | 4 | 100.0% |" in text
    assert "| Heuristics | 4 | 3 | 75.0% |" in text
    assert "| Gemma | 4 | 3 | 75.0% |" in text  # the failed answer counts as wrong
    assert "1 failed" in text


def test_calibration_states_the_thresholds_the_support_and_the_uncertainty():
    text = render_report(collected(), None, CALIBRATION, CASCADE)

    assert "precision >= 0.95" in text
    assert "| laya | 0.5000 | 4 | 4 |" in text
    assert "| gemma | not calibrated | 4 | 0 |" in text
    assert "too little support" in text


def test_the_cascade_section_shows_who_settled_what_and_how_right_it_was():
    text = render_report(collected(), None, CALIBRATION, CASCADE)

    assert "| Laya | 3 |" in text
    assert "| User | 1 |" in text
    assert "100.0%" in text


def test_latency_has_gpu_and_cpu_rows_only_when_a_cpu_run_exists():
    gpu_only = render_report(collected(), None, CALIBRATION, CASCADE)
    both = render_report(collected(), collected("cpu"), CALIBRATION, CASCADE)

    assert "CPU run: not available" in gpu_only
    assert "Laya fine-tuned (cpu)" in both
    assert "Laya fine-tuned (cuda)" in both


def test_the_limits_section_is_always_present():
    text = render_report(collected(), None, CALIBRATION, CASCADE)

    assert "## Limits" in text
    assert "never used for calibration" in text
