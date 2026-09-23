"""로컬 데모. 보고서만 보여주지 않고, 절마다 누가(role_id) 무엇을(start_docs/docs_read) 읽고
무엇을 썼는지(draft), 그리고 격리 증명 수치(코디네이터 vs 서브에이전트가 본 글자 수)까지 함께 보여준다.
실행: streamlit run app.py
"""
import json
import os

import streamlit as st

from graph import DEFAULT_ABLATION, run

HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="eaT 딥리서처 데모", layout="wide")


@st.cache_data
def load_corpus():
    with open(os.path.join(HERE, "data", "corpus.json"), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_questions():
    with open(os.path.join(HERE, "data", "questions.json"), encoding="utf-8") as f:
        return json.load(f)


def title_of(doc_id, corpus):
    for d in corpus["docs"]:
        if d["id"] == doc_id:
            return f"{doc_id} — {d['title']} ({d['category']})"
    return doc_id


def load_runs():
    path = os.path.join(HERE, "output", "runs.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def interpret_isolation(coord, total, corpus_total):
    """숫자만 던지지 않고, 그게 뭘 뜻하는지 사람 말로 바로 풀어준다."""
    if coord is None:
        return "이 실행은 혼자 하는 대조군(baseline)이라 코디네이터-서브에이전트 분리 자체가 없다 — 이 지표는 정의되지 않는다."

    ratio = coord / total if total else None
    lines = []

    if coord > corpus_total:
        lines.append(
            f"⚠️ 코디네이터가 본 글자 수({coord:,}자)가 **코퍼스 전체({corpus_total:,}자)보다도 많다** — "
            f"목차만 본 게 아니라 문서 본문을 통째로 봤다는 뜻이다(isolation 장치가 꺼졌을 때 나타나는 패턴)."
        )
    elif ratio is not None and ratio >= 1:
        lines.append(
            f"⚠️ 코디네이터가 본 글자 수가 서브에이전트가 읽은 총량보다 **많다**(비율 {ratio:.2f}) — "
            "'코디네이터는 목차만, 서브에이전트는 본문을' 이라는 격리 원칙이 이번 실행에서는 지켜지지 않았다."
        )
    elif ratio is not None and ratio < 0.6:
        lines.append(
            f"✅ 코디네이터가 본 글자 수가 서브에이전트 총량의 {ratio:.0%} 수준으로 훨씬 작다 — "
            "코디네이터는 제목·카테고리 같은 목차 정보만 보고, 실제 본문 읽기는 서브에이전트에게 맡겼다는 뜻이다(격리 원칙이 지켜짐)."
        )
    else:
        lines.append(
            f"코디네이터가 본 글자 수가 서브에이전트 총량의 {ratio:.0%} 수준이다 — 격리가 어느 정도는 되고 있지만 "
            "완전히 작지는 않다(목차 자체의 분량이 이미 꽤 크다는 뜻일 수 있다)."
        )
    return "\n\n".join(lines)


def render_isolation(iso):
    coord = iso.get("coordinator_chars_seen")
    total = iso.get("subagent_chars_total")
    corpus_total = iso.get("total_corpus_chars")
    c1, c2, c3 = st.columns(3)
    c1.metric("코디네이터가 본 글자 수 (목차만)", "해당없음(대조군)" if coord is None else f"{coord:,}자")
    c2.metric("서브에이전트가 읽은 글자 수 합", f"{total:,}자")
    c3.metric("코퍼스 전체 글자 수", f"{corpus_total:,}자")
    st.markdown(interpret_isolation(coord, total, corpus_total))


def render_run(log, corpus):
    st.subheader(log["question"])
    st.caption(f"run_id: {log['run_id']} · tag: {log.get('tag', '-')} · 재파견 바퀴: {log.get('revision_rounds_used', 0)}회"
               + (f" (재파견된 절: {', '.join(log['revised_sections'])})" if log.get("revised_sections") else ""))

    render_isolation(log["isolation"])

    st.markdown("---")
    st.markdown("### 절별 원고 — 누가 무엇을 읽고 무엇을 썼는가")
    for sec in log["sections"]:
        revised_mark = " 🔁재파견됨" if sec["section_id"] in (log.get("revised_sections") or []) else ""
        with st.expander(f"**{sec['role_id']}** — {sec['section_id']}{revised_mark}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**배정된 시작자료(start_docs)**")
                for d in sec["start_docs"]:
                    st.write("- " + title_of(d, corpus))
            with col2:
                st.markdown("**실제로 읽은 자료(docs_read, 링크 탐색 포함)**")
                for d in sec["docs_read"]:
                    extra = " 🔗링크로 추가 탐색" if d not in sec["start_docs"] else ""
                    st.write("- " + title_of(d, corpus) + extra)
            st.markdown("**원고**")
            st.write(sec["draft"])

    st.markdown("---")
    st.markdown("### 최종 종합본")
    body = "\n\n".join(f"## {s['role_id']}\n\n{s['draft']}" for s in log["sections"])
    st.markdown(body)


st.title("eaT 제도 이슈 딥리서처 — 데모")
st.caption("공공급식통합플랫폼(eaT) 제도 이슈 코퍼스(33건)를 코디네이터-서브에이전트 구조로 조사해 장문 보고서를 만든다.")

mode = st.sidebar.radio("모드", ["새 질문 실행", "지난 실행 보기"])
corpus = load_corpus()

if mode == "새 질문 실행":
    questions = load_questions()["questions"]
    preset = st.selectbox(
        "질문 세트에서 고르기(선택 안 해도 됨)",
        ["(직접 입력)"] + [f"{q['id']}: {q['question']}" for q in questions],
    )
    default_text = "" if preset == "(직접 입력)" else preset.split(": ", 1)[1]
    question = st.text_area("질문", value=default_text, height=100)

    st.sidebar.markdown("### 장치 on/off (실험용)")
    st.sidebar.caption("체크 = 왼쪽 동작, 체크 해제 = 오른쪽 동작")
    ablation = {
        "isolation": st.sidebar.checkbox("isolation (코디네이터는 목차만 봄 // 내용까지 다 봄)", value=True),
        "link_traversal": st.sidebar.checkbox("link_traversal (링크 따라 추가 탐색 // 준 자료만 읽음)", value=True),
        "peer_awareness": st.sidebar.checkbox("peer_awareness (다른 절 알려주기 // 옆 에이전트가 뭘 쓰는지 모름)", value=True),
        "revision_check": st.sidebar.checkbox("revision_check (점검·재파견 // 재검사 없음)", value=True),
    }

    if st.button("실행", type="primary") and question.strip():
        with st.spinner("코디네이터가 목차를 짜고, 서브에이전트를 파견하는 중..."):
            result = run(question, ablation=ablation, tag="demo")
        render_run(result["log"], corpus)

else:
    runs = load_runs()
    if not runs:
        st.info("아직 output/runs.jsonl이 없습니다. 먼저 '새 질문 실행'을 해보세요.")
    else:
        options = [f"{r['run_id']} ({r.get('tag','-')}) — {r['question'][:40]}..." for r in runs]
        idx = st.selectbox("실행 기록 고르기", range(len(runs)), format_func=lambda i: options[i])
        render_run(runs[idx], corpus)
