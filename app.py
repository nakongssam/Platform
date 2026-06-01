"""
app.py
------
프롬프트 → 파이썬 코드 생성 + 블로그 플랫폼 (Streamlit)

기능
  - 입력  : 로그인 사용자가 프롬프트 입력
  - 처리  : GPT API 가 파이썬 코드 생성
  - 출력  : 코드 제시 + .py 다운로드 + DB 저장
  - 블로그: 생성된 코드를 설명하는 블로그 글을 AI 로 작성·발행
  - 소통  : 블로그에 댓글 + 별점(1~5)
  - 공개  : 블로그는 비로그인도 열람 가능 (단, 댓글/별점은 로그인 필요)

실행
  pip install -r requirements.txt
  streamlit run app.py
"""

import re

import streamlit as st

import database as db

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="프롬프트 → 파이썬 코드 & 블로그", page_icon="🐍", layout="wide")

db.init_db()  # 앱 시작 시 테이블 보장

DEFAULT_MODEL = "gpt-4o-mini"
MODEL_OPTIONS = ["gpt-4o-mini", "gpt-4o"]


# ===========================================================================
# 공통 유틸 / AI 호출
# ===========================================================================
def get_api_key() -> str:
    """st.secrets 우선, 없으면 사이드바에서 입력받은 키 사용."""
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return st.session_state.get("api_key", "")


def has_secret_key() -> bool:
    try:
        return bool(st.secrets["OPENAI_API_KEY"])
    except Exception:
        return False


def extract_code(text: str) -> str:
    """모델 응답에 ```python ... ``` 펜스가 있으면 순수 코드만 추출."""
    fenced = re.findall(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced[0].strip()
    return text.strip()


def _client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def generate_code(prompt_text: str, model: str, api_key: str) -> str:
    """OpenAI API 를 호출해 파이썬 코드를 생성한다."""
    system_prompt = (
        "당신은 숙련된 파이썬 개발자입니다. "
        "사용자의 요구사항을 바탕으로 실행 가능한 파이썬 코드를 작성하세요. "
        "설명 문장 없이 순수한 파이썬 코드만 출력하고, "
        "필요한 곳에는 간단한 한글 주석을 다세요."
    )
    resp = _client(api_key).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0.3,
    )
    return extract_code(resp.choices[0].message.content)


def generate_blog(prompt_text: str, code_text: str, model: str, api_key: str) -> str:
    """생성된 코드를 설명하는 블로그 본문(마크다운)을 생성한다."""
    system_prompt = (
        "당신은 친절한 개발 블로그 작가입니다. "
        "주어진 '요구사항(프롬프트)'과 그로부터 생성된 '파이썬 코드'를 바탕으로, "
        "이 코드가 무엇을 하는지, 어떻게 동작하는지, 어떻게 사용하는지를 "
        "초보자도 이해할 수 있게 설명하는 한국어 블로그 글을 마크다운으로 작성하세요. "
        "제목 줄(# 제목)은 쓰지 말고 본문만 작성하며, 소제목·목록·코드블록을 적절히 사용하세요."
    )
    user_content = (
        f"[요구사항]\n{prompt_text}\n\n"
        f"[파이썬 코드]\n```python\n{code_text}\n```"
    )
    resp = _client(api_key).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()


def safe_filename(text: str, fallback: str = "file") -> str:
    name = re.sub(r"[^\w가-힣]+", "_", text or "").strip("_")
    return name or fallback


# ===========================================================================
# 인증
# ===========================================================================
def auth_view():
    st.subheader("🔑 로그인 / 회원가입")
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


# ===========================================================================
# 코드 생성
# ===========================================================================
def generate_view(user):
    st.subheader("✨ 코드 생성")

    title = st.text_input("제목 (선택)", placeholder="예: CSV 파일 정리 스크립트")
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
                    db.save_prompt_and_code(user["id"], title, prompt_text, code, model)
                    st.session_state.last_code = code
                    st.session_state.last_title = title or "generated"
                    st.success("코드를 생성하고 DB에 저장했습니다.")
                except Exception as e:
                    st.error(f"코드 생성 중 오류가 발생했습니다: {e}")

    if st.session_state.get("last_code"):
        st.markdown("#### 생성된 코드")
        st.code(st.session_state.last_code, language="python")
        st.download_button(
            "📥 .py 파일로 다운로드",
            data=st.session_state.last_code,
            file_name=f"{safe_filename(st.session_state.last_title, 'generated')}.py",
            mime="text/x-python",
            use_container_width=True,
        )


