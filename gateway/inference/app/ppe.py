"""정규화 검출 → 사람별 안전모·조끼 판정 + summary (docs/interfaces.md ② 필드 규칙).

매칭 규칙 (파라미터는 classes.yaml의 matching):
- PPE 박스가 사람 박스 안에 min_containment 이상 들어가고(PPE 박스 면적 기준),
  PPE 박스 중심이 사람 박스의 해당 세로 구간(helmet_region / vest_region, 사람 키 대비 비율)에 있으면 후보.
- PPE 박스 하나는 가장 많이 겹치는 사람 한 명에게만 붙는다.
- 한 사람에게 착용·미착용 박스가 같이 붙으면 conf가 높은 쪽을 따른다.
- 사람에게 붙지 않은 no_helmet / no_vest도 위반으로 집계한다 (사람 박스를 놓친 경우 대비).
"""
from __future__ import annotations

from dataclasses import dataclass

PPE_KINDS = {"helmet": ("helmet", "no_helmet"), "vest": ("vest", "no_vest")}


@dataclass(frozen=True)
class Matching:
    min_containment: float = 0.5
    helmet_region: tuple[float, float] = (-0.15, 0.4)
    vest_region: tuple[float, float] = (0.1, 0.85)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Matching":
        d = d or {}
        return cls(
            min_containment=float(d.get("min_containment", cls.min_containment)),
            helmet_region=tuple(d.get("helmet_region", cls.helmet_region)),
            vest_region=tuple(d.get("vest_region", cls.vest_region)),
        )


def _area(b: list[int]) -> float:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _containment(inner: list[int], outer: list[int]) -> float:
    ix = max(0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    a = _area(inner)
    return ix * iy / a if a else 0.0


def _fits(det_box: list[int], person_box: list[int], region: tuple[float, float]) -> bool:
    ph = person_box[3] - person_box[1]
    if ph <= 0:
        return False
    cx = (det_box[0] + det_box[2]) / 2
    cy = (det_box[1] + det_box[3]) / 2
    rel = (cy - person_box[1]) / ph
    return person_box[0] <= cx <= person_box[2] and region[0] <= rel <= region[1]


def judge(detections: list[dict], m: Matching = Matching()) -> tuple[list[dict], dict]:
    """detections([{cls, conf, box}], 정규화 이름) → (persons, summary)."""
    persons = [d for d in detections if d["cls"] == "person"]
    # 사람별·종류별로 붙은 PPE 검출
    attached: list[dict[str, list[dict]]] = [{"helmet": [], "vest": []} for _ in persons]
    unmatched_missing = {"helmet": False, "vest": False}

    for d in detections:
        kind = next((k for k, names in PPE_KINDS.items() if d["cls"] in names), None)
        if kind is None:
            continue
        region = m.helmet_region if kind == "helmet" else m.vest_region
        best, best_c = None, 0.0
        for i, p in enumerate(persons):
            c = _containment(d["box"], p["box"])
            if c >= m.min_containment and c > best_c and _fits(d["box"], p["box"], region):
                best, best_c = i, c
        if best is not None:
            attached[best][kind].append(d)
        elif d["cls"].startswith("no_"):
            unmatched_missing[kind] = True

    out_persons = []
    for p, att in zip(persons, attached):
        state = {}
        for kind, (worn_cls, _missing_cls) in PPE_KINDS.items():
            if not att[kind]:
                state[kind] = "unknown"
            else:
                top = max(att[kind], key=lambda d: d["conf"])
                state[kind] = "worn" if top["cls"] == worn_cls else "missing"
        out_persons.append({"box": p["box"], "conf": p["conf"], "helmet": state["helmet"], "vest": state["vest"]})

    missing_helmet = unmatched_missing["helmet"] or any(p["helmet"] == "missing" for p in out_persons)
    missing_vest = unmatched_missing["vest"] or any(p["vest"] == "missing" for p in out_persons)
    summary = {
        "person_count": len(out_persons),
        "missing_helmet": missing_helmet,
        "missing_vest": missing_vest,
        "violation": missing_helmet or missing_vest,
        "unknown_helmet_count": sum(p["helmet"] == "unknown" for p in out_persons),
        "unknown_vest_count": sum(p["vest"] == "unknown" for p in out_persons),
    }
    return out_persons, summary
