"""
app.py
------
프롬프트 → 파이썬 코드 생성 플랫폼 (Streamlit)

흐름
  입력  : 로그인한 사용자가 프롬프트 아이디어를 입력
  처리  : GPT API 가 프롬프트를 받아 파이썬 코드를 생성
  출력  : 코드를 화면에 제시 + .py 파일 다운로드 + DB 저장

핵심 개념
  사용자가 입력한 '프롬프트' 가 공유가치(value unit) 이며,
  '공유 프롬프트' 탭을 통해 다른 사용자와 공유·재사용된다.

실행
  pip install -r requirements.txt
  streamlit run app.py
"""

import re
from datetime import datetime

import streamlit as st

import database as db

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="프롬프트 → 파이썬 코드 생성기", page_icon="🐍", layout="wide")

db.init_db()  # 앱 시작 시 테이블 보장

DEFAULT_MODEL = "gpt-4o-mini"
MODEL_OPTIONS = ["gpt-4o-mini", "gpt-4o"]


# ---------------------------------------------------------------------------
# API 키 / 코드 생성
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    """st.secrets 우선, 없으면 사이드바에서 입력받은 키 사용."""
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return st.session_state.get("api_key", "")


def extract_code(text: str) -> str:
    """모델 응답에 ```python ... ``` 펜스가 있으면 순수 코드만 추출."""
    fenced = re.findall(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced[0].strip()
    return text.strip()


def generate_code(prompt_text: str, model: str, api_key: str) -> str:
    """OpenAI API 를 호출해 파이썬 코드를 생성한다."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    system_prompt = (
        "당신은 숙련된 파이썬 개발자입니다. "
        "사용자의 요구사항을 바탕으로 실행 가능한 파이썬 코드를 작성하세요. "
        "설명 문장 없이 순수한 파이썬 코드만 출력하고, "
        "필요한 곳에는 간단한 한글 주석을 다세요."
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0.3,
    )
    return extract_code(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# 인증 화면
# ---------------------------------------------------------------------------
def auth_view():
    st.title("🐍 프롬프트 → 파이썬 코드 생성 플랫폼")
    st.caption("아이디어를 프롬프트로 입력하면 파이썬 코드로 만들어 드립니다.")

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        username = st.text_input("아이디", key="login_user")
        password = st.text_input("비밀번호", type="password", key="login_pw")
        if st.button("로그인", key="login_btn", use_container_width=True):
            user = db.verify_user(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

    with tab_signup:
        new_user = st.text_input("아이디", key="signup_user")
        new_pw = st.text_input("비밀번호", type="password", key="signup_pw")
        new_pw2 = st.text_input("비밀번호 확인", type="password", key="signup_pw2")
        if st.button("회원가입", key="signup_btn", use_container_width=True):
            if new_pw != new_pw2:
                st.error("비밀번호가 일치하지 않습니다.")
            else:
                ok, msg = db.create_user(new_user, new_pw)
                (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------------------
# 코드 생성 화면
# ---------------------------------------------------------------------------
def generate_view(user):
    st.subheader("✨ 코드 생성")

    title = st.text_input("제목 (선택)", placeholder="예: CSV 파일 정리 스크립트")
    # 공유 프롬프트에서 가져온 값이 있으면 기본값으로 채운다
    default_prompt = st.session_state.pop("reuse_prompt", "")
    prompt_text = st.text_area(
        "프롬프트를 입력하세요",
        value=default_prompt,
        height=160,
        placeholder="예) 폴더 안의 모든 .csv 파일을 읽어 하나로 합치고, "
        "결측치를 0으로 채운 뒤 result.csv 로 저장하는 코드를 만들어 줘.",
    )
    model = st.selectbox("모델 선택", MODEL_OPTIONS, index=MODEL_OPTIONS.index(DEFAULT_MODEL))

    if st.button("코드 생성하기", type="primary", use_container_width=True):
        api_key = get_api_key()
        if not api_key:
            st.warning("사이드바에서 OpenAI API 키를 먼저 입력해 주세요.")
        elif not prompt_text.strip():
            st.warning("프롬프트를 입력해 주세요.")
        else:
            with st.spinner("코드를 생성하는 중..."):
                try:
                    code = generate_code(prompt_text, model, api_key)
                    # 출력 단계: DB 에 자동 저장
                    db.save_prompt_and_code(
                        user["id"], title, prompt_text, code, model
                    )
                    st.session_state.last_code = code
                    st.session_state.last_title = title or "generated"
                    st.success("코드를 생성하고 DB에 저장했습니다.")
                except Exception as e:
                    st.error(f"코드 생성 중 오류가 발생했습니다: {e}")

    # 마지막 생성 결과 표시 + 다운로드
    if st.session_state.get("last_code"):
        st.markdown("#### 생성된 코드")
        st.code(st.session_state.last_code, language="python")

        fname = re.sub(r"[^\w가-힣]+", "_", st.session_state.last_title).strip("_")
        st.download_button(
            "📥 .py 파일로 다운로드",
            data=st.session_state.last_code,
            file_name=f"{fname or 'generated'}.py",
            mime="text/x-python",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# 내 기록 화면
# ---------------------------------------------------------------------------
def history_view(user):
    st.subheader("📚 내 기록")
    rows = db.get_user_history(user["id"])
    if not rows:
        st.info("아직 생성한 코드가 없습니다.")
        return

    for r in rows:
        label = r["title"] or r["prompt_text"][:30]
        with st.expander(f"#{r['prompt_id']} · {label}  ({r['created_at']})"):
            st.markdown("**프롬프트**")
            st.write(r["prompt_text"])
            st.markdown(f"**생성 코드** · 모델: `{r['model']}`")
            st.code(r["code_text"], language="python")
            fname = re.sub(r"[^\w가-힣]+", "_", label).strip("_")
            st.download_button(
                "📥 .py 다운로드",
                data=r["code_text"],
                file_name=f"{fname or 'code'}_{r['prompt_id']}.py",
                mime="text/x-python",
                key=f"dl_{r['prompt_id']}",
            )


# ---------------------------------------------------------------------------
# 공유 프롬프트 화면 (value unit)
# ---------------------------------------------------------------------------
def shared_view(user):
    st.subheader("🌐 공유 프롬프트")
    st.caption("모든 사용자가 입력한 프롬프트입니다. 마음에 드는 프롬프트를 가져와 다시 생성할 수 있어요.")

    rows = db.get_shared_prompts()
    if not rows:
        st.info("아직 공유된 프롬프트가 없습니다.")
        return

    for r in rows:
        label = r["title"] or r["prompt_text"][:30]
        with st.expander(f"#{r['prompt_id']} · {label}  ·  by {r['author']}"):
            st.write(r["prompt_text"])
            if st.button("이 프롬프트로 생성하기", key=f"reuse_{r['prompt_id']}"):
                st.session_state.reuse_prompt = r["prompt_text"]
                st.session_state.nav = "✨ 코드 생성"
                st.rerun()


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    if "user" not in st.session_state:
        auth_view()
        return

    user = st.session_state.user

    # 사이드바
    with st.sidebar:
        st.markdown(f"👤 **{user['username']}** 님")
        if st.button("로그아웃", use_container_width=True):
            for k in ("user", "last_code", "last_title", "reuse_prompt"):
                st.session_state.pop(k, None)
            st.rerun()

        st.divider()
        if "OPENAI_API_KEY" not in st.secrets:
            st.session_state.api_key = st.text_input(
                "OpenAI API 키", type="password", value=st.session_state.get("api_key", "")
            )
            st.caption("배포 시에는 secrets.toml 에 키를 넣으면 이 입력칸이 사라집니다.")

        st.divider()
        nav = st.radio(
            "메뉴",
            ["✨ 코드 생성", "📚 내 기록", "🌐 공유 프롬프트"],
            key="nav",
        )

    # 메뉴 라우팅
    if nav == "✨ 코드 생성":
        generate_view(user)
    elif nav == "📚 내 기록":
        history_view(user)
    else:
        shared_view(user)


if __name__ == "__main__":
    main()
