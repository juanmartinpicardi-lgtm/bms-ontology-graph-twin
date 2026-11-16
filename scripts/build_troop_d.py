"""Build the Troop D synthetic test set: controls submittal PDF, BMS export and answer key.

    uv run python scripts/build_troop_d.py
"""
from projectmodel.troop_d import build, load_spec, write_answer_key, write_bms_export
from projectmodel.troop_d_submittal import render


def main() -> None:
    model = build(load_spec())
    summary = write_answer_key(model)
    rows = write_bms_export(model)
    pdf = render(model)
    print(f"answer key: {summary}")
    print(f"BMS export: {rows} objects")
    print(f"submittal: {pdf}")


if __name__ == "__main__":
    main()
