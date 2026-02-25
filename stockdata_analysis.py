import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime, timedelta
import io

# 1. 페이지 설정 및 경로 고정
st.set_page_config(layout="wide", page_title="Ultimate Supply Scanner")
st.title("📊 통합 혼합형 수급 주도주 스캐너 (모바일 안정화 버전)")

# 파일 경로 및 기본 설정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(CURRENT_DIR, "quant_scan_history.csv")
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}

def to_numeric(value):
    try:
        val = str(value).replace(',', '').replace('%', '').strip()
        return float(val) if val not in ['', '-', 'N/A'] else 0.0
    except: return 0.0

def calculate_consecutive_days(data_list):
    count = 0
    for val in data_list:
        if val > 0: count += 1
        else: break
    return count

def get_hybrid_universe(target_count):
    """안정성을 위해 KRX 서버 대신 네이버 금융 시가총액 상위 리스트를 직접 수집"""
    universe = []
    # 네이버 금융 시가총액 페이지 (KOSPI=0, KOSDAQ=1)
    for sosok in ['0', '1']:
        for page in range(1, 5):  # 페이지당 50개씩 수집
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            try:
                res = requests.get(url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(res.text, 'html.parser')
                rows = soup.select("table.type_2 tr")
                for r in rows:
                    tds = r.find_all("td")
                    if len(tds) > 1 and tds[1].find("a"):
                        code = tds[1].find("a")['href'].split("=")[-1]
                        name = tds[1].text.strip()
                        market = "KOSPI" if sosok == '0' else "KOSDAQ"
                        marcap = to_numeric(tds[12].text) # 시가총액(억)
                        universe.append({'Code': code, 'Name': name, 'Market': market, 'Marcap': marcap})
            except: continue
    
    df_all = pd.DataFrame(universe).drop_duplicates('Code')
    return df_all.head(target_count * 2)

# 2. 사이드바 설정 (매수비율 0.1 ~ 0.5 반영)
with st.sidebar:
    st.header("📅 분석 설정")
    date_list = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(30)]
    start_date = st.selectbox("분석 시작일", date_list, index=0)
    end_date = st.selectbox("분석 종료일", date_list, index=0)
    target_count = st.selectbox("🎯 분석 범위", [10, 100, 200, 300, 500, 1000], index=1)
    
    st.divider()
    st.header("🔍 상세 필터 조건")
    c1 = st.checkbox("기관 or 외인 연속 매수 (일)", value=True); v1 = st.selectbox("연속 매수", list(range(1, 11)), index=2, label_visibility="collapsed")
    c2 = st.checkbox("최소 OPM (%)", value=True); v2 = st.selectbox("OPM", list(range(0, 31, 5)), index=1, label_visibility="collapsed")
    c3 = st.checkbox("최대 PER (배)", value=True); v3 = st.selectbox("PER 설정", list(range(5, 505, 5)), index=19, label_visibility="collapsed")
    c4 = st.checkbox("최대 PBR (배)", value=True); v4 = st.selectbox("PBR 설정", [round(i*0.5, 1) for i in range(1, 41)], index=10, label_visibility="collapsed")
    c5 = st.checkbox("최소 거래액 (억)", value=True); v5 = st.selectbox("거래액", [10, 50, 100, 500, 1000], index=2, label_visibility="collapsed")
    
    # 매수비율 필터 범위 (0.1 ~ 0.5)
    c6 = st.checkbox("최소 매수비율 (%)", value=True)
    v6 = st.selectbox("매수비율 설정", [0.1, 0.2, 0.3, 0.4, 0.5], index=0, label_visibility="collapsed")
    
    logic_gate = st.radio("🔄 조건 결합 방식", ("AND (모두 만족)", "OR (하나라도 만족)"), label_visibility="collapsed")

# 3. 메인 분석 화면
tab1, tab2 = st.tabs(["🚀 실시간 분석 & 저장", "📈 성과 기록 분석"])

