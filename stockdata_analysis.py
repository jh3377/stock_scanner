import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime, timedelta

# 1. 페이지 설정 및 경로
st.set_page_config(layout="wide", page_title="Ultimate Supply Scanner")
st.title("📊 통합 혼합형 수급 주도주 스캐너 (최종 완결판)")

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quant_scan_history.csv")
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
    """네이버 금융 시가총액 상위 리스트 수집 (거래소 서버 차단 우회)"""
    universe = []
    for sosok in ['0', '1']:
        for page in range(1, 3): 
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
                        marcap = to_numeric(tds[12].text)
                        universe.append({'Code': code, 'Name': name, 'Market': market, 'Marcap': marcap})
            except: continue
    return pd.DataFrame(universe).drop_duplicates('Code').head(target_count * 2)

# 2. 사이드바 설정
with st.sidebar:
    st.header("📅 설정")
    date_list = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(30)]
    start_date = st.selectbox("시작일", date_list, index=0)
    end_date = st.selectbox("종료일", date_list, index=0)
    target_count = st.selectbox("🎯 분석 범위", [10, 50, 100, 200], index=1)
    
    st.divider()
    st.header("🔍 상세 필터 (안 나오면 체크 해제)")
    c1 = st.checkbox("기관/외인 연속 매수", value=False); v1 = st.number_input("일수", 1, 10, 3)
    c2 = st.checkbox("최소 OPM(%)", value=False); v2 = st.number_input("OPM%", 0, 100, 5)
    c5 = st.checkbox("최소 거래액(억)", value=False); v5 = st.selectbox("거래액", [10, 50, 100, 500], index=1)
    c6 = st.checkbox("최소 매수비율(%)", value=False); v6 = st.slider("비율%", 0.1, 0.5, 0.1, 0.1)
    
    logic_gate = st.radio("🔄 조건 결합", ("AND (모두 만족)", "OR (하나라도 만족)"), index=1)

# 3. 메인 화면 (탭 구성)
tab1, tab2 = st.tabs(["🚀 실시간 분석 & 저장", "📈 성과 기록 분석"])

with tab1:
    if st.button("🚀 통합 분석 시작"):
        status = st.empty()
        bar = st.progress(0)
        df_uni = get_hybrid_universe(target_count)
        
        results = []
        try:
            target_dates = fdr.DataReader('005930', start_date, end_date).index.strftime('%Y.%m.%d').tolist()
        except: st.error("영업일 로드 실패"); st.stop()

        for i, row in enumerate(df_uni.itertuples()):
            bar.progress((i + 1) / len(df_uni))
            status.write(f"분석 중: {row.Name} ({i+1}/{len(df_uni)})")
            try:
                df_p = fdr.DataReader(row.Code, start_date, end_date)
                if df_p.empty: continue
                curr_p = int(df_p['Close'].iloc[-1])
                
                # 재무 및 수급 크롤링
                m_res = requests.get(f"https://finance.naver.com/item/main.naver?code={row.Code}", headers=HEADERS, timeout=5)
                m_soup = BeautifulSoup(m_res.text, 'html.parser')
                opm_td = m_soup.select('tr:-soup-contains("영업이익률") td')
                opm = to_numeric(opm_td[-4].text) if opm_td else 0.0

                f_res = requests.get(f"https://finance.naver.com/item/frgn.naver?code={row.Code}", headers=HEADERS, timeout=5)
                f_soup = BeautifulSoup(f_res.text, 'html.parser')
                f_rows = f_soup.select("table.type2 tr")
                inst_h, frgn_h, c_iv, c_fv = [], [], 0.0, 0.0
                for fr in f_rows:
                    tds = fr.find_all('td')
                    if len(tds) >= 7:
                        iv, fv = to_numeric(tds[5].text), to_numeric(tds[6].text)
                        inst_h.append(iv); frgn_h.append(fv)
                        if tds[0].text.strip() in target_dates: c_iv += iv; c_fv += fv

                results.append({
                    'Symbol': row.Code, '시장': row.Market, '종목명': row.Name, '현재가': curr_p,
                    '등락률': round(((curr_p/df_p['Open'].iloc[0])-1)*100, 1), 'OPM': opm,
                    '거래액(억)': round((df_p['Close'] * df_p['Volume']).sum() / 100000000, 1),
                    '외인(억)': round(c_fv * curr_p / 100000000, 1), '기관(억)': round(c_iv * curr_p / 100000000, 1),
                    '합계(억)': round((c_iv + c_fv) * curr_p / 100000000, 1),
                    '매수비율': round(((c_iv + c_fv) * curr_p / 100000000 / row.Marcap) * 100, 2),
                    '기관연속': calculate_consecutive_days(inst_h), '외인연속': calculate_consecutive_days(frgn_h),
                    'scan_date': end_date
                })
            except: continue
        
        status.empty()
        if results:
            df_res = pd.DataFrame(results)
            # 필터링 적용
            f_conds = []
            if c1: f_conds.append((df_res['기관연속'] >= v1) | (df_res['외인연속'] >= v1))
            if c2: f_conds.append(df_res['OPM'] >= v2)
            if c5: f_conds.append(df_res['거래액(억)'] >= v5)
            if c6: f_conds.append(df_res['매수비율'] >= v6)
            
            df_final = df_res if not f_conds else (df_res[pd.concat(f_conds, axis=1).all(axis=1)] if "AND" in logic_gate else df_res[pd.concat(f_conds, axis=1).any(axis=1)])
            
            if not df_final.empty:
                df_final.to_csv(HISTORY_FILE, mode='a', header=not os.path.exists(HISTORY_FILE), index=False, encoding='utf-8-sig')
                st.success(f"✅ 필터 조건에 맞는 {len(df_final)}개 종목 발견")
                float_cols = ['등락률', 'OPM', '거래액(억)', '외인(억)', '기관(억)', '합계(억)', '매수비율']
                c_k, c_q = st.columns(2)
                with c_k: 
                    st.subheader("🏢 KOSPI"); st.dataframe(df_final[df_final['시장'] == 'KOSPI'].style.format("{:.1f}", subset=float_cols), use_container_width=True, height=750)
                with c_q: 
                    st.subheader("🚀 KOSDAQ"); st.dataframe(df_final[df_final['시장'] == 'KOSDAQ'].style.format("{:.1f}", subset=float_cols), use_container_width=True, height=750)
            else:
                st.warning("⚠️ 필터 조건에 맞는 종목이 없습니다. 아래의 전체 분석 결과를 확인하고 조건을 조절해 보세요.")
                st.write("전체 분석 결과 (필터 적용 전):")
                st.dataframe(df_res[['종목명', '거래액(억)', 'OPM', '매수비율', '기관연속', '외인연속']], use_container_width=True)
        else:
            st.error("분석된 데이터가 없습니다. 날짜나 인터넷 연결을 확인해 주세요.")

