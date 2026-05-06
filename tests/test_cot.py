from backend.cot.cot import CotEvent, parse_cot


def test_cot_roundtrip() -> None:
    ev = CotEvent(
        uid="ALPHA-1",
        type="a-f-G-U-C",
        lat=50.85,
        lon=4.35,
        callsign="ALPHA-1",
    )
    xml = ev.to_xml()
    parsed = parse_cot(xml)
    assert parsed.uid == "ALPHA-1"
    assert parsed.callsign == "ALPHA-1"
    assert abs(parsed.lat - 50.85) < 1e-6
    assert abs(parsed.lon - 4.35) < 1e-6