with tab1:
    if st.button("🚀 통합 고속 분석 시작"):
        progress_bar = st.progress(0, text="종목 리스트 수집 중...")
        status_text = st.empty()
        df_universe = get_hybrid_universe(target_count)
        
        results = []
        total_len = len(df_universe)
        # 영업일 데이터 (삼성전자 기준)
        try:
            target_dates = fdr.DataReader('005930', start_date, end_date).index.strftime('%Y.%m.%d').tolist()
        except: st.error("영업일 로드 실패. 잠시 후 다시 시도해 주세요."); st.stop()

        for i, row in enumerate(df_universe.itertuples()):
            progress_bar.progress((i + 1) / total_len, text=f"분석 중: {row.Name} ({i+1}/{total_len})")
            try:
                # 가격 데이터
                df_p = fdr.DataReader(row.Code, start_date, end_date)
                if df_p.empty: continue
                curr_p = int(df_p['Close'].iloc[-1])
                
                # 재무 크롤링
                res_m = requests.get(f"https://finance.naver.com/item/main.naver?code={row.Code}", headers=HEADERS, timeout=5)
                soup_m = BeautifulSoup(res_m.text, 'html.parser')
                f_table = soup_m.select_one('div.section.cop_analysis')
                opm, per, pbr = 0.0, 0.0, 0.0
                if f_table:
                    t_opm = f_table.select('tr:-soup-contains("영업이익률") td'); opm = to_numeric(t_opm[-4].text) if t_opm else 0.0
                    t_per = f_table.select('tr:-soup-contains("PER") td'); per = to_numeric(t_per[-4].text) if t_per else 0.0
                    t_pbr = f_table.select('tr:-soup-contains("PBR") td'); pbr = to_numeric(t_pbr[-4].text) if t_pbr else 0.0
                
                # 수급 데이터
                res_f = requests.get(f"https://finance.naver.com/item/frgn.naver?code={row.Code}", headers=HEADERS, timeout=5)
                soup_f = BeautifulSoup(res_f.text, 'html.parser')
                rows_f = soup_f.select("table.type2 tr")
                inst_h, frgn_h, c_iv, c_fv = [], [], 0.0, 0.0
                for r_f in rows_f:
                    tds = r_f.find_all('td')
                    if len(tds) >= 7:
                        iv, fv = to_numeric(tds[5].text), to_numeric(tds[6].text)
                        inst_h.append(iv); frgn_h.append(fv)
                        if tds[0].text.strip() in target_dates: c_iv += iv; c_fv += fv
                
                m_cap_val = row.Marcap
                
                results.append({
                    'Symbol': row.Code, '시장': row.Market, '종목명': row.Name, '현재가': int(curr_p),
                    '등락률': round(((curr_p/df_p['Open'].iloc[0])-1)*100, 1),
                    'OPM': round(opm, 1), 'PER': round(per, 1), 'PBR': round(pbr, 1),
                    '거래액(억)': round((df_p['Close'] * df_p['Volume']).sum() / 100000000, 1),
                    '외인(억)': round(c_fv * curr_p / 100000000, 1), '기관(억)': round(c_iv * curr_p / 100000000, 1),
                    '합계(억)': round((c_iv + c_fv) * curr_p / 100000000, 1),
                    '매수비율': round(((c_iv + c_fv) * curr_p / 100000000 / m_cap_val) * 100, 1),
                    '기관연속': calculate_consecutive_days(inst_h), '외인연속': calculate_consecutive_days(frgn_h),
                    'scan_date': end_date
                })
            except: continue
            
        status_text.empty()
        if results:
            df_res = pd.DataFrame(results)
            f_conds = []
            if c1: f_conds.append((df_res['기관연속'] >= v1) | (df_res['외인연속'] >= v1))
            if c2: f_conds.append(df_res['OPM'] >= v2)
            if c3: f_conds.append((df_res['PER'] <= v3) & (df_res['PER'] > 0))
            if c4: f_conds.append((df_res['PBR'] <= v4) & (df_res['PBR'] > 0))
            if c5: f_conds.append(df_res['거래액(억)'] >= v5)
            if c6: f_conds.append(df_res['매수비율'] >= v6)
            
            df_final = df_res if not f_conds else (df_res[pd.concat(f_conds, axis=1).all(axis=1)] if "AND" in logic_gate else df_res[pd.concat(f_conds, axis=1).any(axis=1)])
            df_final = df_final.sort_values(by='합계(억)', ascending=False)
            df_final.to_csv(HISTORY_FILE, mode='a', header=not os.path.exists(HISTORY_FILE), index=False, encoding='utf-8-sig')
            
            st.success(f"✅ 분석 완료 및 저장! ({len(df_final)}개 포착)")
            out_cols = ['종목명', '현재가', '등락률', 'OPM', 'PER', 'PBR', '거래액(억)', '외인(억)', '기관(억)', '합계(억)', '매수비율', '기관연속', '외인연속']
            float_cols = ['등락률', 'OPM', 'PER', 'PBR', '거래액(억)', '외인(억)', '기관(억)', '합계(억)', '매수비율']
            
            pc1, pc2 = st.columns(2)
            with pc1:
                st.subheader("🏢 KOSPI 주도주")
                st.dataframe(df_final[df_final['시장'] == 'KOSPI'][out_cols].style.format("{:.1f}", subset=float_cols), use_container_width=True, height=750) 
            with pc2:
                st.subheader("🚀 KOSDAQ 주도주")
                st.dataframe(df_final[df_final['시장'] == 'KOSDAQ'][out_cols].style.format("{:.1f}", subset=float_cols), use_container_width=True, height=750)

