import streamlit as st
import pandas as pd
from datetime import datetime
import re
from supabase import create_client, Client

st.set_page_config(page_title="Stitch 용산점 활동비 정산", layout="wide")

# Supabase 클라이언트 초기화
def init_supabase() -> Client:
    raw_url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
    raw_key = str(st.secrets["SUPABASE_KEY"]).strip()
    return create_client(raw_url, raw_key)

supabase = init_supabase()

# 기본 기간 목록
DEFAULT_PERIODS = ["9-10월", "7-8월", "5-6월", "3-4월", "1-2월"]

# 다음 2개월 기간 자동 계산 함수 (예: "9-10월" -> "11-12월", "11-12월" -> "1-2월")
def get_next_period_name(current_period: str) -> str:
    nums = re.findall(r'\d+', current_period)
    if len(nums) >= 2:
        end_m = int(nums[1])
        next_start = 1 if end_m == 12 else end_m + 1
        next_end = 2 if end_m == 12 else end_m + 2
        return f"{next_start}-{next_end}월"
    return f"{current_period}_다음"

# 영수증 스토리지 업로드 함수
def upload_receipt(uploaded_file, period, member_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_extension = uploaded_file.name.split(".")[-1]
    file_path = f"{period}/{member_name}_{timestamp}.{file_extension}"

    file_bytes = uploaded_file.read()
    supabase.storage.from_("receipts").upload(
        path=file_path,
        file=file_bytes,
        file_options={"content-type": uploaded_file.type}
    )
    return supabase.storage.from_("receipts").get_public_url(file_path)

# 데이터 로드
def load_data():
    try:
        res = supabase.table("settlements").select("*").execute()
        data = res.data
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        col_mapping = {
            "id": "id",
            "period": "기간",
            "name": "이름",
            "actual_spent": "실지출",
            "claim_amount": "청구액",
            "private_expense": "사비",
            "receipt_url": "영수증",
            "status": "정산상태",
            "is_checked": "확인",
            "note": "비고",
            "updated_at": "수정일시"
        }
        df = df.rename(columns=col_mapping)

        df["실지출"] = pd.to_numeric(df["실지출"], errors="coerce").fillna(0).astype(int)
        df["청구액"] = pd.to_numeric(df["청구액"], errors="coerce").fillna(30000).astype(int)
        df["사비"] = pd.to_numeric(df["사비"], errors="coerce").fillna(0).astype(int)
        df["확인"] = df["확인"].fillna(False).astype(bool)
        df["영수증"] = df["영수증"].fillna("").astype(str)
        df["비고"] = df["비고"].fillna("").astype(str)
        df["정산상태"] = df["정산상태"].fillna("청구 전").astype(str)
        df["수정일시"] = df["수정일시"].fillna("").astype(str)

        return df
    except Exception as e:
        st.error(f"데이터베이스 연결 오류: {e}")
        return pd.DataFrame()

df_all = load_data()

# DB에 존재하는 모든 기간과 기본 기간을 합쳐 기간 목록 동적 생성
db_periods = df_all["기간"].dropna().unique().tolist() if not df_all.empty and "기간" in df_all.columns else []
all_periods = []
for p in DEFAULT_PERIODS + db_periods:
    if p not in all_periods:
        all_periods.append(p)

# 사이드바
with st.sidebar:
    st.header("🧶 Stitch 용산점")
    menu = st.radio("메뉴", ["월별 활동비 입력", "월별 요약 대시보드"])
    st.divider()

    # 세션 상태로 선택 기간 유지 지원
    if "selected_period" not in st.session_state or st.session_state["selected_period"] not in all_periods:
        st.session_state["selected_period"] = all_periods[0]

    selected_period = st.selectbox(
        "정산 기간 선택",
        all_periods,
        index=all_periods.index(st.session_state["selected_period"])
    )
    st.session_state["selected_period"] = selected_period

# 메인 화면
if menu == "월별 활동비 입력":
    col_main, col_summary = st.columns([7, 3])

    mask = (df_all["기간"] == selected_period) if not df_all.empty and "기간" in df_all.columns else pd.Series(dtype=bool)
    current_df = df_all[mask].copy() if not df_all.empty and "기간" in df_all.columns else pd.DataFrame()

    is_auto_filled = False

    # 해당 기간에 데이터가 없을 때: 최근 기간 회원 명단 자동 가져오기
    if current_df.empty:
        prev_names = []
        curr_idx = all_periods.index(selected_period)
        for p in all_periods[curr_idx + 1:]:
            prev_df = df_all[df_all["기간"] == p] if not df_all.empty and "기간" in df_all.columns else pd.DataFrame()
            if not prev_df.empty and "이름" in prev_df.columns:
                prev_names = [n for n in prev_df["이름"].dropna().unique() if str(n).strip()]
                if prev_names:
                    break

        if prev_names:
            current_df = pd.DataFrame({
                "이름": prev_names,
                "실지출": 0,
                "청구액": 30000,
                "사비": 0,
                "영수증": "",
                "정산상태": "청구 전",
                "확인": False,
                "비고": "",
                "수정일시": ""
            })
            is_auto_filled = True

    current_names = [n for n in current_df["이름"].dropna().unique() if str(n).strip()] if not current_df.empty and "이름" in current_df.columns else []

    with col_main:
        st.subheader(f"📅 {selected_period} 활동비 내역")

        if is_auto_filled:
            st.info(f"💡 이전 기간의 회원 목록({len(current_names)}명)을 기본으로 불러왔습니다. 수정 후 아래 [저장하기]를 누르면 DB에 등록됩니다.")

        # 영수증 업로드 창
        with st.expander("🧾 영수증 사진 업로드하기 (클릭)", expanded=False):
            if current_names:
                up_col1, up_col2 = st.columns([1, 2])
                with up_col1:
                    target_user = st.selectbox("이름 선택", current_names, key="receipt_user")
                with up_col2:
                    uploaded_file = st.file_uploader("영수증 파일 (JPG, PNG, PDF)", type=["png", "jpg", "jpeg", "pdf"])

                if st.button("영수증 등록", key="btn_upload"):
                    if uploaded_file is not None:
                        with st.spinner("스토리지에 저장 중..."):
                            link = upload_receipt(uploaded_file, selected_period, target_user)
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                            
                            supabase.table("settlements").update({
                                "receipt_url": link,
                                "updated_at": now_str
                            }).match({"period": selected_period, "name": target_user}).execute()

                            st.success(f"[{target_user}]님의 영수증이 등록되었습니다!")
                            st.rerun()
                    else:
                        st.warning("파일을 먼저 선택해 주세요.")
            else:
                st.info("먼저 표에 회원을 입력하고 저장해 주세요.")

        st.caption("💡 표 아래 '+' 버튼으로 인원을 추가하거나 이름을 수정할 수 있습니다.")

        # 테이블 표시용 데이터 준비
        display_df = current_df.drop(columns=["id", "기간"], errors="ignore") if not current_df.empty else pd.DataFrame(columns=[
            "이름", "실지출", "청구액", "사비", "영수증", "정산상태", "확인", "비고", "수정일시"
        ])

        edited_df = st.data_editor(
            display_df,
            key=f"editor_{selected_period}",
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "이름": st.column_config.TextColumn("이름", required=True),
                "실지출": st.column_config.NumberColumn("실지출 (원)", format="%d원", min_value=0, default=0),
                "청구액": st.column_config.NumberColumn("청구액 (원)", format="%d원", min_value=0, default=30000),
                "사비": st.column_config.NumberColumn("사비 (원)", format="%d원", disabled=True),
                "영수증": st.column_config.LinkColumn("영수증 링크", display_text="영수증 열기"),
                "정산상태": st.column_config.SelectboxColumn("정산 상태", options=["청구 전", "진행 중", "양도", "완료"], default="청구 전"),
                "확인": st.column_config.CheckboxColumn("확인", default=False),
                "비고": st.column_config.TextColumn("비고"),
                "수정일시": st.column_config.TextColumn("최종 편집 일시", disabled=True)
            }
        )

        # 저장하기 & 다음 기간 생성하기 버튼 나란히 배치
        # 왼쪽: [💾 저장하기] / 오른쪽 끝: [➕ 다음 달 생성하기]
        btn_col_left, _, btn_col_right = st.columns([3, 4, 3])

        with btn_col_left:
            if st.button("💾 데이터베이스에 저장하기", type="primary", use_container_width=True):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                supabase.table("settlements").delete().match({"period": selected_period}).execute()

                insert_rows = []
                for _, r in edited_df.iterrows():
                    name_val = str(r["이름"]).strip()
                    if not name_val or name_val == "nan":
                        continue
                    actual = int(r["실지출"]) if pd.notnull(r["실지출"]) else 0
                    claim = int(r["청구액"]) if pd.notnull(r["청구액"]) else 30000
                    priv = max(0, actual - claim)
                    
                    insert_rows.append({
                        "period": selected_period,
                        "name": name_val,
                        "actual_spent": actual,
                        "claim_amount": claim,
                        "private_expense": priv,
                        "receipt_url": str(r.get("영수증", "")) if pd.notnull(r.get("영수증")) else "",
                        "status": str(r.get("정산상태", "청구 전")),
                        "is_checked": bool(r.get("확인", False)),
                        "note": str(r.get("비고", "")) if pd.notnull(r.get("비고")) else "",
                        "updated_at": now_str
                    })

                if insert_rows:
                    supabase.table("settlements").insert(insert_rows).execute()

                st.success(f"[{selected_period}] 내역이 저장되었습니다!")
                st.rerun()

        with btn_col_right:
            next_p_name = get_next_period_name(selected_period)
            if st.button(f"➕ 다음 달({next_p_name}) 생성", use_container_width=True):
                # 1. 현재 테이블에 있는 회원 목록 추출
                active_names = [str(r["이름"]).strip() for _, r in edited_df.iterrows() if str(r["이름"]).strip() and str(r["이름"]).strip() != "nan"]
                if not active_names:
                    active_names = current_names

                if not active_names:
                    st.warning("현재 기간에 입력된 회원이 없습니다. 먼저 회원을 추가해 주세요.")
                else:
                    # 2. 이미 존재하는지 확인
                    existing = supabase.table("settlements").select("id").match({"period": next_p_name}).execute()
                    if existing.data:
                        st.info(f"이미 [{next_p_name}] 데이터가 존재합니다. 해당 기간으로 이동합니다.")
                    else:
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        new_rows = [{
                            "period": next_p_name,
                            "name": name,
                            "actual_spent": 0,
                            "claim_amount": 30000,
                            "private_expense": 0,
                            "receipt_url": "",
                            "status": "청구 전",
                            "is_checked": False,
                            "note": "",
                            "updated_at": now_str
                        } for name in active_names]

                        supabase.table("settlements").insert(new_rows).execute()
                        st.success(f"[{next_p_name}] 기간이 {len(active_names)}명으로 새로 생성되었습니다!")

                    # 새로 만든 기간으로 화면 전환
                    st.session_state["selected_period"] = next_p_name
                    st.rerun()

    # 우측 요약 패널
    with col_summary:
        st.subheader("📊 집계 요약")
        valid_rows = edited_df[edited_df["이름"].astype(str).str.strip() != ""] if not edited_df.empty else pd.DataFrame()
        member_cnt = len(valid_rows)
        total_limit = int(pd.to_numeric(valid_rows["청구액"], errors="coerce").sum()) if not valid_rows.empty else 0
        total_spent = int(pd.to_numeric(valid_rows["실지출"], errors="coerce").sum()) if not valid_rows.empty else 0
        rem_balance = max(0, total_limit - total_spent)
        total_over = max(0, total_spent - total_limit)

        st.metric("총 인원", f"{member_cnt} 명")
        st.metric("총 한도", f"{total_limit:,} 원")
        st.metric("총 지출", f"{total_spent:,} 원", delta=f"{total_spent - total_limit:,} 원", delta_color="inverse")
        st.metric("남은 금액", f"{rem_balance:,} 원")
        st.metric("총 초과액", f"{total_over:,} 원")

        st.divider()
        st.write("**정산 진행 현황**")
        if not valid_rows.empty and "정산상태" in valid_rows.columns:
            status_counts = valid_rows["정산상태"].value_counts()
            for s in ["청구 전", "진행 중", "완료", "양도"]:
                st.write(f"- {s}: **{status_counts.get(s, 0)}건**")

elif menu == "월별 요약 대시보드":
    st.subheader("📑 전체 기간 정산 요약")
    summary_rows = []
    for p in all_periods:
        p_df = df_all[df_all["기간"] == p] if not df_all.empty and "기간" in df_all.columns else pd.DataFrame()
        cnt = len(p_df)
        lim = int(p_df["청구액"].sum()) if cnt > 0 else 0
        sp = int(p_df["실지출"].sum()) if cnt > 0 else 0
        rem = max(0, lim - sp)
        over = max(0, sp - lim)
        summary_rows.append({
            "이름": p,
            "회원수": cnt,
            "총 한도": f"{lim:,}원",
            "총 지출": f"{sp:,}원",
            "총 초과": f"{over:,}원",
            "남은 금액": f"{rem:,}원"
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)