from pricor.samples import SAMPLES, XLSX_CONTENT_TYPE

from .test_api import make_client


def test_lists_the_shipped_samples_with_localized_text():
    response = make_client().get("/samples")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [sample.id for sample in SAMPLES]
    first = body[0]
    assert set(first) == {"id", "file_name", "supplier_name", "week", "title", "description"}
    assert first["file_name"].endswith(".xlsx")
    assert first["supplier_name"] == "Distribuidora Ejemplo"
    assert first["week"] == 1
    assert set(first["title"]) == {"en", "es"} and set(first["description"]) == {"en", "es"}
    assert all(first["title"].values()) and all(first["description"].values())


def test_returns_the_sample_file_with_its_content_type_and_name():
    sample = SAMPLES[1]

    response = make_client().get(f"/samples/{sample.id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_CONTENT_TYPE
    assert sample.file_name in response.headers["content-disposition"]
    assert response.content == sample.path.read_bytes()


def test_unknown_sample_is_a_404_in_the_error_envelope():
    response = make_client().get("/samples/no-such-sample")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "sample_not_found"


def test_served_samples_can_start_an_import():
    client = make_client()
    sample = SAMPLES[0]
    content = client.get(f"/samples/{sample.id}").content

    response = client.post(
        "/sheets", files={"file": (sample.file_name, content, XLSX_CONTENT_TYPE)}
    )

    assert response.status_code == 200
    assert response.json() == {"sheets": ["Lista de precios"]}
