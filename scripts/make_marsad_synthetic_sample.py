"""Generate interop/samples/marsad_context_SYNTHETIC_sample.geojson from seeded SYNTHETIC cells. Not real data."""

from pathlib import Path

from tashwish.interop.marsad import to_geojson, validate_feature_collection
from tashwish.interop.synthetic import synthetic_cells

OUT = Path(__file__).resolve().parents[1] / "interop" / "samples" / "marsad_context_SYNTHETIC_sample.geojson"

if __name__ == "__main__":
    cb, ev = synthetic_cells(seed=7)
    fc = to_geojson(
        cb,
        ev,
        dataset_version="SYNTHETIC-sample-1",
        data_class="synthetic",
        generated_at="2026-01-02T00:00:00Z",
        commit="synthetic-sample",
        path=OUT,
    )
    problems = validate_feature_collection(fc)
    assert not problems, problems
    print(f"wrote {OUT} with {len(fc['features'])} features")
