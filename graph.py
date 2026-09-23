"""
① 기획 -> ② 배치(서브에이전트 동시 파견) -> ③ 점검(재파견) -> ④ 종합
전 과정에서 "누가 몇 글자를 봤는지"를 계측해 격리를 숫자로 증명한다.
"""
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

HERE = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    with open(os.path.join(HERE, path), encoding="utf-8") as f:
        return json.load(f)


def chat(model, system, user, response_format_json=True):
    kwargs = dict(
        model=model,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    if response_format_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


# ---------- ① 기획 ----------

DEFAULT_ABLATION = {"isolation": True, "link_traversal": True, "peer_awareness": True, "revision_check": True}


def shallow_index(corpus):
    """코디네이터에게 줄 '얕은 목차' — id/title/category만. summary(본문)는 절대 포함하지 않는다."""
    return [{"id": d["id"], "title": d["title"], "category": d["category"]} for d in corpus["docs"]]


def full_index(corpus):
    """isolation 장치를 껐을 때 코디네이터에게 주는 버전 — summary(본문)까지 전부 포함."""
    return [{"id": d["id"], "title": d["title"], "category": d["category"], "summary": d["summary"]} for d in corpus["docs"]]


def plan_toc(question, corpus, config, ablation=None):
    ablation = ablation or DEFAULT_ABLATION
    roles = config["roles"]
    role_names = "\n".join(f"- {r['role_id']}: {r['name']} (홈 카테고리 문서 예: {r['home_docs'][:3]})" for r in roles)
    index = full_index(corpus) if not ablation.get("isolation", True) else shallow_index(corpus)
    index_text = json.dumps(index, ensure_ascii=False)

    system = f"""너는 딥리서처의 코디네이터다. 아래 질문에 답하는 장문 보고서의 목차를 짠다.
사용 가능한 역할 목록(모두 쓸 필요 없다 — 질문에 실제로 필요한 역할만 골라라):
{role_names}

규칙:
- 최대 절 수는 {config['budget']['max_sections_per_question']}개.
- 질문이 단 하나의 절로 충분히 답변 가능하면(예: 특정 법령 세부 수치를 묻는 질문) 절을 1개만 만들어라. 억지로 여러 절로 쪼개지 마라.
- 각 절에는 start_docs(문서 id 배열, 아래 목차에 실제로 있는 id만 사용)를 배정해야 한다. 목차에 없는 id를 지어내면 안 된다.
- 서로 다른 절이 같은 문서만 반복해서 다루지 않도록, 각 절의 역할이 겹치지 않게 배정하라.

다음은 문서 목차(id/title/category만 — 본문 없음):
{index_text}

JSON으로만 답하라: {{"sections": [{{"section_id": "...", "role_id": "...", "topic": "한 줄 주제", "start_docs": ["id1","id2"]}}]}}"""

    raw = chat(config["model"]["coordinator_model"], system, f"질문: {question}")
    plan = json.loads(raw)
    chars_seen = len(system) + len(question)  # 코디네이터가 실제로 본 글자 수(목차+질문. 본문 미포함)
    return plan["sections"], chars_seen, index


def validate_plan(sections, corpus):
    """배정이 실제 자료를 가리키는지 코드가 검사한다 — 모델이 지어낸 id는 걸러낸다."""
    valid_ids = {d["id"] for d in corpus["docs"]}
    errors = []
    for sec in sections:
        bad = [i for i in sec["start_docs"] if i not in valid_ids]
        if bad:
            errors.append({"section_id": sec["section_id"], "bad_ids": bad})
    return errors


# ---------- ② 배치: 서브에이전트 동시 파견 ----------

def docs_by_id(corpus):
    return {d["id"]: d for d in corpus["docs"]}


def gather_section_docs(section, corpus, budget, ablation=None):
    """시작자료 + 링크를 따라 예산 안에서 추가 탐색."""
    ablation = ablation or DEFAULT_ABLATION
    by_id = docs_by_id(corpus)
    read_ids = list(dict.fromkeys(section["start_docs"]))  # 순서 보존 중복 제거
    if not ablation.get("link_traversal", True):
        docs = [by_id[i] for i in read_ids if i in by_id]
        return docs, sum(len(d["title"]) + len(d["summary"]) for d in docs)
    frontier = list(read_ids)
    while frontier and len(read_ids) < len(section["start_docs"]) + budget["section_budget_docs"]:
        doc_id = frontier.pop(0)
        doc = by_id.get(doc_id)
        if not doc:
            continue
        for linked in doc.get("links", []):
            if linked not in read_ids and len(read_ids) < len(section["start_docs"]) + budget["section_budget_docs"]:
                read_ids.append(linked)
                frontier.append(linked)

    docs = [by_id[i] for i in read_ids if i in by_id]
    total_chars = sum(len(d["title"]) + len(d["summary"]) for d in docs)
    # 글자수 예산도 넘지 않도록 자른다
    kept, running = [], 0
    for d in docs:
        c = len(d["title"]) + len(d["summary"])
        if running + c > budget["section_budget_chars"] and kept:
            break
        kept.append(d)
        running += c
    return kept, running


def run_subagent(section, corpus, config, other_sections, revision_note=None, ablation=None):
    ablation = ablation or DEFAULT_ABLATION
    docs, chars_read = gather_section_docs(section, corpus, config["budget"], ablation)
    docs_text = "\n\n".join(f"[{d['id']}] {d['title']}\n{d['summary']}" for d in docs)

    if ablation.get("peer_awareness", True):
        peers = "\n".join(f"- {s['role_id']}({s['section_id']}): {s['topic']}" for s in other_sections if s["section_id"] != section["section_id"])
    else:
        peers = "(이 실행에서는 다른 절 정보가 제공되지 않음 — peer_awareness 장치 OFF)"
    peer_chars = len(peers)

    revision_text = f"\n\n[이전 초안에 대한 점검 피드백 — 반영해서 다시 써라]\n{revision_note}" if revision_note else ""

    system = f"""너는 '{section['role_id']}' 역할을 맡은 서브에이전트다. 주제: {section['topic']}
아래는 네게 배정된 원문 자료 전문이다(이것만 근거로 써라 — 자료에 없는 사실을 지어내지 마라):

{docs_text}

다른 절(남의 구역, 참고만 하고 내용을 베끼지 마라 — 이 절들은 본문을 보지 못했다):
{peers}
{revision_text}

너의 절 원고를 800~1200자 분량으로 작성하라. 문장 끝마다 근거 문서 id를 [id] 형태로 표기하라."""

    draft = chat(config["model"]["subagent_model"], system, "위 지시에 따라 절 원고를 작성하라.", response_format_json=False)
    return {
        "section_id": section["section_id"],
        "role_id": section["role_id"],
        "docs_read": [d["id"] for d in docs],
        "chars_read": chars_read,
        "peer_awareness_chars": peer_chars,
        "draft": draft,
    }


def dispatch_all(sections, corpus, config, revision_notes=None, ablation=None):
    revision_notes = revision_notes or {}
    results = {}
    with ThreadPoolExecutor(max_workers=len(sections)) as ex:
        futs = {
            ex.submit(run_subagent, sec, corpus, config, sections, revision_notes.get(sec["section_id"]), ablation): sec["section_id"]
            for sec in sections
        }
        for fut in as_completed(futs):
            r = fut.result()
            results[r["section_id"]] = r
    return results


# ---------- ③ 점검 ----------

def check_section(section, draft_text, config):
    system = """너는 점검자다. 아래 절 원고가 자기 주제에 비해 부실한지 판단하라(완전성만 본다 — 문체는 보지 마라).
JSON으로만 답하라: {"insufficient": true/false, "reason": "부족하면 한두 문장으로 무엇이 빠졌는지, 충분하면 빈 문자열"}"""
    raw = chat(config["model"]["coordinator_model"], system, f"절 주제: {section['topic']}\n\n원고:\n{draft_text}")
    return json.loads(raw)


# ---------- ④ 종합 ----------

def compile_report(question, sections, drafts, prior_drafts=None):
    """두 번째 원고가 나오면: 인용이 있던 절은 새 원고로 교체하되, 재파견 이력을 output에 남긴다.
    (첫 원고를 무조건 덮어쓰지 않는다 — 점검에서 '충분'으로 판정된 절은 그대로 둔다.)"""
    body = "\n\n".join(f"## {s['topic']} ({s['role_id']})\n\n{drafts[s['section_id']]['draft']}" for s in sections)
    return f"# {question}\n\n{body}\n"


# ---------- 실행 파이프라인 ----------

def run(question, run_id=None, ablation=None, tag="full"):
    ablation = ablation or DEFAULT_ABLATION
    run_id = run_id or str(uuid.uuid4())[:8]
    corpus = load_json("data/corpus.json")
    config = load_json("config.json")

    sections, coordinator_chars_seen, index = plan_toc(question, corpus, config, ablation)
    errors = validate_plan(sections, corpus)
    replan_attempts = 0
    while errors and replan_attempts < 1:
        sections, coordinator_chars_seen, index = plan_toc(
            question + f"\n\n[이전 계획에 존재하지 않는 문서 id가 있었다: {errors}. 목차에 있는 id만 사용해라.]",
            corpus, config, ablation,
        )
        errors = validate_plan(sections, corpus)
        replan_attempts += 1

    drafts = dispatch_all(sections, corpus, config, ablation=ablation)

    rounds = 0
    revision_notes = {}
    if ablation.get("revision_check", True):
        while rounds < config["budget"]["max_revision_rounds"]:
            insufficient = {}
            for sec in sections:
                verdict = check_section(sec, drafts[sec["section_id"]]["draft"], config)
                if verdict.get("insufficient"):
                    insufficient[sec["section_id"]] = verdict["reason"]
            if not insufficient:
                break
            resend_sections = [s for s in sections if s["section_id"] in insufficient]
            new_drafts = dispatch_all(resend_sections, corpus, config, revision_notes=insufficient, ablation=ablation)
            drafts.update(new_drafts)
            revision_notes.update(insufficient)
            rounds += 1

    revised_sections = list(revision_notes.keys())

    report = compile_report(question, sections, drafts)

    subagent_chars_seen = {sid: d["chars_read"] for sid, d in drafts.items()}
    peer_awareness_chars = {sid: d["peer_awareness_chars"] for sid, d in drafts.items()}
    total_corpus_chars = sum(len(d["title"]) + len(d["summary"]) for d in corpus["docs"])

    log = {
        "run_id": run_id,
        "tag": tag,
        "ablation": ablation,
        "question": question,
        "sections": [
            {
                "section_id": s["section_id"],
                "role_id": s["role_id"],
                "start_docs": s["start_docs"],
                "docs_read": drafts[s["section_id"]]["docs_read"],
                "draft": drafts[s["section_id"]]["draft"],
            }
            for s in sections
        ],
        "revision_rounds_used": rounds,
        "revised_sections": revised_sections,
        "isolation": {
            "coordinator_chars_seen": coordinator_chars_seen,
            "subagent_chars_seen": subagent_chars_seen,
            "subagent_chars_total": sum(subagent_chars_seen.values()),
            "peer_awareness_chars": peer_awareness_chars,
            "total_corpus_chars": total_corpus_chars,
        },
        "plan_hallucination_errors_before_valid": errors if replan_attempts else [],
        "timestamp": time.time(),
    }

    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    with open(os.path.join(HERE, "output", "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    report_path = os.path.join(HERE, "output", "reports", f"{run_id}.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return {"report": report, "log": log, "report_path": report_path}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "eaT가 자평한 관리체계와 실제 위반 실태 사이의 간극은?"
    result = run(q)
    print(result["report"])
    print("\n--- isolation proof ---")
    print(json.dumps(result["log"]["isolation"], ensure_ascii=False, indent=2))