# ===========================================================================
# 내 기록
# ===========================================================================
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

            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "📥 .py 다운로드",
                    data=r["code_text"],
                    file_name=f"{safe_filename(label, 'code')}_{r['prompt_id']}.py",
                    mime="text/x-python",
                    key=f"dl_{r['prompt_id']}",
                    use_container_width=True,
                )
            with col2:
                if st.button("✍️ 이 코드로 블로그 쓰기", key=f"blog_{r['prompt_id']}",
                             use_container_width=True):
                    st.session_state.blog_source = {
                        "prompt_id": r["prompt_id"],
                        "title": label,
                        "prompt_text": r["prompt_text"],
                        "code_text": r["code_text"],
                    }
                    st.session_state.nav_in = "✍️ 블로그 작성"
                    st.rerun()


# ===========================================================================
# 블로그 작성
# ===========================================================================
def blog_write_view(user):
    st.subheader("✍️ 블로그 작성")

    rows = db.get_user_history(user["id"])
    if not rows:
        st.info("먼저 코드를 생성해야 블로그를 쓸 수 있습니다.")
        return

    # '내 기록'에서 넘어온 코드가 있으면 기본 선택
    source = st.session_state.get("blog_source")
    options = {
        f"#{r['prompt_id']} · {r['title'] or r['prompt_text'][:30]}": r for r in rows
    }
    keys = list(options.keys())
    default_idx = 0
    if source:
        for i, r in enumerate(rows):
            if r["prompt_id"] == source["prompt_id"]:
                default_idx = i
                break

    chosen_key = st.selectbox("설명할 코드 선택", keys, index=default_idx)
    chosen = options[chosen_key]

    st.markdown("**대상 코드 미리보기**")
    st.code(chosen["code_text"], language="python")

    model = st.selectbox("모델 선택", MODEL_OPTIONS, index=MODEL_OPTIONS.index(DEFAULT_MODEL),
                         key="blog_model")

    if st.button("🤖 AI로 블로그 초안 생성", use_container_width=True):
        api_key = get_api_key()
        if not api_key:
            st.warning("사이드바에서 OpenAI API 키를 먼저 입력해 주세요.")
        else:
            with st.spinner("블로그 초안을 작성하는 중..."):
                try:
                    body = generate_blog(
                        chosen["prompt_text"], chosen["code_text"], model, api_key
                    )
                    st.session_state.blog_draft = body
                    st.session_state.blog_draft_title = (
                        chosen["title"] or chosen["prompt_text"][:30]
                    )
                except Exception as e:
                    st.error(f"블로그 생성 중 오류가 발생했습니다: {e}")

    # 초안 편집 + 발행
    blog_title = st.text_input(
        "블로그 제목", value=st.session_state.get("blog_draft_title", "")
    )
    blog_content = st.text_area(
        "블로그 본문 (마크다운, 자유롭게 수정 가능)",
        value=st.session_state.get("blog_draft", ""),
        height=320,
    )
    if blog_content:
        with st.expander("미리보기"):
            st.markdown(blog_content)

    if st.button("📝 블로그 발행", type="primary", use_container_width=True):
        if not blog_title.strip() or not blog_content.strip():
            st.warning("제목과 본문을 모두 입력해 주세요.")
        else:
            blog_id = db.create_blog(
                user["id"],
                chosen["prompt_id"],
                blog_title,
                blog_content,
                chosen["code_text"],
            )
            # 발행 후 상태 정리하고 상세 페이지로 이동
            for k in ("blog_draft", "blog_draft_title", "blog_source"):
                st.session_state.pop(k, None)
            st.session_state.view_blog_id = blog_id
            st.session_state.nav_in = "🌐 블로그 보기"
            st.success("블로그를 발행했습니다.")
            st.rerun()


# ===========================================================================
# 블로그 목록 / 상세 (비로그인 열람 가능)
# ===========================================================================
def blog_section(user):
    """user 가 None 이면 비로그인 상태 (열람만 가능)."""
    blog_id = st.session_state.get("view_blog_id")
    if blog_id:
        blog_detail_view(user, blog_id)
    else:
        blog_list_view(user)


def blog_list_view(user):
    st.subheader("🌐 블로그")
    if user is None:
        st.caption("로그인하지 않아도 블로그를 읽을 수 있어요. 댓글·별점은 로그인 후 가능합니다.")

    blogs = db.get_blogs()
    if not blogs:
        st.info("아직 발행된 블로그가 없습니다.")
        return

    for b in blogs:
        avg = b["avg_rating"] or 0.0
        cnt = b["rating_count"] or 0
        rating_str = f"⭐ {avg} ({cnt})" if cnt else "⭐ -"
        with st.container(border=True):
            st.markdown(f"### {b['title']}")
            st.caption(
                f"by {b['author']} · {b['created_at']} · "
                f"{rating_str} · 💬 {b['comment_count']}"
            )
            preview = b["content"].strip().replace("\n", " ")
            st.write(preview[:120] + ("..." if len(preview) > 120 else ""))
            if st.button("읽기", key=f"open_{b['id']}"):
                st.session_state.view_blog_id = b["id"]
                st.rerun()


