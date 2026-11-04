"""Hostile PDFs: reading one either works or says it can't."""

import time
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

FUZZ = settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@FUZZ
@given(data=st.data())
def test_fuzz_pdf_input(tmp_path: Path, data: st.DataObject) -> None:
    from cairnward_research.pdf import PdfError, PdfText, read_pdf
    from tests.fakes.pdf import make_pdf

    good = make_pdf([["Sleep and memory line one.", "Line two."]], title="T")
    how = data.draw(st.sampled_from(["flip", "truncate", "insert", "random"]))
    blob = bytearray(good)
    if how == "flip":
        for _ in range(data.draw(st.integers(1, 20))):
            i = data.draw(st.integers(0, len(blob) - 1))
            blob[i] = data.draw(st.integers(0, 255))
    elif how == "truncate":
        blob = blob[: data.draw(st.integers(0, len(blob)))]
    elif how == "insert":
        i = data.draw(st.integers(0, len(blob)))
        blob[i:i] = data.draw(st.binary(max_size=200))
    else:
        blob = bytearray(data.draw(st.binary(max_size=500)))
    path = tmp_path / f"fuzz-{time.monotonic_ns()}.pdf"
    path.write_bytes(bytes(blob))
    try:
        parsed = read_pdf(path)
    except PdfError:
        return
    assert isinstance(parsed, PdfText)