# 4. 성과 기록 분석 화면
with tab2:
    st.header("📈 성과 기록 상세 분석 리포트")
    if os.path.exists(HISTORY_FILE):
        try:
            h_data = pd.read_csv(HISTORY_FILE, dtype={'scan_date': str})
            h_data['Symbol'] = h_data['Symbol'].astype(str).str.zfill(6)
            available_dates = sorted(h_data['scan_date'].unique(), reverse=True)
            
            sc1, sc2 = st.columns(2)
            with sc1: sel_scan_date = st.selectbox("📅 스캔 날짜 선택", available_dates)
            with sc2: sel_compare_date = st.date_input("📅 비교 기준일 선택", datetime.now())
            
            targets = h_data[h_data['scan_date'] == sel_scan_date].copy()
            if st.button("🔄 실시간 수익률 비교 시작"):
                perf_list = []
                status_msg = st.empty()
                for r in targets.itertuples():
                    status_msg.text(f"📡 {r.종목명} 최신가 조회 중...")
                    try:
                        p_df = fdr.DataReader(r.Symbol, (sel_compare_date - timedelta(days=5)).strftime('%Y-%m-%d'), sel_compare_date.strftime('%Y-%m-%d'))
                        if p_df.empty: continue
                        p_now, p_scan = int(p_df['Close'].iloc[-1]), int(r.현재가)
                        perf_list.append({
                            '시장': r.시장, '종목명': r.종목명, '스캔가': f"{p_scan:,}원", '현재가': f"{p_now:,}원", 
                            '수익률(%)': round(((p_now / p_scan) - 1) * 100, 1), '매수비율': round(r.매수비율, 1),
                            '외인(억)': round(r.외인(억), 1), '기관(억)': round(r.기관(억), 1), '외인연속': int(r.외인연속), '기관연속': int(r.기관연속)
                        })
                    except: continue
                status_msg.empty()
                if perf_list:
                    res_df = pd.DataFrame(perf_list)
                    def style_profit(v): return f"color: {'red' if v < 0 else ('blue' if v > 0 else 'black')}"
                    pc1_res, pc2_res = st.columns(2)
                    perf_cols = ['종목명', '스캔가', '현재가', '수익률(%)', '매수비율', '외인(억)', '기관(억)', '외인연속', '기관연속']
                    with pc1_res:
                        st.info("🏢 KOSPI 성과")
                        df_k_res = res_df[res_df['시장'] == 'KOSPI'].sort_values('수익률(%)', ascending=False)
                        st.dataframe(df_k_res[perf_cols].style.applymap(style_profit, subset=['수익률(%)']).format("{:.1f}", subset=['수익률(%)', '매수비율', '외인(억)', '기관(억)']), use_container_width=True, height=750)
                    with pc2_res:
                        st.success("🚀 KOSDAQ 성과")
                        df_q_res = res_df[res_df['시장'] == 'KOSDAQ'].sort_values('수익률(%)', ascending=False)
                        st.dataframe(df_q_res[perf_cols].style.applymap(style_profit, subset=['수익률(%)']).format("{:.1f}", subset=['수익률(%)', '매수비율', '외인(억)', '기관(억)']), use_container_width=True, height=750)
                else: st.warning("선택한 날짜에 조회 가능한 데이터가 없습니다.")
        except Exception as e: st.error(f"데이터 로드 오류: {e}")