with tab2:
    st.header("📈 성과 기록 상세 분석 리포트")
    if os.path.exists(HISTORY_FILE):
        try:
            h_data = pd.read_csv(HISTORY_FILE)
            available_dates = sorted(h_data['scan_date'].unique(), reverse=True)
            sc1, sc2 = st.columns(2)
            with sc1: sel_scan_date = st.selectbox("📅 스캔 날짜", available_dates)
            with sc2: sel_compare_date = st.date_input("📅 비교 기준일", datetime.now())
            
            targets = h_data[h_data['scan_date'] == sel_scan_date].copy()
            if st.button("🔄 성과 분석 시작"):
                perf_list = []
                for r in targets.itertuples():
                    try:
                        p_df = fdr.DataReader(str(r.Symbol).zfill(6), (sel_compare_date - timedelta(days=5)).strftime('%Y-%m-%d'), sel_compare_date.strftime('%Y-%m-%d'))
                        p_now, p_scan = int(p_df['Close'].iloc[-1]), int(r.현재가)
                        perf_list.append({
                            '시장': r.시장, '종목명': r.종목명, '스캔가': f"{p_scan:,}원", '현재가': f"{p_now:,}원", 
                            '수익률(%)': round(((p_now / p_scan) - 1) * 100, 1), '매수비율': round(r.매수비율, 1),
                            '외인(억)': round(r.외인(억), 1), '기관(억)': round(r.기관(억), 1)
                        })
                    except: continue
                if perf_list:
                    res_df = pd.DataFrame(perf_list)
                    st.subheader(f"🎯 성과 결과 (기준: {sel_compare_date})")
                    c1_res, c2_res = st.columns(2)
                    with c1_res: st.info("🏢 KOSPI"); st.dataframe(res_df[res_df['시장'] == 'KOSPI'], use_container_width=True, height=750)
                    with c2_res: st.success("🚀 KOSDAQ"); st.dataframe(res_df[res_df['시장'] == 'KOSDAQ'], use_container_width=True, height=750)
                else: st.warning("비교일 데이터를 가져올 수 없습니다.")
        except Exception as e: st.error(f"기록 로드 실패: {e}")
    else: st.info("저장된 기록이 없습니다. 먼저 첫 번째 탭에서 분석을 완료해 주세요.")
