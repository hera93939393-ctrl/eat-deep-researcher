# eaT 제도 이슈 딥리서처

공공급식통합플랫폼(eaT) 제도 이슈(연혁·불공정행위·위생재계약·정책대응·인프라·국감전망·자체심사기준) 코퍼스 33건을
코디네이터-서브에이전트 구조로 분업 조사해 장문 보고서를 만든다.

자세한 설계 근거·실험 기록·회고는 → [REPORT.md](./REPORT.md) 참고.

## 빠른 실행

```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env

python graph.py "질문"                      # 단발 실행(기본, 모든 장치 ON)
python ablation.py "질문" peer_awareness     # 기본 vs 장치 하나 끈 실행 비교
python ablation_repro.py 3                   # 같은 스위치를 N회 반복해 효과가 재현되는지 확인
python baseline.py "질문" [budget_chars]     # 혼자 하는 대조군(같은 자료·모델·예산)
python metrics.py output/runs.jsonl          # 정답표 없는 지표(경보/신호) 계산
streamlit run app.py                         # 데모 화면
```

## 구조

```
data/
  corpus.json        코퍼스 33건 (docs + links)
  questions.json      질문 10건과 "왜 나눌 만한가"
config.json           절수·예산·바퀴상한·역할명단(도메인에 묶인 값)
graph.py              기획 -> 배치(서브에이전트 동시 파견) -> 점검 -> 종합. 격리를 글자수로 계측
metrics.py            정답표 없는 지표 (ALARM 3종 + SIGNAL 6종)
ablation.py           장치 하나 끈 실행
ablation_repro.py     같은 스위치를 반복 실행해 효과의 재현성 확인
baseline.py           혼자 하는 대조군(같은 자료·모델·예산)
app.py                Streamlit 데모 — 절마다 누가 무엇을 읽고 썼는지 보여준다
output/
  runs.jsonl          매 실행 로그(격리 증명 수치 포함)
  ablation.json, ablation_repro.json
  reports/            생성된 보고서(.md)
```
