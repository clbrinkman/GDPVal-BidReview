import importlib.util
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    spec = importlib.util.spec_from_file_location("bidreview_app", ROOT / "platform" / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_db_module():
    spec = importlib.util.spec_from_file_location("bidreview_db", ROOT / "platform" / "db.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_app_imports_and_home_redirects():
    module = load_app_module()
    client = TestClient(module.app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/tenders"


def test_read_routes_do_not_seed_database(tmp_path):
    source = sqlite3.connect(ROOT / "data" / "platform.db")
    target_path = tmp_path / "platform.db"
    target = sqlite3.connect(target_path)
    source.backup(target)
    source.close()
    target.execute("DELETE FROM review_check")
    target.execute("DELETE FROM env_file")
    target.commit()
    target.close()

    module = load_app_module()
    module.DB_PATH = str(target_path)
    client = TestClient(module.app)
    assert client.get("/review").status_code == 200
    assert client.get("/expert").status_code == 200
    assert client.get("/case").status_code in {200, 303}

    check = sqlite3.connect(target_path)
    assert check.execute("SELECT COUNT(*) FROM review_check").fetchone()[0] == 0
    assert check.execute("SELECT COUNT(*) FROM env_file").fetchone()[0] == 0
    check.close()


def test_migration_initializes_an_empty_database_idempotently(tmp_path):
    module = load_db_module()
    db_path = tmp_path / "nested" / "platform.db"
    first_tables = module.migrate(str(db_path))
    second_tables = module.migrate(str(db_path))

    assert first_tables == second_tables
    assert {"tender", "attachment", "rubric", "bid_case", "schema_migrations"} <= set(first_tables)
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 10
    assert {"expert_review", "expert_resolution", "audit_event"} <= set(first_tables)
    connection.close()


def test_independent_expert_reviews_create_conflict_and_adjudication(tmp_path):
    db_module = load_db_module()
    db_path = tmp_path / "platform.db"
    db_module.migrate(str(db_path))
    connection = sqlite3.connect(db_path)
    connection.execute("""INSERT INTO review_check
        (case_id,node,item,artifact,expert_area,required_reviews)
        VALUES ('CASE-1','EXP','是否成立？','盲审证据','inj',2)""")
    check_id = connection.execute("SELECT id FROM review_check").fetchone()[0]
    connection.commit()
    connection.close()

    app_module = load_app_module()
    app_module.DB_PATH = str(db_path)
    client = TestClient(app_module.app, follow_redirects=False)
    page = client.get(f"/expert/task/{check_id}?reviewer=expert-a")
    assert page.status_code == 200
    assert "CASE-1" not in page.text
    for reviewer, verdict in [("expert-a", "自然"), ("expert-b", "不像真实偏差")]:
        response = client.post(f"/expert/task/{check_id}", data={
            "reviewer": reviewer, "verdict": verdict, "confidence": 4,
            "rationale": "基于材料的独立判断", "evidence_refs": "第2段", "mode": "submit"
        })
        assert response.status_code == 303

    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM expert_resolution WHERE check_id=?", (check_id,)).fetchone()[0] == "conflict"
    assert connection.execute("SELECT COUNT(*) FROM expert_review WHERE check_id=?", (check_id,)).fetchone()[0] == 2
    connection.close()

    response = client.post(f"/expert/conflicts/{check_id}", data={
        "adjudicator": "expert-c", "verdict": "自然", "rationale": "采纳专家 A 的领域证据"
    })
    assert response.status_code == 303
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT status FROM expert_resolution WHERE check_id=?", (check_id,)).fetchone()[0] == "adjudicated"
    assert connection.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 3
    connection.close()
