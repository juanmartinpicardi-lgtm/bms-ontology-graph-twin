"""Build the Troop D synthetic test set: controls submittal PDF, BMS export, answer key, and the upload-ready test
package (test_packages/troop_d/) used to try the guided setup end to end.

    uv run python scripts/build_troop_d.py
"""
from projectmodel.troop_d import build, load_spec, write_answer_key, write_bms_export, write_test_package
from projectmodel.troop_d_submittal import render


def main() -> None:
    model = build(load_spec())
    summary = write_answer_key(model)
    rows = write_bms_export(model)
    pdf = render(model)
    print(f"answer key: {summary}")
    print(f"BMS export: {rows} objects")
    print(f"submittal: {pdf}")
    for path in write_test_package():
        print(f"test package: {path.name} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
