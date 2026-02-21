import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# 1. 페이지 설정
st.set_page_config(layout="wide", page_title="My Stock Scanner")
st.title("📊 통합 퀀트 수급 스캐너")

# 2. 사이드바 설정
with st.sidebar:
    st.header("📅 기간 및 범위")
    date_options = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(15)]
    start_date = st.selectbox("시작일", date_options, index=2)
    end_date = st.selectbox("종료일", date_options, index=0)
    
    count_options = list(range(100, 2001, 100))
    target_count = st.selectbox("🎯 분석 종목 수 (시장별)", count_options, index=count_options.index(200))
    
    st.divider()
    st.header("🔍 필터 조건")
    
    c_opm = st.checkbox("최소 OPM (%)", value=True)
    opm_val = st.selectbox("OPM 값", list(range(0, 51, 5)), index=2, label_visibility="collapsed")
    
    c_per = st.checkbox("최대 PER (배)", value=True)
    per_val = st.selectbox("PER 값", list(range(5, 201, 5)), index=9, label_visibility="collapsed")
    
    c_pbr = st.checkbox("최대 PBR (배)", value=True)
    pbr_val = st.selectbox("PBR 값", list(range(5, 101, 5)), index=3, label_visibility="collapsed")
    
    c_amt = st.checkbox("누적 거래액 (억)", value=True)
    amt_val = st.selectbox("거래액 값", list(range(500, 10001, 500)), index=0, label_visibility="collapsed")
    
    c_str = st.checkbox("시총대비 매수비율 (%)", value=True)
    s_opts = [round(i * 0.01, 2) for i in range(0, 101)]
    str_val = st.selectbox("강도 값", s_opts, index=1, label_visibility="collapsed")

    c_trs = st.checkbox("자사주비중 (%)", value=False)
    trs_val = st.selectbox("자사주 값", list(range(0, 31, 5)), index=0, label_visibility="collapsed")

    st.divider()
    logic_gate = st.radio("🔄 조건 결합", ("모든 체크 조건 만족 (AND)", "하나라도 만족 (OR)"))

def to_numeric(value):
    try:
        if value is None or str(value).strip() in ["", "N/A", "-", "NaN"]: return 0.0
        return float(str(value).replace(',', '').replace('%', '').replace('+', '').strip())
    except: return 0.0

