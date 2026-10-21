"""Summarize results.xml per test function, for docs/traceability.md.

Run: .venv/bin/python ../agents/erin/trace.py ../agents/erin/results.xml
Prints one line per test function: file::function  passed/total  status.
"""

import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict


def main(path):
    root = ET.parse(path).getroot()
    funcs = OrderedDict()
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    for case in root.iter("testcase"):
        name = re.sub(r"\[.*\]$", "", case.get("name"))
        key = f"{case.get('classname')}::{name}"
        outcome = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        totals[outcome] += 1
        entry = funcs.setdefault(key, {"passed": 0, "failed": 0, "skipped": 0})
        entry[outcome] += 1
    for key, e in funcs.items():
        n = sum(e.values())
        status = "FAIL" if e["failed"] else ("SKIP" if e["skipped"] else "pass")
        print(f"{key}  {e['passed']}/{n}  {status}")
    for suite in root.iter("testsuite"):
        print("suite:", {k: suite.get(k) for k in ("tests", "failures", "errors", "skipped", "time", "timestamp")})
    print("totals:", totals)


if __name__ == "__main__":
    main(sys.argv[1])
