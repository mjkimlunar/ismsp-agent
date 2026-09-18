# 공개 배포 (선택)

과제 요구사항은 "공개 배포는 선택입니다. 하더라도 API 키를 저장소에 올리지 마세요" 다.
아래 절차는 **키를 저장소에 올리지 않고** 배포하는 방법이며, 코드는 준비만 해 두고
실제 배포는 하지 않았다.

## 먼저 알아야 할 것 — 크레딧이 노출된다

공개 URL 을 열면 **누구나 내 OpenAI 크레딧으로 질문한다.**
문의 한 건이 약 1.7원이므로 1,000건이면 1,700원이고, 봇이 긁으면 그 이상이다.
그래서 이 저장소에는 두 개의 잠금을 미리 넣어 두었다. **둘 다 시크릿을 설정했을 때만
켜지고, 설정하지 않으면 아무 일도 하지 않는다** — 로컬에서 쓰던 방식이 바뀌지 않게 한 것이다.

| 시크릿 | 없을 때 | 넣었을 때 |
|---|---|---|
| `APP_PASSWORD` | 잠금 없음 | 비밀번호를 맞춰야 화면이 열린다 |
| `APP_MAX_TURNS` | 제한 없음 | 한 세션에서 그 횟수까지만 물어볼 수 있다 |

`app.py` 의 `secret()` 이 **환경변수 → `st.secrets`** 순서로 찾으므로,
로컬에서는 `.env` 가 그대로 쓰이고 배포에서는 시크릿이 쓰인다.

## Streamlit Community Cloud

1. https://share.streamlit.io 에서 GitHub 계정으로 로그인
2. **New app** → 저장소 `mjkimlunar/ismsp-agent` · 브랜치 `master` · 메인 파일 `app.py`
3. **Advanced settings → Secrets** 에 아래를 붙여 넣는다 (TOML 형식)

```toml
OPENAI_API_KEY = "sk-..."
ISMSP_MODEL = "gpt-4o-mini"

# 공개 URL 로 열 때 반드시 같이 넣는다
APP_PASSWORD = "아무-어려운-문자열"
APP_MAX_TURNS = "20"
```

4. **Deploy** — 첫 빌드에 2~3분 걸린다

시크릿은 Streamlit 쪽 설정에만 저장되고 저장소에는 올라가지 않는다.
`.streamlit/secrets.toml` 은 `.gitignore` 에 이미 들어 있다.

## 배포 뒤에 확인할 것

- 비밀번호 화면이 먼저 나오는지
- `APP_MAX_TURNS` 만큼 물어본 뒤 입력창이 잠기는지
- OpenAI 사용량 대시보드를 며칠 지켜보기 — 예상보다 늘면 비밀번호를 바꾸거나 앱을 내린다

## 왜 지금 배포하지 않았나

화면공유로 로컬 실행을 보여 줬고 캡처도 리포트에 들어가 있어서,
**공개 URL 이 주는 것이 크레딧 위험만큼 크지 않다**고 판단했다.
포트폴리오나 발표에 링크가 필요해지면 위 절차로 15분 안에 열 수 있다.

## 로컬 실행 (지금 쓰는 방식)

```bash
cp .env.example .env        # OPENAI_API_KEY 채우기
streamlit run app.py        # http://localhost:8501
```