# 3. 데이터 분석 로직
if st.button("🚀 분석 시작"):
    with st.spinner('데이터를 수집하고 있습니다...'):
        df_krx = fdr.StockListing('KRX')
        df_krx = df_krx.rename(columns={'Code': 'Symbol', 'Marcap': '시가총액'})
        
        combined = pd.concat([
            df_krx[df_krx['Market'] == 'KOSPI'].sort_values('시가총액', ascending=False).head(target_count),
            df_krx[df_krx['Market'] == 'KOSDAQ'].sort_values('시가총액', ascending=False).head(target_count)
        ])
        
        results = []
        progress_bar = st.progress(0)
        headers = {'User-Agent': 'Mozilla/5.0'}

        for i, row in enumerate(combined.itertuples()):
            try:
                df_hist = fdr.DataReader(row.Symbol, start_date, end_date)
                if len(df_hist) < 1: continue
                
                # 수급 데이터 (안정적인 통신을 위해 타임아웃 3초 설정)
                res_f = requests.get(f"https://finance.naver.com/item/frgn.naver?code={row.Symbol}", headers=headers, timeout=3)
                soup_f = BeautifulSoup(res_f.text, 'html.parser')
                rows_f = soup_f.find_all('tr', onmouseover="mouseOver(this)")
                p_i, p_f = 0.0, 0.0
                for r_idx in range(min(len(rows_f), len(df_hist))):
                    tds = rows_f[r_idx].find_all('td')
                    curr_p = to_numeric(tds[1].text)
                    p_i += (to_numeric(tds[5].text) * curr_p) / 100000000
                    p_f += (to_numeric(tds[6].text) * curr_p) / 100000000

                # 재무 데이터 크롤링 및 키 에러 방지 처리
                res_m = requests.get(f"https://finance.naver.com/item/main.naver?code={row.Symbol}", headers=headers, timeout=3)
                soup_m = BeautifulSoup(res_m.text, 'html.parser')
                f_table = soup_m.select_one('div.section.cop_analysis')
                opm, per, pbr = 0.0, 0.0, 0.0
                if f_table:
                    # '영업이익률' 텍스트가 포함된 행을 정확히 찾아 데이터 추출
                    opm_row = f_table.select('tr:contains("영업이익률") td')
                    if opm_row: opm = to_numeric(opm_row[-4].text)
                    per_row = f_table.select('tr:contains("PER") td')
                    if per_row: per = to_numeric(per_row[-4].text)
                    pbr_row = f_table.select('tr:contains("PBR") td')
                    if pbr_row: pbr = to_numeric(pbr_row[-4].text)

                treasury = 0.0
                if c_trs:
                    try:
                        res_s = requests.get(f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={row.Symbol}", headers=headers, timeout=3)
                        soup_s = BeautifulSoup(res_s.text, 'html.parser')
                        t_text = soup_s.find('th', string=lambda t: t and '자기주식' in t)
                        if t_text: treasury = to_numeric(t_text.find_next_sibling('td').text)
                    except: pass

                m_cap_bn = to_numeric(row.시가총액) / 100000000
                strength = ((p_i + p_f) / m_cap_bn) * 100

                results.append({
                    '시장': row.Market, '종목명': row.Name, '현재가': df_hist['Close'].iloc[-1],
                    '상승률': round(((df_hist['Close'].iloc[-1] / df_hist['Open'].iloc[0]) - 1) * 100, 1),
                    '거래액': round((df_hist['Close'] * df_hist['Volume']).sum() / 100000000, 1),
                    '시총(억)': round(m_cap_bn, 1), 'OPM': round(opm, 1), 'PER': round(per, 1), 
                    'PBR': round(pbr, 1), '매수비율': round(strength, 1), '자사주': round(treasury, 1)
                })
            except: continue
            finally: progress_bar.progress((i + 1) / len(combined))

        df_res = pd.DataFrame(results)
        
        # 필터 로직
        filters = []
        if c_opm: filters.append(df_res['OPM'] >= opm_val)
        if c_per: filters.append((df_res['PER'] <= per_val) & (df_res['PER'] > 0))
        if c_pbr: filters.append(df_res['PBR'] <= pbr_val)
        if c_amt: filters.append(df_res['거래액'] >= amt_val)
        if c_str: filters.append(df_res['매수비율'] >= str_val)
        if c_trs: filters.append(df_res['자사주'] >= trs_val)

        if not filters: df_final = df_res
        else:
            cond = filters[0]
            for f in filters[1:]:
                if "AND" in logic_gate: cond &= f
                else: cond |= f
            df_final = df_res[cond]

        # 결과 출력 (높이 확장 800px)
        col_l, col_r = st.columns(2)
        def display_df(df, market, area):
            with area:
                st.subheader(f"🏛️ {market}")
                m_df = df[df['시장'] == market].sort_values('매수비율', ascending=False).reset_index(drop=True)
                if not m_df.empty:
                    st.dataframe(
                        m_df.drop(columns=['시장']).style.format({
                            '현재가': '{:,.0f}', '상승률': '{:+.1f}%', '거래액': '{:,.1f}', '시총(억)': '{:,.1f}', 
                            'OPM': '{:.1f}', 'PER': '{:.1f}', 'PBR': '{:.1f}', '매수비율': '{:.1f}%', '자사주': '{:.1f}%'
                        }), use_container_width=True, height=800
                    )
                else: st.info(f"{market} 검색 결과 없음")

        display_df(df_final, 'KOSPI', col_l)
        display_df(df_final, 'KOSDAQ', col_r)