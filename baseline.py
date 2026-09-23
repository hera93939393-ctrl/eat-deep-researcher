"""혼자 하는 대조군. 같은 자료·같은 모델·같은 도구를 쓰되, 목차 분업 없이 한 에이전트가 전부 읽고 통째로 쓴다.
예산은 실제 멀티에이전트 실행이 소비한 총 글자수(subagent_chars_total)와 같거나 더 넉넉하게 준다 —
대조군의 손발을 묶어놓고 이긴 척하지 않기 위해서다.
"""
import json
import os
import sys
import time
import uuid

from dotenv import load_dotenv
from openai import OpenAI

from graph import build_source_list

load_dotenv()
client = OpenAI()

HERE = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    with open(os.path.join(HERE, path), encoding="utf-8") as f:
        return json.load(f)


def run_baseline(question, budget_chars=None, model=None, run_id=None):
    corpus = load_json("data/corpus.json")
    config = load_json("config.json")
    model = model or config["model"]["subagent_model"]
    run_id = run_id or str(uuid.uuid4())[:8]

    docs = corpus["docs"]
    total_corpus_chars = sum(len(d["title"]) + len(d["summary"]) for d in docs)
    budget_chars = budget_chars if budget_chars is not None else total_corpus_chars

    # 예산 안에서 최대한 담는다 — 코퍼스 전체가 예산보다 작으면 전체를 그대로 준다(대조군을 굶기지 않는다).
    kept, running = [], 0
    for d in docs:
        c = len(d["title"]) + len(d["summary"])
        if running + c > budget_chars and kept:
            break
        kept.append(d)
        running += c
    budget_fully_available = running <= budget_chars and len(kept) == len(docs)

    docs_text = "\n\n".join(f"[{d['id']}] {d['title']}\n{d['summary']}" for d in kept)

    system = f"""너는 혼자서 장문 보고서를 쓰는 에이전트다(분업 없음, 목차 설계도 네가 한다).
아래는 네게 주어진 원문 자료 전체다(이것만 근거로 써라 — 자료에 없는 사실을 지어내지 마라):

{docs_text}

질문에 답하는 장문 보고서를 작성하라. 절을 스스로 나눠 소제목을 달고, 문장 끝마다 근거 문서 id를 [id] 형태로 표기하라.
분량은 3000~4500자 정도로 하라(여러 서브에이전트가 나눠 쓴 보고서와 비슷한 총 분량)."""

    draft = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": f"질문: {question}"}],
    ).choices[0].message.content

    log = {
        "run_id": run_id,
        "tag": "baseline_solo",
        "question": question,
        "sections": [
            {
                "section_id": "solo",
                "role_id": "SOLO",
                "start_docs": [d["id"] for d in kept],
                "docs_read": [d["id"] for d in kept],
                "draft": draft,
            }
        ],
        "revision_rounds_used": 0,
        "revised_sections": [],
        "isolation": {
            "coordinator_chars_seen": None,
            "subagent_chars_seen": {"solo": running},
            "subagent_chars_total": running,
            "peer_awareness_chars": {"solo": 0},
            "total_corpus_chars": total_corpus_chars,
        },
        "budget_chars_given": budget_chars,
        "budget_chars_used": running,
        "budget_fully_available_ie_not_truncated": budget_fully_available,
        "plan_hallucination_errors_before_valid": [],
        "timestamp": time.time(),
    }

    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    with open(os.path.join(HERE, "output", "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    sources = build_source_list(log["sections"], {"solo": {"draft": draft}}, corpus)
    report_path = os.path.join(HERE, "output", "reports", f"{run_id}.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# {question}\n\n{draft}\n\n---\n\n## 출처\n\n{sources}\n")

    return {"report": draft, "log": log, "report_path": report_path}


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "eaT가 자평한 관리체계와 실제 위반 실태 사이의 간극은?"
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result = run_baseline(q, budget_chars=budget, run_id="baseline")
    print(result["report"])
    print("\n--- budget check ---")
    print(json.dumps({
        "budget_chars_given": result["log"]["budget_chars_given"],
        "budget_chars_used": result["log"]["budget_chars_used"],
        "not_truncated": result["log"]["budget_fully_available_ie_not_truncated"],
    }, ensure_ascii=False, indent=2))
