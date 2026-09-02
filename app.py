import streamlit as st
import pandas as pd
from datetime import datetime
import os

st.set_page_config(page_title="Stitch 용산점 활동비 정산", layout="wide")

CSV_FILE = "expense_records.csv"

# 1. 데이터 로드 / 초기화 (12명 기본 세팅)
DEFAULT_NAMES = ["미경", "상희", "선아", "세라", "신영", "아리", "예지", "은서", "은석", "희순", "회원11", "회원12"]
PERIODS = ["7-8월", "5-6월", "3-4월", "1-2월"]

def load_data():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
    else:
        rows = []
        for p in PERIODS:
            for name in DEFAULT_NAMES:
                rows.append({
                    "기간": p,
                    "이름": name,
                    "실지출": 0,
                    "청구액": 30000,
                    "사비": 0,
                    "정산상태": "청구 전",
                    "확인": False,
                    "비고": "",
                    "수정일시": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
        df = pd.DataFrame(rows)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")

    # CSV 로드 시 발생하는 타입 불일치 방지
    df["실지출"] = pd.to_numeric(df["실지출"], errors="coerce").fillna(0).astype(int)
    df["청구액"] = pd.to_numeric(df["청구액"], errors="coerce").fillna(30000).astype(int)
    df["사비"] = pd.to_numeric(df["사비"], errors="coerce").fillna(0).astype(int)
    df["확인"] = df["확인"].astype(bool)
    df["비고"] = df["비고"].fillna("").astype(str)
    df["정산상태"] = df["정산상태"].fillna("청구 전").astype(str)
    df["수정일시"] = df["수정일시"].fillna("").astype(str)

    return df
    
df_all = load_data()

# 2. 좌측 사이드바
with st.sidebar:
    st.header("🧶 Stitch 용산점")
    menu = st.radio("메뉴", ["월별 활동비 입력", "월별 요약 대시보드"])
    st.divider()
    selected_period = st.selectbox("정산 기간 선택", PERIODS)

# 3. 본문 레이아웃 (중앙 7 : 우측 요약 3)
if menu == "월별 활동비 입력":
    col_main, col_summary = st.columns([7, 3])

    # 선택된 기간 데이터 필터링
    mask = df_all["기간"] == selected_period
    current_df = df_all[mask].copy()

    with col_main:
        st.subheader(f"📅 {selected_period} 활동비 입력")
        st.caption("표에서 금액과 상태를 직접 수정하면 우측 요약에 즉시 반영됩니다.")

        edited_df = st.data_editor(
            current_df.drop(columns=["기간"]),
            key=f"editor_{selected_period}",
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "이름": st.column_config.TextColumn("이름", required=True),
                "실지출": st.column_config.NumberColumn("실지출 (원)", format="%d원", min_value=0),
                "청구액": st.column_config.NumberColumn("청구액 (원)", format="%d원", min_value=0),
                "사비": st.column_config.NumberColumn("사비 (원)", format="%d원", disabled=True),
                "정산상태": st.column_config.SelectboxColumn("정산 상태", options=["청구 전", "진행 중", "양도", "완료"]),
                "확인": st.column_config.CheckboxColumn("확인"),
                "비고": st.column_config.TextColumn("비고"),
                "수정일시": st.column_config.TextColumn("최종 편집 일시", disabled=True)
            }
        )

        # 초과 사비 자동 계산 (실지출 > 청구액일 경우 초과액)
        edited_df["사비"] = (edited_df["실지출"] - edited_df["청구액"]).apply(lambda x: max(0, x))

        if st.button("💾 변경사항 저장하기", type="primary"):
            edited_df["기간"] = selected_period
            edited_df["수정일시"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            df_all = pd.concat([df_all[~mask], edited_df], ignore_index=True)
            df_all.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
            st.success("성공적으로 저장되었습니다!")
            st.rerun()

    # 우측 실시간 요약 패널
    with col_summary:
        st.subheader("📊 집계 요약")
        
        member_cnt = len(edited_df)
        total_limit = int(edited_df["청구액"].sum())
        total_spent = int(edited_df["실지출"].sum())
        rem_balance = max(0, total_limit - total_spent)
        total_over = max(0, total_spent - total_limit)

        st.metric("총 인원", f"{member_cnt} 명")
        st.metric("총 한도", f"{total_limit:,} 원")
        st.metric("총 지출", f"{total_spent:,} 원", delta=f"{total_spent - total_limit:,} 원", delta_color="inverse")
        st.metric("남은 금액", f"{rem_balance:,} 원")
        st.metric("총 초과액", f"{total_over:,} 원")

        st.divider()
        st.write("**정산 진행 현황**")
        status_counts = edited_df["정산상태"].value_counts()
        for s in ["청구 전", "진행 중", "완료", "양도"]:
            st.write(f"- {s}: **{status_counts.get(s, 0)}건**")

elif menu == "월별 요약 대시보드":
    st.subheader("📑 전체 기간 정산 요약")
    summary_rows = []
    for p in PERIODS:
        p_df = df_all[df_all["기간"] == p]
        cnt = len(p_df)
        lim = int(p_df["청구액"].sum())
        sp = int(p_df["실지출"].sum())
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