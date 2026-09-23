"""
정답표도 판정 모델(LLM judge)도 쓰지 않는 지표.
전부 '만들어진 글(draft, [id] 인용 표시)'과 '실제로 읽은 자료 목록(docs_read/start_docs, 로그에 이미 기록됨)'만 대조해서 계산한다.

- ALARM: 0이어야 한다. 하나라도 나오면 설계가 어딘가 깨진 것.
- SIGNAL: 높낮이를 서로 비교하는 데 쓴다(런 간, 절 간). 절대적으로 좋다/나쁘다를 가르는 값이 아니다.
"""
import json
import re
from itertools import combinations

CITATION_RE = re.compile(r"\[\s*([A-Za-z0-9_]+)\s*\]")


def _citations(draft_text):
    return CITATION_RE.findall(draft_text)


def load_corpus_ids(corpus_path="data/corpus.json"):
    with open(corpus_path, encoding="utf-8") as f:
        corpus = json.load(f)
    return {d["id"] for d in corpus["docs"]}


# ---------------- ALARM (0이어야 함) ----------------

def invalid_citation_rate(run, corpus_ids):
    """장치: 서브에이전트의 근거 정확성 — 코퍼스에 존재조차 하지 않는 id를 인용했는가(완전한 지어냄)."""
    total, invalid = 0, 0
    for sec in run["sections"]:
        cited = _citations(sec["draft"])
        total += len(cited)
        invalid += sum(1 for c in cited if c not in corpus_ids)
    return invalid / total if total else 0.0


def unread_citation_rate(run):
    """장치: '읽은 것만 쓴다'는 근거성(grounding) 원칙 — 실제로 자기가 읽지 않은(docs_read에 없는) 문서를 인용했는가."""
    total, unread = 0, 0
    for sec in run["sections"]:
        cited = set(_citations(sec["draft"]))
        read = set(sec["docs_read"])
        total += len(cited)
        unread += len(cited - read)
    return unread / total if total else 0.0


def plan_id_hallucination_count(run):
    """장치: 코디네이터의 목차 설계 신뢰성 — 배정 단계에서 코퍼스에 없는 문서 id를 지어낸 횟수(재시도 전 기준)."""
    errs = run.get("plan_hallucination_errors_before_valid") or []
    return sum(len(e["bad_ids"]) for e in errs)


# ---------------- SIGNAL (비교용) ----------------

def isolation_ratio(run):
    """장치: 기획-읽기 분리(격리)가 실제로 이뤄지는가 — 코디네이터가 본 글자 수 / 서브에이전트들이 실제로 읽은 글자 수 합. 낮을수록 코디네이터는 목차만 보고 실제 본문은 서브에이전트만 봤다는 뜻."""
    iso = run["isolation"]
    total = iso["subagent_chars_total"]
    coord = iso["coordinator_chars_seen"]
    if coord is None or not total:
        return None  # 코디네이터-서브에이전트 분업 구조가 없는 실행(예: 혼자 하는 대조군)에는 이 지표가 정의되지 않는다
    return coord / total


def citation_density(run):
    """장치: 절 원고의 근거 촘촘함 — 원고 100자당 인용 태그([id]) 개수 평균. 너무 낮으면 근거 없이 서술만 하고 있다는 신호."""
    vals = []
    for sec in run["sections"]:
        n = len(sec["draft"])
        if n == 0:
            continue
        vals.append(len(_citations(sec["draft"])) / (n / 100))
    return sum(vals) / len(vals) if vals else 0.0


def assigned_doc_utilization(run):
    """장치: 코디네이터가 배정한 시작자료가 실제로 원고에 쓰였는가 — 배정된 start_docs 중 원고에서 인용된 비율. 낮으면 배정이 부적절했거나 서브에이전트가 자료를 활용하지 못한 것."""
    vals = []
    for sec in run["sections"]:
        start = set(sec["start_docs"])
        if not start:
            continue
        cited = set(_citations(sec["draft"]))
        vals.append(len(cited & start) / len(start))
    return sum(vals) / len(vals) if vals else 0.0


def link_traversal_ratio(run, section_budget_docs):
    """장치: 링크 탐색 장치가 실제로 쓰이는가 — 시작자료 외에 링크 따라 추가로 읽은 문서 수 / 예산. 0에 가까우면 링크 구조가 있어도 아무도 안 따라갔다는 뜻."""
    vals = []
    for sec in run["sections"]:
        extra = len(sec["docs_read"]) - len(sec["start_docs"])
        vals.append(max(extra, 0) / section_budget_docs if section_budget_docs else 0.0)
    return sum(vals) / len(vals) if vals else 0.0


def cross_section_overlap(run):
    """장치: 절 분할이 내용 기준으로 독립적인가 — 절 쌍마다 읽은 문서 집합의 자카드 유사도 평균. 너무 높으면 형식으로 나눠서 다들 같은 자료를 읽고 있다는 경고."""
    sections = run["sections"]
    if len(sections) < 2:
        return 0.0
    scores = []
    for a, b in combinations(sections, 2):
        sa, sb = set(a["docs_read"]), set(b["docs_read"])
        union = sa | sb
        scores.append(len(sa & sb) / len(union) if union else 0.0)
    return sum(scores) / len(scores)


def revision_rate(run):
    """장치: 점검(③) 단계가 실제로 판별력을 갖는가 — 전체 절 중 '부족' 판정을 받아 재파견된 절의 비율. 항상 0이면 점검이 늘 통과만 시키는 형식적 장치일 수 있다는 의심 신호."""
    sections = run["sections"]
    revised = run.get("revised_sections") or []
    return len(revised) / len(sections) if sections else 0.0


ALARM_FUNCS = {
    "invalid_citation_rate": invalid_citation_rate,
    "unread_citation_rate": unread_citation_rate,
    "plan_id_hallucination_count": plan_id_hallucination_count,
}

SIGNAL_FUNCS = {
    "isolation_ratio": isolation_ratio,
    "citation_density": citation_density,
    "assigned_doc_utilization": assigned_doc_utilization,
    "link_traversal_ratio": link_traversal_ratio,
    "cross_section_overlap": cross_section_overlap,
    "revision_rate": revision_rate,
}


def score_run(run, corpus_ids, section_budget_docs):
    alarms = {
        "invalid_citation_rate": invalid_citation_rate(run, corpus_ids),
        "unread_citation_rate": unread_citation_rate(run),
        "plan_id_hallucination_count": plan_id_hallucination_count(run),
    }
    signals = {
        "isolation_ratio": isolation_ratio(run),
        "citation_density": citation_density(run),
        "assigned_doc_utilization": assigned_doc_utilization(run),
        "link_traversal_ratio": link_traversal_ratio(run, section_budget_docs),
        "cross_section_overlap": cross_section_overlap(run),
        "revision_rate": revision_rate(run),
    }
    return {"run_id": run["run_id"], "alarms": alarms, "signals": signals}


if __name__ == "__main__":
    import sys

    corpus_ids = load_corpus_ids()
    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)
    budget = config["budget"]["section_budget_docs"]

    path = sys.argv[1] if len(sys.argv) > 1 else "output/runs.jsonl"
    with open(path, encoding="utf-8") as f:
        runs = [json.loads(line) for line in f if line.strip()]

    for run in runs:
        result = score_run(run, corpus_ids, budget)
        print(json.dumps(result, ensure_ascii=False, indent=2))
