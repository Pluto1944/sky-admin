from __future__ import annotations

from modules.farm_system.registration import FarmRegistrationService
from scripts.audit_farm_system import audit_farm_system
from tests.farm_system.test_registration import FakeCocClient, _setup_pair, _war


def test_audit_accepts_consistent_settlement(db):
    _, first, _, _, _, round_row = _setup_pair(db)
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        first, round_row["id"], "#AAA"
    )
    assert audit_farm_system(db.conn) == []


def test_audit_detects_score_and_missing_ledger(db):
    _, first, _, clan_a, _, round_row = _setup_pair(db)
    FarmRegistrationService(db.conn, FakeCocClient(_war("#AAA", "#BBB"))).register(
        first, round_row["id"], "#AAA"
    )
    db.conn.execute("UPDATE farm_clans SET score = 99 WHERE id = ?", (clan_a["id"],))
    ledger_id = db.conn.execute(
        "SELECT id FROM farm_score_ledger WHERE clan_id = ?", (clan_a["id"],)
    ).fetchone()[0]
    db.conn.execute("DELETE FROM farm_score_ledger WHERE id = ?", (ledger_id,))
    db.conn.commit()

    codes = {issue["code"] for issue in audit_farm_system(db.conn)}
    assert "score_current_mismatch" in codes
    assert "match_base_ledger_count" in codes
