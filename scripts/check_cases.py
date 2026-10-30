#!/usr/bin/env python3
"""Check a test case CSV against the v2 design standard."""
import csv
import re
import sys
from collections import Counter

FIELDS = ["用例编号", "需求编号", "设计方法", "覆盖维度", "主要类型", "所属模块",
          "用例标题", "前置条件", "优先级", "执行方式", "测试步骤", "期待结果",
          "测试结果", "备注"]
METHODS = ["等价类划分", "边界值分析", "判定表法", "因果图法", "状态迁移法",
           "场景法", "正交实验法", "错误推测法"]
TYPES = ["功能测试", "性能测试", "兼容性测试", "易用性测试", "安全测试"]


def count_lines(text):
    return len([ln for ln in (text or "").replace("\r\n", "\n").split("\n") if ln.strip()])


def main():
    if len(sys.argv) != 2:
        print("usage: check_cases.py <cases.csv>")
        return 2
    with open(sys.argv[1], encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("FAIL: no data rows")
        return 1
    missing_cols = [c for c in FIELDS if c not in rows[0]]
    if missing_cols:
        print("FAIL: missing columns:", "、".join(missing_cols))
        meta = ["需求编号", "设计方法", "覆盖维度", "主要类型"]
        if any(c in meta for c in missing_cols):
            print("HINT: this looks like a 10 column display table. Run the "
                  "checker on the full 14 field data file instead.")
        return 1

    failures, warnings = [], []

    numbers = []
    for i, r in enumerate(rows, start=2):
        num = (r["用例编号"] or "").strip()
        if not re.fullmatch(r"Test\d{3,}", num):
            failures.append(f"row {i}: malformed case number {num!r}")
        else:
            numbers.append(int(num[4:]))
        prio = (r["优先级"] or "").strip()
        if prio not in ("P0", "P1", "P2"):
            failures.append(f"row {i} ({num}): illegal priority {prio!r}")
        if not (r["需求编号"] or "").strip():
            failures.append(f"row {i} ({num}): empty requirement number")
        steps, results = count_lines(r["测试步骤"]), count_lines(r["期待结果"])
        if steps != results:
            failures.append(
                f"row {i} ({num}): {steps} steps but {results} expected results")

    dup = [n for n, c in Counter(numbers).items() if c > 1]
    if dup:
        failures.append("duplicate numbers: " + ", ".join(f"Test{n:03d}" for n in sorted(dup)))
    if numbers:
        gaps = sorted(set(range(min(numbers), max(numbers) + 1)) - set(numbers))
        if gaps:
            warnings.append("numbering gaps (verify these are retired numbers): "
                            + ", ".join(f"Test{n:03d}" for n in gaps))

    total = len(rows)
    p0 = sum(1 for r in rows if (r["优先级"] or "").strip() == "P0")
    share = p0 / total * 100
    if share > 15:
        failures.append(f"P0 share {share:.1f}% exceeds the 15% cap ({p0}/{total})")

    def check_values(cell_values, canon, label):
        hit, unknown = set(), set()
        for v in cell_values:
            v = (v or "").strip()
            if v in canon:
                hit.add(v)
            elif v:
                unknown.add(v)
        if unknown:
            failures.append(f"non-canonical {label} values: " + "、".join(sorted(unknown)))
        missing = [name for name in canon if name not in hit]
        if missing:
            failures.append(f"{label} with no coverage: " + "、".join(missing))
        return hit

    methods_hit = check_values([r["设计方法"] for r in rows], METHODS, "methods")
    types_hit = check_values([r["主要类型"] for r in rows], TYPES, "types")

    print(f"total cases: {total}")
    print(f"P0: {p0} ({share:.1f}%)")
    print(f"methods covered: {len(methods_hit)}/8")
    print(f"types covered: {len(types_hit)}/5")
    for w in warnings:
        print("WARN:", w)
    for f_ in failures:
        print("FAIL:", f_)
    if failures:
        print("RESULT: FAILED")
        return 1
    print("RESULT: PASSED" + (" with warnings" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
