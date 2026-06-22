"""Smoke tests for KML import + listing + visibility toggle + delete."""

from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient

from tests.conftest import admin_token, auth, register

_SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Style id="red">
      <LineStyle><color>ff0000ff</color><width>3</width></LineStyle>
      <PolyStyle><color>7f0000ff</color></PolyStyle>
    </Style>
    <Placemark><name>HQ</name><styleUrl>#red</styleUrl>
      <Point><coordinates>4.35,50.85,0</coordinates></Point>
    </Placemark>
    <Placemark><name>Route Alpha</name>
      <LineString><coordinates>4.30,50.80 4.35,50.85 4.40,50.86</coordinates></LineString>
    </Placemark>
    <Placemark><name>AO Bravo</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        4.20,50.75 4.45,50.75 4.45,50.95 4.20,50.95 4.20,50.75
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
  </Document>
</kml>
"""


def _upload(
    client: TestClient, token: str, data: bytes = _SAMPLE_KML, name: str = "ao.kml"
):
    return client.post(
        "/kml-layers",
        headers=auth(token),
        files={"file": (name, BytesIO(data), "application/vnd.google-earth.kml+xml")},
    )


def test_upload_and_list(client: TestClient) -> None:
    tok = admin_token(client)
    r = _upload(client, tok)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["feature_count"] == 3
    assert body["name"] == "ao"
    assert len(body["features"]) == 3
    types = {f["type"] for f in body["features"]}
    assert types == {"POINT", "LINE", "POLYGON"}

    r = client.get("/kml-layers", headers=auth(tok))
    assert r.status_code == 200, r.text
    layers = r.json()
    assert len(layers) == 1
    assert layers[0]["feature_count"] == 3
    assert layers[0]["bbox"] is not None and len(layers[0]["bbox"]) == 4


def test_get_detail_includes_features_and_coords_are_lat_lon(
    client: TestClient,
) -> None:
    tok = admin_token(client)
    layer_id = _upload(client, tok).json()["id"]

    r = client.get(f"/kml-layers/{layer_id}", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    point = next(f for f in body["features"] if f["type"] == "POINT")
    # coords are [lat, lon] — lat must be ~50.85, lon ~4.35
    assert abs(point["coords"][0] - 50.85) < 1e-6
    assert abs(point["coords"][1] - 4.35) < 1e-6


def test_patch_visibility_round_trip(client: TestClient) -> None:
    tok = admin_token(client)
    layer_id = _upload(client, tok).json()["id"]

    r = client.patch(
        f"/kml-layers/{layer_id}", headers=auth(tok), json={"visible": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["visible"] is False

    layers = client.get("/kml-layers", headers=auth(tok)).json()
    assert layers[0]["visible"] is False


def test_operator_cannot_upload_or_delete(client: TestClient) -> None:
    admin_tok = admin_token(client)
    _, op_token, _ = register(client, role="OPERATOR")

    # Operators can read.
    assert client.get("/kml-layers", headers=auth(op_token)).status_code == 200

    # But not upload …
    r = _upload(client, op_token)
    assert r.status_code == 403

    # … or delete.
    layer_id = _upload(client, admin_tok).json()["id"]
    assert (
        client.delete(f"/kml-layers/{layer_id}", headers=auth(op_token)).status_code
        == 403
    )


def test_upload_rejects_bad_extension(client: TestClient) -> None:
    tok = admin_token(client)
    r = _upload(client, tok, name="bad.txt")
    assert r.status_code == 400


def test_upload_rejects_empty_kml(client: TestClient) -> None:
    tok = admin_token(client)
    empty = b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document></Document></kml>'
    r = _upload(client, tok, data=empty)
    assert r.status_code == 400


def test_delete_layer(client: TestClient) -> None:
    tok = admin_token(client)
    layer_id = _upload(client, tok).json()["id"]
    assert (
        client.delete(f"/kml-layers/{layer_id}", headers=auth(tok)).status_code == 204
    )
    assert client.get(f"/kml-layers/{layer_id}", headers=auth(tok)).status_code == 404


def test_download_kml_returns_raw_xml(client: TestClient) -> None:
    tok = admin_token(client)
    layer_id = _upload(client, tok).json()["id"]
    r = client.get(f"/kml-layers/{layer_id}/kml", headers=auth(tok))
    assert r.status_code == 200
    assert b"<kml" in r.content
