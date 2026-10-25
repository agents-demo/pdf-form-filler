import json

from pdffiller.data_store import DataStore


def _write(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_load_and_items(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"First name": "Jonathan", "Last name": "Baehr"}})
    ds = DataStore(p).load()
    assert ds.section_titles() == ["personal"]
    assert ds.items("personal") == {"First name": "Jonathan", "Last name": "Baehr"}


def test_get_case_insensitive(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"Phone": "0525115283"}})
    ds = DataStore(p).load()
    assert ds.get("phone") == "0525115283"


def test_upsert_new_key(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    ds.upsert("personal", "Email", "j@example.com")
    assert ds.get("Email", "personal") == "j@example.com"


def test_upsert_unknown_category_creates_section(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    ds.upsert("work", "Company", "Acme")
    assert ds.items("work") == {"Company": "Acme"}


def test_upsert_with_options(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    ds.upsert("personal", "Gender", "Male", options=["Male", "Female", "Other"])
    assert ds.get("Gender", "personal") == "Male"
    assert ds.get_options("Gender", "personal") == ["Male", "Female", "Other"]
    ds.save()
    reloaded = DataStore(p).load()
    assert reloaded.get_options("Gender", "personal") == ["Male", "Female", "Other"]
    raw = json.loads(p.read_text())
    assert raw["personal"]["Gender"] == {
        "value": "Male",
        "options": ["Male", "Female", "Other"],
    }


def test_language_heading(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "he", "personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    assert ds.language == "he"
    ds.set_language("en")
    ds.save()
    assert json.loads(p.read_text())["language"] == "en"


def test_language_defaults_to_en(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    assert ds.language == "en"


def test_save_roundtrip(tmp_path):
    p = tmp_path / "data.json"
    _write(p, {"language": "en", "personal": {"First name": "Jonathan"}})
    ds = DataStore(p).load()
    ds.upsert("personal", "Phone", "123")
    ds.save()
    reloaded = DataStore(p).load()
    assert reloaded.get("Phone") == "123"
    assert reloaded.get("First name") == "Jonathan"
