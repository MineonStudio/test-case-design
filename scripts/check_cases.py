#!/usr/bin/env python3
"""Check test cases against the v2 design standard.

Usage:
  python3 scripts/check_cases.py <用例文件.csv>   check one task's case file
  python3 scripts/check_cases.py <项目目录>        check the project's full set

Project mode collects the current (highest version) '-用例-v<N>.csv' of every
task directory, reads '<项目目录>/retired-ids.csv' to excuse numbering gaps and
judges method/type coverage on the full set. Single file mode only warns about
method/type coverage. Both modes run a reverse coverage check against the
traceability matrix in the '-测试分析说明-v<N>.md' file when one is found.
"""
import csv
import os
import re
import sys
from collections import Counter, defaultdict

FIELDS = ["用例编号", "需求编号", "设计方法", "覆盖维度", "主要类型", "所属模块",
          "用例标题", "前置条件", "优先级", "执行方式", "测试步骤", "期待结果",
          "测试结果", "备注"]
METHODS = ["等价类划分", "边界值分析", "判定表法", "因果图法", "状态迁移法",
           "场景法", "正交实验法", "错误推测法"]
TYPES = ["功能测试", "性能测试", "兼容性测试", "易用性测试", "安全测试"]
EXEC_MODES = ["AI 执行", "人工执行"]
RESULTS = ["未执行", "通过", "失败", "阻塞", "跳过"]
P0_CATEGORIES = ["主流程不通", "资金错误", "权限穿透", "状态错乱"]
P0_REASON_RE = re.compile(r"P0\s*理由[：:]\s*(主流程不通|资金错误|权限穿透|状态错乱)")
P0_WARN_TOTAL = 30.0
P0_WARN_MODULE = 50.0
CASE_FILE_RE = re.compile(r"-用例-v(\d+)\.csv$")
ANALYSIS_FILE_RE = re.compile(r"-测试分析说明-v(\d+)\.md$")
RETIRED_FILE = "retired-ids.csv"
SKIP_MARKS = ("缺UI稿", "缺接口文档")
EMPTY_MARKS = ("", "-", "—", "无", "N/A", "n/a")


def nospace(text):
    return re.sub(r"\s+", "", text or "")


def count_lines(text):
    return len([ln for ln in (text or "").replace("\r\n", "\n").split("\n") if ln.strip()])


def split_multi(cell):
    return [p.strip() for p in re.split(r"[、,，;；/\s]+", cell or "") if p.strip()]


def latest(directory, pattern):
    best, best_v = None, -1
    for name in os.listdir(directory):
        m = pattern.search(name)
        if m and int(m.group(1)) > best_v:
            best, best_v = os.path.join(directory, name), int(m.group(1))
    return best


