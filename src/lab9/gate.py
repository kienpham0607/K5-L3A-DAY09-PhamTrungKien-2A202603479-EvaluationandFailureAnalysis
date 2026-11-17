"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    import math

    from lab9.graders import GRADERS

    problems: list[str] = []
    metrics = pr.get("metrics") or {}
    for mid, val in metrics.items():
        if isinstance(val, (int, float)) and (math.isnan(val) or math.isinf(val)):
            problems.append(f"metric {mid} is NaN/inf")

    manifest = pr.get("manifest") or {}
    items = int(manifest.get("items") or 0)
    seeds = list(manifest.get("seeds") or [])
    rows = list(pr.get("rows") or [])
    expected_n = items * len(seeds) if items and seeds else None
    if expected_n is not None and len(rows) != expected_n:
        problems.append(f"row count {len(rows)} != items×seeds {expected_n}")

    pr_keys = {(r.get("item_id"), r.get("seed")) for r in rows}
    base_keys = {(r.get("item_id"), r.get("seed")) for r in (base.get("rows") or [])}
    if pr_keys != base_keys:
        problems.append("(item_id, seed) set differs from baseline")

    if pr.get("evaluator_failures"):
        problems.append("evaluator_failures non-empty")

    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for r in rows:
        for mid in graded:
            if mid in r and r.get(mid) is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for {mid}")
                break
        else:
            continue
        break

    # Slice tags per item must match baseline (hide-by-relabel attack).
    def _slices_by_item(report: dict) -> dict[str, frozenset[str]]:
        out: dict[str, frozenset[str]] = {}
        for r in report.get("rows") or []:
            iid = r.get("item_id")
            tags = frozenset(r.get("slices") or [])
            if iid in out and out[iid] != tags:
                out[iid] = frozenset()  # inconsistent within report → fail below
            else:
                out[iid] = tags
        return out

    pr_slices, base_slices = _slices_by_item(pr), _slices_by_item(base)
    for iid in set(pr_slices) & set(base_slices):
        if pr_slices[iid] != base_slices[iid]:
            problems.append(f"slice tags for {iid} differ from baseline")
            break

    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems.extend(_ratchet_problems(spec, base_spec))
    return problems


def _ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds/slices may only get stricter on the same eval-set version."""
    problems: list[str] = []
    base_metrics = {m["id"]: m for m in base_spec.get("metrics") or []}
    spec_metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for mid, bm in base_metrics.items():
        if mid not in spec_metrics:
            problems.append(f"metric {mid} disappeared (ratchet)")
            continue
        sm = spec_metrics[mid]
        if bm.get("blocking") and not sm.get("blocking"):
            problems.append(f"metric {mid} lost blocking (ratchet)")
        bth, sth = bm.get("threshold") or {}, sm.get("threshold") or {}
        if "min" in bth and "min" in sth and float(sth["min"]) < float(bth["min"]):
            problems.append(f"metric {mid} min loosened (ratchet)")
        if "max" in bth and "max" in sth and float(sth["max"]) > float(bth["max"]):
            problems.append(f"metric {mid} max loosened (ratchet)")
        if bth.get("no_significant_drop") and not sth.get("no_significant_drop"):
            problems.append(f"metric {mid} dropped no_significant_drop (ratchet)")

    base_slices = {(s.get("name"), s.get("metric")): s for s in base_spec.get("slices") or []}
    spec_slices = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for key, bs in base_slices.items():
        if key not in spec_slices:
            problems.append(f"slice {key[0]}/{key[1]} disappeared (ratchet)")
            continue
        ss = spec_slices[key]
        if bs.get("blocking") and not ss.get("blocking"):
            problems.append(f"slice {key[0]}/{key[1]} lost blocking (ratchet)")
        if "min" in bs and "min" in ss and float(ss["min"]) < float(bs["min"]):
            problems.append(f"slice {key[0]}/{key[1]} min loosened (ratchet)")
        if bs.get("no_significant_drop") and not ss.get("no_significant_drop"):
            problems.append(f"slice {key[0]}/{key[1]} dropped no_significant_drop (ratchet)")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)
        verdict, note = "ok", ""
        val: float | None
        if not a:
            val, verdict = None, "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < float(s["min"]):
                verdict = "fail"
            if s.get("no_significant_drop"):
                b = per_item(base, metric, slice_name=name)
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap(
                        [a[k] for k in keys], [b[k] for k in keys],
                        n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                    )
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
