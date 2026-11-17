"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    tp = fp = fn = tn = 0
    for h, j in zip(human, judge, strict=True):
        h_pos, j_pos = h == POS, j == POS
        if h_pos and j_pos:
            tp += 1
        elif not h_pos and j_pos:
            fp += 1
        elif h_pos and not j_pos:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    # precision = tp/(tp+fp), recall = tp/(tp+fn); return 0.0 when the denominator is 0
    cm = confusion(human, judge)
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    n = len(human)
    if n == 0 or len(judge) != n:
        raise ValueError("kappa undefined for empty or mismatched labels")
    cm = confusion(human, judge)
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    p_o = (tp + tn) / n
    p_h_pos = (tp + fn) / n
    p_j_pos = (tp + fp) / n
    p_e = p_h_pos * p_j_pos + (1.0 - p_h_pos) * (1.0 - p_j_pos)
    if p_e == 1.0:
        raise ValueError("kappa undefined when expected agreement p_e == 1")
    return (p_o - p_e) / (1.0 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    # (p_obs + spec - 1) / (sens + spec - 1)
    denom = sensitivity + specificity - 1.0
    if denom == 0.0:
        return 0.0
    raw = (observed_rate + specificity - 1.0) / denom
    return max(0.0, min(1.0, raw))


def _numpy_generator(seed: int):
    """numpy.random.default_rng(seed), with a PCG64 bypass when mtrand.pyd is OS-blocked."""
    import importlib.util
    import sys
    import types
    from pathlib import Path

    import numpy as np

    # If a previous failed import left a broken numpy.random stub, rebuild it.
    existing = sys.modules.get("numpy.random")
    if existing is not None and hasattr(existing, "default_rng"):
        try:
            return existing.default_rng(seed)
        except Exception:
            pass
    try:
        return np.random.default_rng(seed)
    except Exception:
        root = Path(np.__file__).resolve().parent / "random"
        pkg = types.ModuleType("numpy.random")
        pkg.__path__ = [str(root)]
        sys.modules["numpy.random"] = pkg

        def _load(modname: str, filename: str):
            path = root / filename
            spec = importlib.util.spec_from_file_location(modname, path)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            short = modname.rsplit(".", 1)[-1]
            setattr(pkg, short, mod)
            return mod

        _load("numpy.random.bit_generator", "bit_generator.cp312-win_amd64.pyd")
        _load("numpy.random._common", "_common.cp312-win_amd64.pyd")
        _load("numpy.random._bounded_integers", "_bounded_integers.cp312-win_amd64.pyd")
        pcg = _load("numpy.random._pcg64", "_pcg64.cp312-win_amd64.pyd")
        gen = _load("numpy.random._generator", "_generator.cp312-win_amd64.pyd")
        pkg.Generator = gen.Generator
        pkg.PCG64 = pcg.PCG64
        pkg.default_rng = lambda s=None, _g=gen, _p=pcg: _g.Generator(_p.PCG64(s))
        return pkg.default_rng(seed)


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np

    aa = np.asarray(list(a), dtype=float)
    bb = np.asarray(list(b), dtype=float)
    if aa.shape != bb.shape:
        raise ValueError("paired_bootstrap requires same-length sequences")
    n = int(aa.size)
    if n == 0 or np.array_equal(aa, bb):
        return 0.0, 0.0, 0.0
    delta = float(aa.mean() - bb.mean())
    # Direct PCG64 percentile bootstrap (matches scipy method="percentile" + default_rng).
    gen = _numpy_generator(rng)
    diffs = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        idx = gen.integers(0, n, size=n)
        diffs[i] = float(aa[idx].mean() - bb[idx].mean())
    alpha = (1.0 - confidence) / 2.0
    lo = float(np.percentile(diffs, 100.0 * alpha))
    hi = float(np.percentile(diffs, 100.0 * (1.0 - alpha)))
    return delta, lo, hi


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    import math

    if k <= 0 or k > n or c < 0 or c > n:
        raise ValueError(f"invalid (n, c, k)=({n}, {c}, {k})")
    # If fewer than k failures, every k-subset has ≥1 pass → probability 1.
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    import math

    if k <= 0 or k > n or c < 0 or c > n:
        raise ValueError(f"invalid (n, c, k)=({n}, {c}, {k})")
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)
