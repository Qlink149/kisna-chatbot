"""Run the entity extraction matrix and print a results table."""

import os
import sys

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_entity_extractor_matrix import MATRIX, _check_row

CHECK_KEYS = (
    "category",
    "categories",
    "multi_category",
    "secondary_category",
    "material_type",
    "unsupported_category",
    "unsupported_material",
    "min_price",
    "max_price",
    "title",
)


def main() -> None:
    print("Input | Expected | Actual | PASS/FAIL")
    print("-" * 100)
    passed = 0
    failed = 0
    for query, expected in MATRIX:
        ok, actual = _check_row(query, expected)
        passed += int(ok)
        failed += int(not ok)
        status = "PASS" if ok else "FAIL"
        exp = {k: expected[k] for k in CHECK_KEYS if k in expected}
        act = {k: actual.get(k) for k in CHECK_KEYS if k in expected}
        line = f"{query!r} | {exp} | {act} | {status}"
        print(line.encode("ascii", errors="replace").decode("ascii"))
    print(f"\nEntity matrix: {passed} passed, {failed} failed")


if __name__ == "__main__":
    main()