def read_cases(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or [], list(reader)


def read_retired(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "用例编号" not in (reader.fieldnames or []):
            return None
        out = set()
        for r in reader:
            m = re.fullmatch(r"Test(\d{3,})", (r.get("用例编号") or "").strip())
            if m:
                out.add(int(m.group(1)))
        return out


def parse_matrix(md_path):
    """Return (rows, problem). rows are dicts keyed by normalized header."""
    with open(md_path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#") and "需求追溯矩阵" in ln:
            start = i + 1
            break
    if start is None:
        return None, "no '需求追溯矩阵' section found"
    table = []
    for ln in lines[start:]:
        s = ln.strip()
        if s.startswith("#"):
            break
        if s.startswith("|"):
            table.append(s)
        elif table and s:
            break
    if len(table) < 2:
        return None, "no markdown table under '需求追溯矩阵'"

    def cells(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    header = [nospace(c) for c in cells(table[0])]
    need = ["需求点编号", "UI元素编号", "接口错误码", "覆盖用例编号"]
    missing = [n for n in need if n not in header]
    if missing:
        return None, "matrix header lacks columns: " + "、".join(missing)
    rows = []
    for row in table[1:]:
        cs = cells(row)
        if all(re.fullmatch(r":?-+:?", c) for c in cs if c):
            continue
        rows.append({h: (cs[k] if k < len(cs) else "") for k, h in enumerate(header)})
    return rows, None


def reverse_coverage(md_path, case_numbers, warnings):
    rows, problem = parse_matrix(md_path)
    name = os.path.basename(md_path)
    if problem:
        warnings.append(f"reverse coverage skipped for {name}: {problem}")
        return None
    uncovered, unknown_refs = [], set()
    stats = {"需求点": [0, 0], "UI 元素": [0, 0], "接口错误码": [0, 0]}
    for r in rows:
        covered_ids = [c for c in split_multi(r.get("覆盖用例编号")) if c not in EMPTY_MARKS]
        valid = [c for c in covered_ids if c in case_numbers]
        unknown_refs.update(c for c in covered_ids if c not in case_numbers)
        is_covered = bool(valid)
        items = []
        req = (r.get("需求点编号") or "").strip()
        if req and nospace(req) != "无对应需求":
            items.append(("需求点", [req]))
        ui = r.get("UI元素编号") or ""
        if nospace(ui) not in SKIP_MARKS:
            items.append(("UI 元素", [x for x in split_multi(ui) if x not in EMPTY_MARKS]))
        codes = r.get("接口错误码") or ""
        if nospace(codes) not in SKIP_MARKS:
            items.append(("接口错误码", [x for x in split_multi(codes) if x not in EMPTY_MARKS]))
        for kind, ids in items:
            for x in ids:
                stats[kind][1] += 1
                if is_covered:
                    stats[kind][0] += 1
                else:
                    uncovered.append(f"{kind} {x}")
    if unknown_refs:
        warnings.append(f"{name}: matrix cites case numbers not in the case set: "
                        + "、".join(sorted(unknown_refs)))
    if uncovered:
        warnings.append(f"{name}: not covered by any case (add cases or write the reason "
                        "in 测试分析说明; unexplained ones are hard failures): "
                        + "、".join(uncovered))
    return stats


def main():
    if len(sys.argv) != 2:
        print("usage: check_cases.py <用例文件.csv | 项目目录>")
        return 2
    target = sys.argv[1]
    failures, warnings = [], []
    sources = []  # (case csv, analysis md or None)

    if os.path.isdir(target):
        project_mode = True
        retired = read_retired(os.path.join(target, RETIRED_FILE))
        if retired is None:
            warnings.append(f"{RETIRED_FILE} missing or unreadable in the project directory")
        for name in sorted(os.listdir(target)):
            d = os.path.join(target, name)
            if not os.path.isdir(d):
                continue
            case_file = latest(d, CASE_FILE_RE)
            if case_file:
                sources.append((case_file, latest(d, ANALYSIS_FILE_RE)))
            else:
                warnings.append(f"task directory without a '-用例-v<N>.csv' file: {name}")
        if not sources:
            print("FAIL: no '-用例-v<N>.csv' file found in any task directory")
            print("RESULT: FAILED")
            return 1
    elif os.path.isfile(target):
        project_mode = False
        task_dir = os.path.dirname(os.path.abspath(target))
        retired = read_retired(os.path.join(os.path.dirname(task_dir), RETIRED_FILE))
        analysis = None
        m = CASE_FILE_RE.search(os.path.basename(target))
        if m:
            prefix = os.path.basename(target)[:m.start()]
            cand = [n for n in os.listdir(task_dir)
                    if n.startswith(prefix) and ANALYSIS_FILE_RE.search(n)]
            if cand:
                analysis = os.path.join(task_dir, max(
                    cand, key=lambda n: int(ANALYSIS_FILE_RE.search(n).group(1))))
        sources.append((target, analysis))
    else:
        print(f"FAIL: no such file or directory: {target}")
        return 2

    rows = []
    for case_file, _ in sources:
        header, file_rows = read_cases(case_file)
        label = os.path.relpath(case_file, target) if project_mode else os.path.basename(case_file)
        missing_cols = [c for c in FIELDS if c not in header]
        if missing_cols:
            failures.append(f"{label}: missing columns: " + "、".join(missing_cols))
            if any(c in ["需求编号", "设计方法", "覆盖维度", "主要类型"] for c in missing_cols):
                failures.append(f"{label}: this looks like a 10 column display table. Run "
                                "the checker on the full 14 field data file instead.")
            continue
        if not file_rows:
            failures.append(f"{label}: no data rows")
        for i, r in enumerate(file_rows, start=2):
            rows.append((f"{label} row {i}", {k: (r.get(k) or "") for k in FIELDS}))

    if not rows:
        for f_ in failures or ["no data rows"]:
            print("FAIL:", f_)
        print("RESULT: FAILED")
        return 1

    numbers = []
    p0_by_module, total_by_module = Counter(), Counter()
    methods_by_module = defaultdict(set)
    for where, r in rows:
        num = r["用例编号"].strip()
        tag = f"{where} ({num})"
        m = re.fullmatch(r"Test(\d{3,})", num)
        if not m:
            failures.append(f"{where}: malformed case number {num!r}")
        else:
            numbers.append(int(m.group(1)))
        prio = r["优先级"].strip()
        if prio not in ("P0", "P1", "P2"):
            failures.append(f"{tag}: illegal priority {prio!r}")
        if not r["需求编号"].strip():
            failures.append(f"{tag}: empty requirement number")
        steps, results = count_lines(r["测试步骤"]), count_lines(r["期待结果"])
        if steps != results:
            failures.append(f"{tag}: {steps} steps but {results} expected results")
        mode = r["执行方式"].strip()
        if nospace(mode) not in [nospace(x) for x in EXEC_MODES]:
            failures.append(f"{tag}: 执行方式 must be AI 执行 or 人工执行, got {mode!r}")
        elif nospace(mode) == "人工执行" and not r["备注"].strip():
            failures.append(f"{tag}: 人工执行 needs the reason in 备注")
        result = r["测试结果"].strip()
        if result not in RESULTS:
            failures.append(f"{tag}: 测试结果 must be one of {'、'.join(RESULTS)}, got {result!r}")
        if prio == "P0" and not P0_REASON_RE.search(r["备注"]):
            failures.append(f"{tag}: P0 备注 lacks 'P0 理由：' with one of "
                            + "、".join(P0_CATEGORIES))
        module = r["所属模块"].strip() or "(未填模块)"
        total_by_module[module] += 1
        if prio == "P0":
            p0_by_module[module] += 1
        method = r["设计方法"].strip()
        if method in METHODS:
            methods_by_module[module].add(method)

    dup = [n for n, c in Counter(numbers).items() if c > 1]
    if dup:
        failures.append("duplicate numbers: " + ", ".join(f"Test{n:03d}" for n in sorted(dup)))
    if numbers:
        used = set(numbers)
        lo = 1 if project_mode else min(used)
        gaps = set(range(lo, max(used) + 1)) - used
        if retired is not None:
            reused = sorted(used & retired)
            if reused:
                failures.append("retired numbers reused: "
                                + ", ".join(f"Test{n:03d}" for n in reused))
            gaps -= retired
        gaps = sorted(gaps)
        if gaps:
            msg = ", ".join(f"Test{n:03d}" for n in gaps)
            if retired is not None:
                failures.append("numbering gaps not in retired-ids.csv (missing cases, or "
                                "register them as retired and rerun): " + msg)
            else:
                warnings.append("numbering gaps (no retired-ids.csv found to verify): " + msg)

    for module in sorted(total_by_module):
        ms = methods_by_module[module]
        if "错误推测法" not in ms:
            failures.append(f"module {module}: no 错误推测法 case")
        if len(ms) < 2:
            failures.append(f"module {module}: uses only one design method")

    total = len(rows)
    p0 = sum(p0_by_module.values())
    share = p0 / total * 100 if total else 0.0
    if share > P0_WARN_TOTAL:
        warnings.append(f"P0 share {share:.1f}% is over {P0_WARN_TOTAL:.0f}% ({p0}/{total}); "
                        "review the grading per module")
    for module in sorted(total_by_module):
        ms = p0_by_module[module] / total_by_module[module] * 100
        if ms > P0_WARN_MODULE:
            warnings.append(f"module {module}: P0 share {ms:.1f}% is over "
                            f"{P0_WARN_MODULE:.0f}%; review the grading")

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
            msg = f"{label} with no coverage: " + "、".join(missing)
            if project_mode:
                failures.append(msg)
            else:
                warnings.append(msg + " (single file; full coverage is judged on the "
                                "project directory)")
        return hit

    methods_hit = check_values([r["设计方法"] for _, r in rows], METHODS, "methods")
    types_hit = check_values([r["主要类型"] for _, r in rows], TYPES, "types")

    case_numbers = {r["用例编号"].strip() for _, r in rows}
    coverage = Counter()
    for case_file, analysis in sources:
        if analysis:
            stats = reverse_coverage(analysis, case_numbers, warnings)
            for kind, (c, t) in (stats or {}).items():
                coverage[kind + " covered"] += c
                coverage[kind + " total"] += t
        else:
            warnings.append(f"no '-测试分析说明-v<N>.md' next to {os.path.basename(case_file)}; "
                            "reverse coverage not checked")

    print(f"mode: {'project' if project_mode else 'single file'} "
          f"({len(sources)} case file{'s' if len(sources) != 1 else ''})")
    print(f"total cases: {total}")
    print(f"P0: {p0} ({share:.1f}%)")
    print(f"methods covered: {len(methods_hit)}/8")
    print(f"types covered: {len(types_hit)}/5")
    for kind in ("需求点", "UI 元素", "接口错误码"):
        if coverage[kind + " total"]:
            print(f"{kind} covered: {coverage[kind + ' covered']}/{coverage[kind + ' total']}")
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