def blog_detail_view(user, blog_id):
    blog = db.get_blog(blog_id)
    if not blog:
        st.error("존재하지 않는 블로그입니다.")
        st.session_state.pop("view_blog_id", None)
        return

    if st.button("← 목록으로"):
        st.session_state.pop("view_blog_id", None)
        st.rerun()

    avg, cnt = db.get_rating_summary(blog_id)
    st.title(blog["title"])
    st.caption(
        f"by {blog['author']} · {blog['created_at']} · "
        f"⭐ {avg} ({cnt}명 평가)"
    )
    st.markdown(blog["content"])

    if blog["code_text"]:
        with st.expander("원본 코드 보기"):
            st.code(blog["code_text"], language="python")
            st.download_button(
                "📥 .py 다운로드",
                data=blog["code_text"],
                file_name=f"{safe_filename(blog['title'], 'code')}_{blog_id}.py",
                mime="text/x-python",
            )

    st.divider()

    # ----- 별점 -----
    st.markdown("#### ⭐ 별점")
    if user is None:
        st.info("별점을 남기려면 로그인하세요.")
    else:
        current = db.get_user_rating(blog_id, user["id"])
        star_labels = {1: "★", 2: "★★", 3: "★★★", 4: "★★★★", 5: "★★★★★"}
        chosen = st.radio(
            "별점을 선택하세요",
            options=[1, 2, 3, 4, 5],
            format_func=lambda x: star_labels[x],
            index=(current - 1) if current else 4,
            horizontal=True,
            key=f"rate_radio_{blog_id}",
        )
        if st.button("별점 등록", key=f"rate_btn_{blog_id}"):
            db.set_rating(blog_id, user["id"], chosen)
            st.success("별점을 등록했습니다.")
            st.rerun()
        if current:
            st.caption(f"내가 준 별점: {star_labels[current]}")

    st.divider()

    # ----- 댓글 -----
    st.markdown("#### 💬 댓글")
    comments = db.get_comments(blog_id)
    if comments:
        for c in comments:
            st.markdown(f"**{c['author']}** · {c['created_at']}")
            st.write(c["comment_text"])
            st.markdown("---")
    else:
        st.caption("아직 댓글이 없습니다.")

    if user is None:
        st.info("댓글을 남기려면 로그인하세요.")
    else:
        new_comment = st.text_area("댓글 작성", key=f"comment_input_{blog_id}", height=80)
        if st.button("댓글 등록", key=f"comment_btn_{blog_id}"):
            if new_comment.strip():
                db.add_comment(blog_id, user["id"], new_comment)
                st.rerun()
            else:
                st.warning("댓글 내용을 입력해 주세요.")


# ===========================================================================
# 공유 프롬프트 (value unit)
# ===========================================================================
def shared_view(user):
    st.subheader("🔗 공유 프롬프트")
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
                st.session_state.nav_in = "✨ 코드 생성"
                st.rerun()


# ===========================================================================
# 메인 / 라우팅
# ===========================================================================
def sidebar_api_key():
    if not has_secret_key():
        st.session_state.api_key = st.text_input(
            "OpenAI API 키", type="password", value=st.session_state.get("api_key", "")
        )
        st.caption("배포 시 secrets.toml 에 키를 넣으면 이 입력칸이 사라집니다.")


def main():
    user = st.session_state.get("user")  # None 이면 비로그인

    with st.sidebar:
        st.markdown("## 🐍 코드 & 블로그")
        if user:
            st.markdown(f"👤 **{user['username']}** 님")
            if st.button("로그아웃", use_container_width=True):
                for k in ("user", "last_code", "last_title", "reuse_prompt",
                          "blog_draft", "blog_draft_title", "blog_source", "view_blog_id"):
                    st.session_state.pop(k, None)
                st.rerun()
            st.divider()
            sidebar_api_key()
            st.divider()
            nav = st.radio(
                "메뉴",
                ["✨ 코드 생성", "📚 내 기록", "✍️ 블로그 작성", "🌐 블로그 보기", "🔗 공유 프롬프트"],
                key="nav_in",
            )
        else:
            st.caption("로그인하지 않아도 블로그를 읽을 수 있어요.")
            st.divider()
            nav = st.radio(
                "메뉴",
                ["🌐 블로그 보기", "🔑 로그인 / 회원가입"],
                key="nav_out",
            )

    # 라우팅
    if nav == "🔑 로그인 / 회원가입":
        auth_view()
    elif nav == "🌐 블로그 보기":
        blog_section(user)
    elif nav == "✨ 코드 생성":
        generate_view(user)
    elif nav == "📚 내 기록":
        history_view(user)
    elif nav == "✍️ 블로그 작성":
        blog_write_view(user)
    elif nav == "🔗 공유 프롬프트":
        shared_view(user)


if __name__ == "__main__":
    main()
