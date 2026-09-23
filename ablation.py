"""스위치를 하나씩 꺼서 무엇이 값을 했는지 가른다.
기본(전부 ON) 대비, 지정한 장치 하나만 끈 실행을 같은 질문으로 재현한다.
"""
import json
import sys

from graph import DEFAULT_ABLATION, run

DEVICES = ["isolation", "link_traversal", "peer_awareness", "revision_check"]


def run_ablation(question, device, run_id_prefix="abl"):
    assert device in DEVICES, f"알 수 없는 장치: {device} (선택지: {DEVICES})"
    off = dict(DEFAULT_ABLATION)
    off[device] = False
    result = run(question, run_id=f"{run_id_prefix}_no_{device}", ablation=off, tag=f"no_{device}")
    return result


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "eaT가 자평한 관리체계와 실제 위반 실태 사이의 간극은?"
    device = sys.argv[2] if len(sys.argv) > 2 else "peer_awareness"

    full = run(question, run_id="full", ablation=DEFAULT_ABLATION, tag="full")
    ablated = run_ablation(question, device)

    summary = {
        "question": question,
        "device_off": device,
        "full": {"report_path": full["report_path"], "isolation": full["log"]["isolation"], "revision_rounds_used": full["log"]["revision_rounds_used"]},
        "ablated": {"report_path": ablated["report_path"], "isolation": ablated["log"]["isolation"], "revision_rounds_used": ablated["log"]["revision_rounds_used"]},
    }
    with open("output/ablation.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
