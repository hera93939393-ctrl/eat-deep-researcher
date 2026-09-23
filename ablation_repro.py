"""peer_awareness 효과가 1회성 노이즈가 아니라 재현되는지 확인.
같은 질문으로 full/no_peer_awareness를 N회씩 반복 실행하고,
'FRAUD 절이 링크를 따라 p1(POLICY 계열)까지 인용했는가'를 매 회 기록한다.
"""
import json
import re
import sys

from graph import DEFAULT_ABLATION, run

QUESTION = "eaT가 자평한 '11개 서류심사·12개 현장심사' 관리체계와 실제 국감·언론에서 드러난 위반 실태 사이에는 어떤 간극이 있는가?"


def fraud_section(log):
    for sec in log["sections"]:
        if sec["role_id"] == "FRAUD":
            return sec
    return None


def reaches_policy(sec):
    if not sec:
        return None
    cited = set(re.findall(r"\[\s*([A-Za-z0-9_]+)\s*\]", sec["draft"]))
    policy_ids = {"p1", "p2", "p3", "p4"}
    return bool(cited & policy_ids)


def main(n=3):
    results = {"full": [], "no_peer_awareness": []}
    for i in range(n):
        full = run(QUESTION, run_id=f"repro_full_{i}", ablation=DEFAULT_ABLATION, tag="full")
        off = dict(DEFAULT_ABLATION); off["peer_awareness"] = False
        abl = run(QUESTION, run_id=f"repro_noPA_{i}", ablation=off, tag="no_peer_awareness")

        results["full"].append(reaches_policy(fraud_section(full["log"])))
        results["no_peer_awareness"].append(reaches_policy(fraud_section(abl["log"])))
        print(f"trial {i}: full_reaches_policy={results['full'][-1]}  no_peer_awareness_reaches_policy={results['no_peer_awareness'][-1]}")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    with open("output/ablation_repro.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    main(n)
