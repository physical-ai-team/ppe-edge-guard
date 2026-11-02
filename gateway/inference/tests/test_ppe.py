"""사람별 판정 규칙 (docs/interfaces.md ② 필드 규칙, 시연 시나리오)."""
import pytest

from app.ppe import Matching, judge

PERSON = [100, 100, 300, 700]           # 키 600
HEAD = [160, 90, 240, 170]              # 머리 (위로 약간 나감)
TORSO = [120, 250, 280, 450]            # 몸통


def det(cls, box, conf=0.8):
    return {"cls": cls, "conf": conf, "box": box}


@pytest.mark.parametrize(
    "scenario, ppe, helmet, vest, violation",
    [
        ("both_worn", [det("helmet", HEAD), det("vest", TORSO)], "worn", "worn", False),
        ("helmet_only", [det("helmet", HEAD), det("no_vest", TORSO)], "worn", "missing", True),
        ("vest_only", [det("no_helmet", HEAD), det("vest", TORSO)], "missing", "worn", True),
        ("none_worn", [det("no_helmet", HEAD), det("no_vest", TORSO)], "missing", "missing", True),
        ("person_only", [], "unknown", "unknown", False),
    ],
)
def test_one_person_scenarios(scenario, ppe, helmet, vest, violation):
    persons, s = judge([det("person", PERSON, 0.9), *ppe])
    assert persons == [{"box": PERSON, "conf": 0.9, "helmet": helmet, "vest": vest}]
    assert s["person_count"] == 1
    assert s["violation"] is violation
    assert s["missing_helmet"] is (helmet == "missing")
    assert s["missing_vest"] is (vest == "missing")
    assert s["unknown_helmet_count"] == (helmet == "unknown")
    assert s["unknown_vest_count"] == (vest == "unknown")


def test_no_person():
    persons, s = judge([])
    assert persons == []
    assert s == {"person_count": 0, "missing_helmet": False, "missing_vest": False, "violation": False,
                 "unknown_helmet_count": 0, "unknown_vest_count": 0}


def test_unmatched_missing_counts_as_violation():
    """사람 박스를 놓쳐도 no_helmet / no_vest 검출이 있으면 위반."""
    persons, s = judge([det("no_helmet", HEAD)])
    assert persons == [] and s["person_count"] == 0
    assert s["missing_helmet"] and s["violation"] and not s["missing_vest"]


def test_unmatched_worn_is_ignored():
    persons, s = judge([det("helmet", HEAD), det("vest", TORSO)])
    assert s["violation"] is False and s["person_count"] == 0


def test_conflict_takes_higher_conf():
    persons, s = judge([det("person", PERSON), det("helmet", HEAD, 0.47), det("no_helmet", HEAD, 0.48)])
    assert persons[0]["helmet"] == "missing"
    persons, _ = judge([det("person", PERSON), det("helmet", HEAD, 0.6), det("no_helmet", HEAD, 0.48)])
    assert persons[0]["helmet"] == "worn"


def test_region_rules():
    """조끼 위치의 안전모 박스, 발 위치의 조끼 박스는 그 사람에게 붙지 않는다."""
    feet = [120, 640, 280, 700]
    persons, s = judge([det("person", PERSON), det("helmet", TORSO), det("no_vest", feet)])
    assert persons[0]["helmet"] == "unknown"
    assert persons[0]["vest"] == "unknown"
    assert s["missing_vest"] is True  # 붙지 않은 no_vest는 위반으로 집계


def test_ppe_goes_to_one_person_only():
    """두 사람이 겹쳐 있어도 PPE 박스는 더 많이 들어간 한 명에게만 붙는다."""
    a = [100, 100, 300, 700]
    b = [220, 120, 420, 720]
    head_a = [130, 90, 210, 170]   # a 안에 완전히, b와는 거의 안 겹침
    persons, s = judge([det("person", a), det("person", b), det("no_helmet", head_a)])
    assert [p["helmet"] for p in persons] == ["missing", "unknown"]
    assert s["unknown_helmet_count"] == 1


def test_two_people_mixed():
    a, b = [100, 100, 300, 700], [500, 100, 700, 700]
    head_b, torso_b = [560, 90, 640, 170], [520, 250, 680, 450]
    persons, s = judge([
        det("person", a), det("helmet", HEAD), det("vest", TORSO),
        det("person", b), det("no_helmet", head_b), det("vest", torso_b),
    ])
    assert [(p["helmet"], p["vest"]) for p in persons] == [("worn", "worn"), ("missing", "worn")]
    assert s["violation"] and s["missing_helmet"] and not s["missing_vest"]


def test_matching_from_dict_overrides():
    m = Matching.from_dict({"min_containment": 0.9, "helmet_region": [0, 0.2]})
    assert m.min_containment == 0.9 and m.helmet_region == (0, 0.2) and m.vest_region == Matching().vest_region
    # 머리 박스가 사람 위로 나가 있어 containment < 0.9 → 붙지 않음
    persons, _ = judge([det("person", PERSON), det("helmet", HEAD)], m)
    assert persons[0]["helmet"] == "unknown"
