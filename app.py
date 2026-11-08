import datetime
from datetime import timedelta
import json
import os
import threading
import time
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px

# -----------------------------------------------------------------------------
# 페이지 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="포트폴리오 시뮬레이터 (Portfolio Simulator)",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 로컬 저장 파일 경로
DATA_FILE = "portfolios_data.json"

# -----------------------------------------------------------------------------
# 웹페이지(브라우저) 종료 감지 시 백그라운드 cmd/서버 자동 종료 감시자
# -----------------------------------------------------------------------------
if "server_watcher_started" not in st.session_state:
    st.session_state.server_watcher_started = True

    def auto_close_on_browser_exit():
        time.sleep(6)
        has_connected = False
        while True:
            time.sleep(2)
            try:
                from streamlit.runtime import Runtime
                runtime = Runtime.instance()
                if runtime:
                    session_mgr = runtime._session_mgr
                    active_sessions = session_mgr.list_active_sessions()
                    if len(active_sessions) > 0:
                        has_connected = True
                    elif has_connected and len(active_sessions) == 0:
                        time.sleep(5)
                        if len(session_mgr.list_active_sessions()) == 0:
                            os._exit(0)
            except Exception:
                pass

    watcher_thread = threading.Thread(target=auto_close_on_browser_exit, daemon=True)
    watcher_thread.start()

# 커스텀 CSS (카드 스타일 및 배지 디자인)
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 18px;
        border-left: 5px solid #4A90E2;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .status-badge-profit {
        background-color: #d4edda;
        color: #155724;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .status-badge-loss {
        background-color: #f8d7da;
        color: #721c24;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .status-badge-hold {
        background-color: #cce5ff;
        color: #004085;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: 600;
        display: inline-block;
    }
    .mode-badge {
        background-color: #e2e3e5;
        color: #383d41;
        padding: 3px 8px;
        border-radius: 8px;
        font-size: 0.85rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 기본 설정 템플릿 (기본 모드는 항상 모드 1)
# -----------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "stop_loss_pct": -5.0,
    "take_profit_pct": 15.0,
    "exit_mode": "모드 1: 목표가 도달 시 즉시 익절",
    "mode2_drop_pct": -5.0,
    "mode3_step_up": 10.0,
    "mode3_drop_pct": -5.0,
}


# -----------------------------------------------------------------------------
# 포트폴리오 저장 / 불러오기 직렬화 도우미 함수 (설정 포함)
# -----------------------------------------------------------------------------
def serialize_portfolios(portfolios: dict, settings: dict) -> str:
    """포트폴리오 종목 리스트와 각 포트폴리오별 설정을 JSON 문자열로 직렬화합니다."""
    serializable = {"portfolios": {}, "settings": {}}
    for p_name, items in portfolios.items():
        serializable["portfolios"][p_name] = []
        for item in items:
            b_date = item["buy_date"]
            if isinstance(b_date, (datetime.date, datetime.datetime)):
                b_date_str = b_date.strftime("%Y-%m-%d")
            else:
                b_date_str = str(b_date)
            serializable["portfolios"][p_name].append({
                "ticker": str(item["ticker"]).strip().upper(),
                "buy_date": b_date_str,
                "shares": float(item.get("shares", 0.0)),
                "custom_buy_price": float(item["custom_buy_price"]) if item.get("custom_buy_price") else None,
                "invest_amount": float(item["invest_amount"]) if item.get("invest_amount") else None
            })
        serializable["settings"][p_name] = settings.get(p_name, DEFAULT_SETTINGS.copy())
    return json.dumps(serializable, ensure_ascii=False, indent=2)


def deserialize_portfolios(json_str: str) -> tuple:
    """JSON 문자열을 포트폴리오 딕셔너리와 설정 딕셔너리로 역직렬화합니다."""
    data = json.loads(json_str)
    deserialized_portfolios = {}
    deserialized_settings = {}

    if "portfolios" in data and isinstance(data["portfolios"], dict):
        raw_portfolios = data["portfolios"]
        raw_settings = data.get("settings", {})
    else:
        raw_portfolios = data
        raw_settings = {}

    for p_name, items in raw_portfolios.items():
        deserialized_portfolios[p_name] = []
        for item in items:
            b_date_val = item.get("buy_date")
            if isinstance(b_date_val, str):
                try:
                    parsed_date = datetime.datetime.strptime(b_date_val, "%Y-%m-%d").date()
                except Exception:
                    parsed_date = datetime.date.today()
            elif isinstance(b_date_val, (datetime.date, datetime.datetime)):
                parsed_date = b_date_val
            else:
                parsed_date = datetime.date.today()

            deserialized_portfolios[p_name].append({
                "ticker": str(item.get("ticker", "")).strip().upper(),
                "buy_date": parsed_date,
                "shares": float(item.get("shares", 0.0)),
                "custom_buy_price": float(item["custom_buy_price"]) if item.get("custom_buy_price") else None,
                "invest_amount": float(item["invest_amount"]) if item.get("invest_amount") else None
            })

        if p_name in raw_settings:
            merged_s = DEFAULT_SETTINGS.copy()
            merged_s.update(raw_settings[p_name])
            if "계단식" in merged_s.get("exit_mode", ""):
                merged_s["exit_mode"] = "모드 1: 목표가 도달 시 즉시 익절"
            deserialized_settings[p_name] = merged_s
        else:
            deserialized_settings[p_name] = DEFAULT_SETTINGS.copy()

    return deserialized_portfolios, deserialized_settings


def save_to_disk(portfolios: dict, settings: dict, filepath: str = DATA_FILE):
    """로컬 파일에 포트폴리오 데이터와 설정을 자동 저장합니다."""
    try:
        content = serialize_portfolios(portfolios, settings)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        st.warning(f"로컬 파일 저장 중 오류 발생: {e}")


def load_from_disk(filepath: str = DATA_FILE) -> tuple:
    """로컬 파일에서 포트폴리오 데이터와 설정을 불러옵니다."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                return deserialize_portfolios(content)
        except Exception:
            return None, None
    return None, None


# -----------------------------------------------------------------------------
# 세션 상태(Session State) 초기화
# -----------------------------------------------------------------------------
if "portfolios" not in st.session_state or "portfolio_settings" not in st.session_state:
    loaded_p, loaded_s = load_from_disk()
    if loaded_p and len(loaded_p) > 0:
        st.session_state.portfolios = loaded_p
        st.session_state.portfolio_settings = loaded_s if loaded_s else {}
    else:
        st.session_state.portfolios = {
            "기본 포트폴리오": [
                {"ticker": "NVDA", "buy_date": datetime.date(2024, 1, 15), "shares": 10.123456, "custom_buy_price": None, "invest_amount": 0.0},
                {"ticker": "TSLA", "buy_date": datetime.date(2024, 3, 1), "shares": 15.0, "custom_buy_price": None, "invest_amount": 0.0},
                {"ticker": "AAPL", "buy_date": datetime.date(2024, 6, 1), "shares": 20.25, "custom_buy_price": None, "invest_amount": 0.0},
            ]
        }
        st.session_state.portfolio_settings = {
            "기본 포트폴리오": DEFAULT_SETTINGS.copy()
        }
        save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)

# 기본 포트폴리오의 초기 기본 모드를 확실하게 모드 1로 보장
if "initialized_default_mode" not in st.session_state:
    st.session_state.initialized_default_mode = True
    if "기본 포트폴리오" in st.session_state.portfolio_settings:
        st.session_state.portfolio_settings["기본 포트폴리오"]["exit_mode"] = "모드 1: 목표가 도달 시 즉시 익절"
        save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)

p_names = list(st.session_state.portfolios.keys())
if "current_portfolio_name" not in st.session_state or st.session_state.current_portfolio_name not in p_names:
    st.session_state.current_portfolio_name = p_names[0] if p_names else "기본 포트폴리오"

if "last_buy_date" not in st.session_state:
    st.session_state.last_buy_date = datetime.date.today()


# -----------------------------------------------------------------------------
# 주가 데이터 가져오기 (캐싱 활용)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600)
def fetch_stock_history(ticker: str, start_date: datetime.date):
    """Yahoo Finance에서 매수일 이전 거래일부터 현재까지의 일별 주가 데이터를 조회합니다."""
    try:
        stock = yf.Ticker(ticker.strip().upper())
        fetch_start = start_date - timedelta(days=7)
        df = stock.history(start=fetch_start)
        if df.empty:
            return None, "데이터를 찾을 수 없습니다. 티커를 확인해주세요."
        return df, None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=60)
def fetch_current_price(ticker: str):
    """실시간 최신 주가를 조회합니다."""
    try:
        stock = yf.Ticker(ticker.strip().upper())
        fast_info = getattr(stock, "fast_info", None)
        if fast_info and hasattr(fast_info, "last_price") and fast_info.last_price:
            return float(fast_info.last_price)
        
        hist = stock.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None
    except Exception:
        return None


def format_shares(shares: float) -> str:
    """수량을 소수점 6자리까지 포맷하고 뒤쪽 불필요한 0을 정리합니다."""
    return f"{shares:.6f}".rstrip("0").rstrip(".")


def resolve_shares_and_price(
    ticker: str,
    buy_date: datetime.date,
    input_shares: float,
    input_invest_amt: float,
    input_custom_price: float
):
    """사용자 입력을 바탕으로 실제 체결 매수가격, 매입금액, 수량을 확정합니다."""
    ticker_clean = ticker.strip().upper()
    df, err = fetch_stock_history(ticker_clean, buy_date)

    close_price = None
    if df is not None and not df.empty:
        df.index = df.index.tz_localize(None)
        df["Date"] = df.index.date
        df_from_buy = df[df["Date"] >= buy_date]
        if not df_from_buy.empty:
            close_price = float(df_from_buy["Close"].iloc[0])
        else:
            close_price = float(df["Close"].iloc[-1])
    else:
        realtime = fetch_current_price(ticker_clean)
        if realtime:
            close_price = float(realtime)

    if input_custom_price and input_custom_price > 0:
        actual_price = float(input_custom_price)
    else:
        if close_price is None or close_price <= 0:
            return {"error": f"'{ticker_clean}'의 매수일 주가 데이터를 조회할 수 없습니다. 티커와 매수일을 확인해주세요."}
        actual_price = float(close_price)

    if (input_custom_price <= 0) and (input_invest_amt <= 0) and (input_shares <= 0):
        final_invest_amt = 1.0
        final_shares = final_invest_amt / actual_price
    elif input_invest_amt > 0:
        final_invest_amt = float(input_invest_amt)
        final_shares = final_invest_amt / actual_price
    elif input_shares > 0:
        final_shares = float(input_shares)
        final_invest_amt = final_shares * actual_price
    else:
        final_invest_amt = 1.0
        final_shares = final_invest_amt / actual_price

    return {
        "error": None,
        "buy_price": actual_price,
        "invest_amt": final_invest_amt,
        "shares": final_shares
    }


# -----------------------------------------------------------------------------
# 3가지 모드 지원 손절/익절 시뮬레이션 핵심 계산 로직
# -----------------------------------------------------------------------------
def simulate_position(item: dict, settings: dict):
    """
    모드 1, 2, 3 지원 포지션 시뮬레이션:
    - 공통 손절선: 매수가 대비 손절선(예: -5%) 이하 시 손절 종료
    - 모드 1 (단일 익절): 익절선(예: +15%) 도달 시 즉시 전량 매도 종료
    - 모드 2 (최고가 추적 트레일링): 익절선 도달 후 기록한 장중 최고가 대비 지정 비율(-5%) 하락 시 매도
    - 모드 3 (직전 목표가 기준 방어선 상향): 익절선 도달 시 직전 목표가 대비 -5%로 매도가 상향, 미도달 시 계속 보유
    """
    ticker = str(item["ticker"]).strip().upper()
    buy_date = item["buy_date"]
    if isinstance(buy_date, str):
        try:
            buy_date = datetime.datetime.strptime(buy_date, "%Y-%m-%d").date()
        except Exception:
            buy_date = datetime.date.today()

    shares = float(item.get("shares", 0.0))
    custom_buy_price = item.get("custom_buy_price")
    saved_invest_amt = item.get("invest_amount")

    stop_loss_pct = settings.get("stop_loss_pct", -5.0)
    take_profit_pct = settings.get("take_profit_pct", 15.0)
    exit_mode = settings.get("exit_mode", "모드 1: 목표가 도달 시 즉시 익절")

    m2_drop = settings.get("mode2_drop_pct", -5.0)
    m3_step_up = settings.get("mode3_step_up", 10.0)
    m3_drop = settings.get("mode3_drop_pct", -5.0)

    df, err = fetch_stock_history(ticker, buy_date)
    if df is None:
        return {
            "ticker": ticker,
            "error": err,
            "status": "오류",
            "buy_date": buy_date.strftime("%Y-%m-%d"),
            "buy_price": 0.0,
            "shares": shares,
            "current_price": 0.0,
            "exit_date": "-",
            "exit_price": 0.0,
            "return_pct": 0.0,
            "invested_amt": 0.0,
            "final_value": 0.0,
            "pnl": 0.0,
            "history_df": None,
            "hit_tp1": False,
            "stage": 1
        }

    df.index = df.index.tz_localize(None)
    df["Date"] = df.index.date

    df_from_buy = df[df["Date"] >= buy_date].copy()
    if df_from_buy.empty:
        buy_price = float(custom_buy_price) if custom_buy_price else float(df["Close"].iloc[-1])
        if shares <= 0:
            inv_amt = float(saved_invest_amt) if saved_invest_amt else 1.0
            shares = inv_amt / buy_price
        return {
            "ticker": ticker,
            "status": "보유 중",
            "buy_date": buy_date.strftime("%Y-%m-%d"),
            "buy_price": buy_price,
            "shares": shares,
            "current_price": buy_price,
            "exit_date": "-",
            "exit_price": buy_price,
            "return_pct": 0.0,
            "invested_amt": buy_price * shares,
            "final_value": buy_price * shares,
            "pnl": 0.0,
            "history_df": df,
            "hit_tp1": False,
            "stage": 1
        }

    actual_buy_date = df_from_buy["Date"].iloc[0]
    if custom_buy_price and float(custom_buy_price) > 0:
        buy_price = float(custom_buy_price)
    else:
        buy_price = float(df_from_buy["Close"].iloc[0])

    if shares <= 0:
        inv_amt = float(saved_invest_amt) if saved_invest_amt and float(saved_invest_amt) > 0 else 1.0
        shares = inv_amt / buy_price

    realtime_price = fetch_current_price(ticker)
    if realtime_price is None:
        realtime_price = float(df_from_buy["Close"].iloc[-1])

    status = "보유 중"
    exit_date = "-"
    exit_price = realtime_price
    final_return_pct = ((realtime_price - buy_price) / buy_price) * 100

    df_after_buy = df[df["Date"] > actual_buy_date].copy()

    hit_tp1 = False
    stage = 1

    highest_price_after_tp1 = 0.0

    m3_last_target = buy_price * (1 + take_profit_pct / 100)
    m3_stop = m3_last_target * (1 + m3_drop / 100)
    m3_next_target = m3_last_target * (1 + m3_step_up / 100)

    if not df_after_buy.empty:
        for idx, row in df_after_buy.iterrows():
            c_price = float(row["Close"])
            c_return = ((c_price - buy_price) / buy_price) * 100
            cur_date = row["Date"]

            # [1단계] 1차 익절 목표 도달 전
            if not hit_tp1:
                if c_return <= stop_loss_pct:
                    status = "손절"
                    exit_date = cur_date.strftime("%Y-%m-%d")
                    exit_price = c_price
                    final_return_pct = c_return
                    break
                elif c_return >= take_profit_pct:
                    if "모드 1" in exit_mode:
                        status = "익절 (목표 달성 매도)"
                        exit_date = cur_date.strftime("%Y-%m-%d")
                        exit_price = c_price
                        final_return_pct = c_return
                        break
                    
                    hit_tp1 = True
                    stage = 1
                    if "모드 2" in exit_mode:
                        highest_price_after_tp1 = c_price
                    elif "모드 3" in exit_mode:
                        m3_last_target = buy_price * (1 + take_profit_pct / 100)
                        m3_stop = m3_last_target * (1 + m3_drop / 100)
                        m3_next_target = m3_last_target * (1 + m3_step_up / 100)
                    continue

            # [2단계 이상] 모드 2 또는 모드 3의 1차 목표 달성 이후 추적
            else:
                if "모드 2" in exit_mode:
                    if c_price > highest_price_after_tp1:
                        highest_price_after_tp1 = c_price
                    current_m2_stop = highest_price_after_tp1 * (1 + m2_drop / 100)
                    if c_price <= current_m2_stop:
                        status = "익절 (최고가 트레일링 매도)"
                        exit_date = cur_date.strftime("%Y-%m-%d")
                        exit_price = c_price
                        final_return_pct = c_return
                        break

                elif "모드 3" in exit_mode:
                    if c_price <= m3_stop:
                        status = f"익절 ({stage}차 목표 달성 후 매도)"
                        exit_date = cur_date.strftime("%Y-%m-%d")
                        exit_price = c_price
                        final_return_pct = c_return
                        break
                    elif c_price >= m3_next_target:
                        stage += 1
                        m3_last_target = m3_next_target
                        m3_stop = m3_last_target * (1 + m3_drop / 100)
                        m3_next_target = m3_last_target * (1 + m3_step_up / 100)

    if exit_date == "-":
        if hit_tp1:
            if "모드 2" in exit_mode:
                status = "보유 중 (고점 추종중)"
            elif "모드 3" in exit_mode:
                status = f"보유 중 ({stage}차 목표 달성 유지)"
        else:
            status = "보유 중"

    invested_amt = buy_price * shares
    final_value = exit_price * shares
    pnl = final_value - invested_amt

    return {
        "ticker": ticker,
        "status": status,
        "buy_date": actual_buy_date.strftime("%Y-%m-%d"),
        "buy_price": buy_price,
        "shares": shares,
        "current_price": realtime_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "return_pct": final_return_pct,
        "invested_amt": invested_amt,
        "final_value": final_value,
        "pnl": pnl,
        "history_df": df[df["Date"] >= actual_buy_date].copy(),
        "hit_tp1": hit_tp1,
        "stage": stage
    }


# -----------------------------------------------------------------------------
# 사이드바: 1. 다중 포트폴리오 선택 및 전환
# -----------------------------------------------------------------------------
st.sidebar.header("📁 포트폴리오 선택")

portfolio_list = list(st.session_state.portfolios.keys())
if st.session_state.current_portfolio_name not in portfolio_list:
    st.session_state.current_portfolio_name = portfolio_list[0]

curr_idx = portfolio_list.index(st.session_state.current_portfolio_name)
selected_portfolio_name = st.sidebar.selectbox(
    "관리할 포트폴리오",
    options=portfolio_list,
    index=curr_idx,
    help="여러 포트폴리오 중 하나를 선택하여 분석 및 관리합니다."
)

if selected_portfolio_name != st.session_state.current_portfolio_name:
    st.session_state.current_portfolio_name = selected_portfolio_name
    st.rerun()

with st.sidebar.expander("➕ 새 포트폴리오 만들기"):
    with st.form(key="quick_add_portfolio_form", clear_on_submit=True):
        new_p_name_input = st.text_input("새 포트폴리오 이름", placeholder="예: 배당주 포트폴리오").strip()
        add_p_btn = st.form_submit_button("생성 및 전환")
        if add_p_btn:
            if not new_p_name_input:
                st.sidebar.error("이름을 입력해주세요.")
            elif new_p_name_input in st.session_state.portfolios:
                st.sidebar.error("이미 존재하는 포트폴리오 이름입니다.")
            else:
                st.session_state.portfolios[new_p_name_input] = []
                st.session_state.portfolio_settings[new_p_name_input] = DEFAULT_SETTINGS.copy()
                st.session_state.current_portfolio_name = new_p_name_input
                save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                st.sidebar.success(f"'{new_p_name_input}' 생성 완료!")
                st.rerun()

st.sidebar.markdown("---")

# -----------------------------------------------------------------------------
# 사이드바: 2. 종목 추가 (패널 위치 상단으로 이동!)
# -----------------------------------------------------------------------------
st.sidebar.subheader(f"➕ [{st.session_state.current_portfolio_name}] 종목 추가")

with st.sidebar.form(key="add_stock_form", clear_on_submit=True):
    new_ticker = st.text_input("티커 (소문자 입력 시 대문자 자동 변환)", placeholder="예: tsla, aapl").strip().upper()
    new_buy_date = st.date_input(
        "매수일",
        value=st.session_state.last_buy_date,
        max_value=datetime.date.today(),
        help="직전에 입력한 매수일이 다음 입력의 시작일로 자동 유지됩니다."
    )
    new_shares = st.number_input(
        "매수 수량 (주) (초기값: 0, 매입 금액 입력 시 자동 계산)",
        min_value=0.0,
        value=0.0,
        step=0.000001,
        format="%.6f",
        help="0으로 두고 매입 금액을 입력하면 수량이 자동 계산됩니다."
    )
    new_invest_amount = st.number_input(
        "매입 금액 ($) (소수점 가능, 초기값: 0)",
        min_value=0.0,
        value=0.0,
        step=10.0,
        format="%.2f",
        help="투자할 금액을 입력하면 매수가격으로 나누어 수량이 자동 계산됩니다."
    )
    new_custom_price = st.number_input(
        "매수가격 ($) (0이면 매수일 종가 자동 반영)",
        min_value=0.0,
        value=0.0,
        step=1.0,
        format="%.2f",
        help="0으로 입력하면 매수일의 실제 종가가 매수가격으로 적용됩니다."
    )
    submit_button = st.form_submit_button(label="포트폴리오에 추가")

    if submit_button:
        if not new_ticker:
            st.sidebar.error("티커를 입력해주세요.")
        else:
            with st.spinner(f"{new_ticker} 시세 조회 및 계산 중..."):
                resolved = resolve_shares_and_price(
                    ticker=new_ticker,
                    buy_date=new_buy_date,
                    input_shares=float(new_shares),
                    input_invest_amt=float(new_invest_amount),
                    input_custom_price=float(new_custom_price)
                )

            if resolved.get("error"):
                st.sidebar.error(resolved["error"])
            else:
                st.session_state.last_buy_date = new_buy_date
                st.session_state.portfolios[st.session_state.current_portfolio_name].append({
                    "ticker": new_ticker,
                    "buy_date": new_buy_date,
                    "shares": resolved["shares"],
                    "custom_buy_price": resolved["buy_price"],
                    "invest_amount": resolved["invest_amt"]
                })
                save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                st.sidebar.success(
                    f"✅ [{new_ticker}] 추가 완료!  \n"
                    f"• 매수일: {new_buy_date}  \n"
                    f"• 매수가격: ${resolved['buy_price']:,.2f}  \n"
                    f"• 매입금액: ${resolved['invest_amt']:,.2f}  \n"
                    f"• 계산된 수량: {format_shares(resolved['shares'])}주"
                )
                st.rerun()

st.sidebar.markdown("---")

# -----------------------------------------------------------------------------
# 사이드바: 3. 실시간 익절 전략 모드 및 시뮬레이션 설정 (패널 위치 하단으로 이동!)
# -----------------------------------------------------------------------------
st.sidebar.subheader(f"⚙️ [{st.session_state.current_portfolio_name}] 전략 설정")

curr_p_name = st.session_state.current_portfolio_name
if curr_p_name not in st.session_state.portfolio_settings:
    st.session_state.portfolio_settings[curr_p_name] = DEFAULT_SETTINGS.copy()

cur_settings = st.session_state.portfolio_settings[curr_p_name]

# 공통 손절 / 익절선 입력
col_sl, col_tp = st.sidebar.columns(2)
with col_sl:
    new_sl = st.number_input(
        "손절선 (%)",
        value=float(cur_settings.get("stop_loss_pct", -5.0)),
        step=0.5,
        format="%.1f",
        key=f"sl_input_{curr_p_name}"
    )
with col_tp:
    new_tp = st.number_input(
        "익절선 (%)",
        value=float(cur_settings.get("take_profit_pct", 15.0)),
        step=0.5,
        format="%.1f",
        key=f"tp_input_{curr_p_name}"
    )

# 익절 전략 모드 옵션 (기본값: 모드 1)
mode_options = [
    "모드 1: 목표가 도달 시 즉시 익절",
    "모드 2: 최고가 추적 트레일링",
    "모드 3: 직전 목표가 기준 방어선 상향"
]

stored_mode = cur_settings.get("exit_mode", mode_options[0])
if stored_mode not in mode_options:
    stored_mode = mode_options[0]

cur_mode_idx = mode_options.index(stored_mode)

selected_mode = st.sidebar.radio(
    "🎯 익절 관리 모드 선택",
    options=mode_options,
    index=cur_mode_idx,
    key=f"radio_exit_mode_{curr_p_name}",
    help="익절을 결정하는 전략 모드를 실시간으로 변경합니다."
)

m2_drop_val = float(cur_settings.get("mode2_drop_pct", -5.0))
m3_up_val = float(cur_settings.get("mode3_step_up", 10.0))
m3_drop_val = float(cur_settings.get("mode3_drop_pct", -5.0))

if "모드 1" in selected_mode:
    st.sidebar.caption("💡 설정된 익절선에 도달하는 즉시 전량 매도하고 시뮬레이션을 종료합니다.")

elif "모드 2" in selected_mode:
    st.sidebar.caption("💡 익절선 도달 후 기록한 '장중 최고가'에서 지정 비율 하락 시 매도합니다.")
    m2_drop_val = st.sidebar.number_input(
        "최고가 대비 매도선 (-%)",
        value=m2_drop_val,
        step=0.5,
        format="%.1f",
        key=f"m2_drop_input_{curr_p_name}"
    )

elif "모드 3" in selected_mode:
    st.sidebar.caption("💡 목표가를 깰 때마다 직전 목표가 -X%로 방어선을 끌어올리며, 매도가 미도달 시 계속 보유합니다.")
    m3_drop_val = st.sidebar.number_input(
        "직전목표가 대비 (-%)",
        value=m3_drop_val,
        step=0.5,
        format="%.1f",
        key=f"m3_drop_input_{curr_p_name}"
    )
    m3_up_val = st.sidebar.number_input(
        "추가 목표 (+%)",
        value=m3_up_val,
        step=1.0,
        format="%.1f",
        key=f"m3_up_input_{curr_p_name}"
    )

# 기본 전략 초기화 버튼
if st.sidebar.button("🔄 기본 전략(모드 1)으로 초기화", key=f"reset_settings_{curr_p_name}"):
    st.session_state.portfolio_settings[curr_p_name] = DEFAULT_SETTINGS.copy()
    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
    st.rerun()

# 설정값 업데이트 및 자동 저장
updated_settings = {
    "stop_loss_pct": new_sl,
    "take_profit_pct": new_tp,
    "exit_mode": selected_mode,
    "mode2_drop_pct": m2_drop_val,
    "mode3_step_up": m3_up_val,
    "mode3_drop_pct": m3_drop_val,
}

if updated_settings != cur_settings:
    st.session_state.portfolio_settings[curr_p_name] = updated_settings
    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
    st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🗑️ 현재 포트폴리오 종목 전체 비우기"):
    st.session_state.portfolios[st.session_state.current_portfolio_name] = []
    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
    st.rerun()

if st.sidebar.button("🛑 프로그램 및 서버 완전 종료", help="웹 서버와 백그라운드 cmd 창을 즉시 종료합니다.", type="secondary"):
    st.sidebar.warning("프로그램과 서버 프로세스를 종료합니다. 잠시 후 창을 닫아주세요.")
    time.sleep(1)
    os._exit(0)


# -----------------------------------------------------------------------------
# 메인 화면: 대시보드 타이틀 및 실시간 데이터 시뮬레이션
# -----------------------------------------------------------------------------
st.title(f"📊 미국주식 포트폴리오 시뮬레이터: [{st.session_state.current_portfolio_name}]")
st.markdown(
    f"현재 적용 모드: <span class='mode-badge'>{updated_settings['exit_mode']}</span> | "
    f"손절선: **{updated_settings['stop_loss_pct']}%** | 익절선: **+{updated_settings['take_profit_pct']}%**",
    unsafe_allow_html=True
)

current_items = st.session_state.portfolios[st.session_state.current_portfolio_name]

if not current_items:
    st.info(f"현재 '{st.session_state.current_portfolio_name}'에 등록된 종목이 없습니다. 왼쪽 사이드바에서 종목을 추가해보세요.")
    tab_manage_only = st.tabs(["💾 포트폴리오 관리 (저장 / 불러오기 / 다중 관리)"])[0]
    with tab_manage_only:
        st.subheader("📁 포트폴리오 다중 관리 및 백업/불러오기")
        up_file = st.file_uploader("📂 포트폴리오 JSON 백업 파일 불러오기", type=["json"], key="empty_uploader")
        if up_file is not None:
            try:
                uploaded_content = up_file.read().decode("utf-8")
                loaded_dict, loaded_settings = deserialize_portfolios(uploaded_content)
                if loaded_dict:
                    st.session_state.portfolios.update(loaded_dict)
                    if loaded_settings:
                        st.session_state.portfolio_settings.update(loaded_settings)
                    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                    st.success(f"성공적으로 {len(loaded_dict)}개의 포트폴리오를 불러왔습니다!")
                    st.rerun()
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
    st.stop()

# 실시간 시뮬레이션 실행 (선택된 모드 즉시 적용)
with st.spinner("미국 주식 실시간 및 시계열 데이터를 분석 중입니다..."):
    results = [
        simulate_position(item, updated_settings)
        for item in current_items
    ]

# -----------------------------------------------------------------------------
# 포트폴리오 종합 통계 계산
# -----------------------------------------------------------------------------
total_invested = sum(r["invested_amt"] for r in results)
total_final_val = sum(r["final_value"] for r in results)
total_pnl = total_final_val - total_invested
total_return_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

exited_items = [r for r in results if ("손절" in r["status"] or "익절" in r["status"])]
exited_invested = sum(r["invested_amt"] for r in exited_items)
exited_final_val = sum(r["final_value"] for r in exited_items)
exited_pnl = exited_final_val - exited_invested
exited_return_pct = (exited_pnl / exited_invested * 100) if exited_invested > 0 else 0.0

holding_items = [r for r in results if "보유" in r["status"]]
holding_invested = sum(r["invested_amt"] for r in holding_items)
holding_final_val = sum(r["final_value"] for r in holding_items)
holding_pnl = holding_final_val - holding_invested
holding_return_pct = (holding_pnl / holding_invested * 100) if holding_invested > 0 else 0.0

# -----------------------------------------------------------------------------
# 상단 핵심 메트릭 카드
# -----------------------------------------------------------------------------
m_col1, m_col2, m_col3, m_col4 = st.columns(4)

with m_col1:
    st.metric(
        label="💼 총 투자 금액",
        value=f"${total_invested:,.2f}"
    )

with m_col2:
    st.metric(
        label="💰 최종 평가/실현 금액",
        value=f"${total_final_val:,.2f}",
        delta=f"${total_pnl:+,.2f}"
    )

with m_col3:
    st.metric(
        label="📈 포트폴리오 전체 수익률",
        value=f"{total_return_pct:+.2f}%",
        delta=f"{total_return_pct:+.2f}%"
    )

with m_col4:
    st.metric(
        label="🎯 손절/익절 완료 실현수익률",
        value=f"{exited_return_pct:+.2f}%" if exited_items else "N/A",
        delta=f"완료 {len(exited_items)}건 / 보유 {len(holding_items)}건"
    )

st.markdown("---")

# -----------------------------------------------------------------------------
# 탭 구성: 목록 / 시각화 차트 / 종목 수정 / 포트폴리오 관리
# -----------------------------------------------------------------------------
tab_table, tab_chart, tab_edit, tab_manage = st.tabs([
    "📋 포트폴리오 현황",
    "📉 종목별 주가 추이 차트",
    "✏️ 종목 수정 / 삭제",
    "💾 포트폴리오 관리 (저장 / 불러오기 / 다중 관리)"
])

# -----------------------------------------------------------------------------
# 탭 1: 포트폴리오 현황
# -----------------------------------------------------------------------------
with tab_table:
    table_rows = []
    for idx, r in enumerate(results, start=1):
        status_label = r["status"]
        if "익절" in status_label:
            status_display = f"🟢 {status_label}"
        elif "손절" in status_label:
            status_display = f"🔴 {status_label}"
        elif "보유" in status_label:
            status_display = f"🔵 {status_label}"
        else:
            status_display = "⚠️ 오류"

        table_rows.append({
            "번호": idx,
            "상태": status_display,
            "티커": r["ticker"],
            "매수일": r["buy_date"],
            "매수가 ($)": f"${r['buy_price']:,.2f}",
            "수량": f"{format_shares(r['shares'])}주",
            "현재가 ($)": f"${r['current_price']:,.2f}",
            "청산가 ($)": f"${r['exit_price']:,.2f}" if r["exit_date"] != "-" else "-",
            "수익률 (%)": f"{r['return_pct']:+.2f}%",
            "청산일": r["exit_date"],
            "투자금 ($)": f"${r['invested_amt']:,.2f}",
            "손익금 ($)": f"${r['pnl']:+,.2f}",
        })

    df_display = pd.DataFrame(table_rows)
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.caption("💡 사이드바에서 **익절 관리 모드**나 파라미터를 변경하시면 위 표와 수익률이 실시간으로 즉시 다시 계산됩니다.")

    st.markdown("#### 💡 세부 그룹별 수익률 요약")
    sub_col1, sub_col2 = st.columns(2)
    with sub_col1:
        st.info(
            f"**[손절 / 익절 완료 종목 합계]**  \n"
            f"• 대상 종목 수: **{len(exited_items)}개**  \n"
            f"• 총 투자 원금: **${exited_invested:,.2f}**  \n"
            f"• 총 실현 손익: **${exited_pnl:+,.2f}**  \n"
            f"• 실현 총 수익률: **{exited_return_pct:+.2f}%**"
        )
    with sub_col2:
        st.success(
            f"**[현재 보유 중인 종목 합계]**  \n"
            f"• 대상 종목 수: **{len(holding_items)}개**  \n"
            f"• 총 투자 원금: **${holding_invested:,.2f}**  \n"
            f"• 평가 손익: **${holding_pnl:+,.2f}**  \n"
            f"• 미실현 수익률: **{holding_return_pct:+.2f}%**"
        )

# -----------------------------------------------------------------------------
# 탭 2: 종목별 주가 추이 차트
# -----------------------------------------------------------------------------
with tab_chart:
    st.subheader("📊 종목별 주가 궤적 및 익절/손절 시점 분석")
    valid_results = [r for r in results if r["history_df"] is not None and not r["history_df"].empty]

    if not valid_results:
        st.warning("차트를 표시할 수 있는 유효한 주가 데이터가 없습니다.")
    else:
        selected_ticker = st.selectbox(
            "분석할 종목을 선택하세요:",
            options=[r["ticker"] for r in valid_results]
        )
        selected_data = next(r for r in valid_results if r["ticker"] == selected_ticker)
        df_hist = selected_data["history_df"].copy()
        b_price = selected_data["buy_price"]
        sl_price = b_price * (1 + updated_settings["stop_loss_pct"] / 100)
        tp_price = b_price * (1 + updated_settings["take_profit_pct"] / 100)

        fig = go.Figure()

        # 일별 종가 라인
        fig.add_trace(go.Scatter(
            x=df_hist["Date"],
            y=df_hist["Close"],
            mode="lines",
            name="일별 종가 (Close)",
            line=dict(color="#1f77b4", width=2.5)
        ))

        # 매수가 기준선
        fig.add_hline(
            y=b_price,
            line_dash="dash",
            line_color="#6c757d",
            annotation_text=f"매수가: ${b_price:.2f}",
            annotation_position="top left"
        )

        # 익절선 (+15%)
        fig.add_hline(
            y=tp_price,
            line_dash="dot",
            line_color="#28a745",
            annotation_text=f"익절선 (+{updated_settings['take_profit_pct']}%): ${tp_price:.2f}",
            annotation_position="top left"
        )

        # 손절선 (-5%)
        fig.add_hline(
            y=sl_price,
            line_dash="dot",
            line_color="#dc3545",
            annotation_text=f"손절선 ({updated_settings['stop_loss_pct']}%): ${sl_price:.2f}",
            annotation_position="bottom left"
        )

        # 청산 마커
        if selected_data["exit_date"] != "-":
            marker_color = "#dc3545" if "손절" in selected_data["status"] else "#28a745"
            marker_symbol = "x" if "손절" in selected_data["status"] else "star"
            exit_d = datetime.datetime.strptime(selected_data["exit_date"], "%Y-%m-%d").date()

            fig.add_trace(go.Scatter(
                x=[exit_d],
                y=[selected_data["exit_price"]],
                mode="markers+text",
                name=f"{selected_data['status']}",
                text=[f"{selected_data['status']} ({selected_data['return_pct']:+.1f}%)"],
                textposition="top center",
                marker=dict(size=14, color=marker_color, symbol=marker_symbol)
            ))

        fig.update_layout(
            title=f"{selected_ticker} 주가 흐름 분석 [{updated_settings['exit_mode']}] (상태: {selected_data['status']})",
            xaxis_title="날짜",
            yaxis_title="주가 (USD)",
            hovermode="x unified",
            template="plotly_white",
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 탭 3: 종목 수정 / 삭제
# -----------------------------------------------------------------------------
with tab_edit:
    st.subheader(f"✏️ [{st.session_state.current_portfolio_name}] 종목 내용 변경 및 개별 삭제")
    st.caption("수정할 종목의 아코디언을 클릭하여 열고, 수량 또는 매입금액, 매수가격을 변경한 뒤 **[💾 수정사항 적용]**을 누르세요.")

    for idx, item in enumerate(current_items):
        t_val = str(item["ticker"]).strip().upper()
        b_val = item["buy_date"]
        if isinstance(b_val, str):
            try:
                b_val = datetime.datetime.strptime(b_val, "%Y-%m-%d").date()
            except Exception:
                b_val = datetime.date.today()
        s_val = float(item.get("shares", 0.0))
        p_val = float(item["custom_buy_price"]) if item.get("custom_buy_price") else 0.0
        inv_val = float(item["invest_amount"]) if item.get("invest_amount") else (s_val * p_val if p_val > 0 else 0.0)

        with st.expander(f"📌 [{idx + 1}] {t_val} (매수일: {b_val}, {format_shares(s_val)}주)", expanded=False):
            with st.form(key=f"edit_form_{idx}"):
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    edit_ticker = st.text_input("티커", value=t_val, key=f"et_{idx}").strip().upper()
                    edit_buy_date = st.date_input(
                        "매수일",
                        value=b_val,
                        max_value=datetime.date.today(),
                        key=f"ed_{idx}"
                    )
                    edit_shares = st.number_input(
                        "매수 수량 (주)",
                        min_value=0.0,
                        value=s_val,
                        step=0.000001,
                        format="%.6f",
                        key=f"es_{idx}",
                        help="0으로 두고 매입 금액을 입력하면 수량이 자동 계산됩니다."
                    )
                with col_e2:
                    edit_invest_amt = st.number_input(
                        "매입 금액 ($) (소수점 가능)",
                        min_value=0.0,
                        value=inv_val,
                        step=10.0,
                        format="%.2f",
                        key=f"einv_{idx}",
                        help="0으로 둘 경우 수량 또는 5번 조건이 적용됩니다."
                    )
                    edit_price = st.number_input(
                        "매수가격 ($) (0이면 매수일 종가 자동 적용)",
                        min_value=0.0,
                        value=p_val,
                        step=1.0,
                        format="%.2f",
                        key=f"ep_{idx}"
                    )

                btn_save = st.form_submit_button("💾 수정사항 적용")

                if btn_save:
                    if not edit_ticker:
                        st.error("티커를 입력해주세요.")
                    else:
                        with st.spinner(f"{edit_ticker} 시세 조회 및 계산 중..."):
                            resolved = resolve_shares_and_price(
                                ticker=edit_ticker,
                                buy_date=edit_buy_date,
                                input_shares=float(edit_shares),
                                input_invest_amt=float(edit_invest_amt),
                                input_custom_price=float(edit_price)
                            )
                        if resolved.get("error"):
                            st.error(resolved["error"])
                        else:
                            st.session_state.portfolios[st.session_state.current_portfolio_name][idx] = {
                                "ticker": edit_ticker.strip().upper(),
                                "buy_date": edit_buy_date,
                                "shares": resolved["shares"],
                                "custom_buy_price": resolved["buy_price"],
                                "invest_amount": resolved["invest_amt"]
                            }
                            save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                            st.success(f"[{edit_ticker}] 수정 완료! (매수가: ${resolved['buy_price']:,.2f}, 수량: {format_shares(resolved['shares'])}주)")
                            st.rerun()

            if st.button(f"🗑️ [{t_val}] 종목 삭제", key=f"del_{idx}"):
                st.session_state.portfolios[st.session_state.current_portfolio_name].pop(idx)
                save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                st.rerun()

# -----------------------------------------------------------------------------
# 탭 4: 포트폴리오 관리 (다중 관리 & 저장/불러오기)
# -----------------------------------------------------------------------------
with tab_manage:
    st.subheader("📂 다중 포트폴리오 관리")
    
    m_col_left, m_col_right = st.columns(2)

    with m_col_left:
        st.markdown("##### ➕ 새 포트폴리오 만들기")
        with st.form("create_portfolio_form", clear_on_submit=True):
            new_p_name = st.text_input("새 포트폴리오 이름", placeholder="예: 성장주 전략").strip()
            create_btn = st.form_submit_button("포트폴리오 생성")
            if create_btn:
                if not new_p_name:
                    st.error("포트폴리오 이름을 입력해주세요.")
                elif new_p_name in st.session_state.portfolios:
                    st.error("이미 같은 이름의 포트폴리오가 존재합니다.")
                else:
                    st.session_state.portfolios[new_p_name] = []
                    st.session_state.portfolio_settings[new_p_name] = DEFAULT_SETTINGS.copy()
                    st.session_state.current_portfolio_name = new_p_name
                    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                    st.success(f"'{new_p_name}' 포트폴리오가 생성되었습니다!")
                    st.rerun()

        st.markdown("##### 🏷️ 현재 포트폴리오 이름 변경")
        with st.form("rename_portfolio_form"):
            rename_input = st.text_input("새 이름", value=st.session_state.current_portfolio_name).strip()
            rename_btn = st.form_submit_button("이름 변경 적용")
            if rename_btn:
                if not rename_input:
                    st.error("변경할 이름을 입력해주세요.")
                elif rename_input == st.session_state.current_portfolio_name:
                    st.info("이름이 이전과 동일합니다.")
                elif rename_input in st.session_state.portfolios:
                    st.error("이미 존재하는 이름입니다.")
                else:
                    old_name = st.session_state.current_portfolio_name
                    st.session_state.portfolios[rename_input] = st.session_state.portfolios.pop(old_name)
                    st.session_state.portfolio_settings[rename_input] = st.session_state.portfolio_settings.pop(old_name, DEFAULT_SETTINGS.copy())
                    st.session_state.current_portfolio_name = rename_input
                    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                    st.success(f"'{old_name}' → '{rename_input}' 변경 완료!")
                    st.rerun()

    with m_col_right:
        st.markdown("##### 📋 현재 포트폴리오 복제 (Clone)")
        with st.form("clone_portfolio_form", clear_on_submit=True):
            clone_name_input = st.text_input("복제본 포트폴리오 이름", value=f"{st.session_state.current_portfolio_name}_사본").strip()
            clone_btn = st.form_submit_button("복제본 생성")
            if clone_btn:
                if not clone_name_input:
                    st.error("복제본 이름을 입력해주세요.")
                elif clone_name_input in st.session_state.portfolios:
                    st.error("이미 존재하는 이름입니다.")
                else:
                    import copy
                    st.session_state.portfolios[clone_name_input] = copy.deepcopy(
                        st.session_state.portfolios[st.session_state.current_portfolio_name]
                    )
                    st.session_state.portfolio_settings[clone_name_input] = copy.deepcopy(
                        st.session_state.portfolio_settings.get(st.session_state.current_portfolio_name, DEFAULT_SETTINGS.copy())
                    )
                    st.session_state.current_portfolio_name = clone_name_input
                    save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                    st.success(f"'{clone_name_input}' 복제 완료!")
                    st.rerun()

        st.markdown("##### 🗑️ 현재 포트폴리오 삭제")
        st.warning(f"현재 선택된 **[{st.session_state.current_portfolio_name}]** 및 포함된 모든 종목을 삭제합니다.")
        if st.button("🚨 현재 포트폴리오 완전히 삭제", type="primary"):
            if len(st.session_state.portfolios) <= 1:
                st.error("최소 1개의 포트폴리오는 유지되어야 하므로 삭제할 수 없습니다.")
            else:
                del_target = st.session_state.current_portfolio_name
                st.session_state.portfolios.pop(del_target)
                st.session_state.portfolio_settings.pop(del_target, None)
                st.session_state.current_portfolio_name = list(st.session_state.portfolios.keys())[0]
                save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                st.success(f"'{del_target}' 포트폴리오가 삭제되었습니다.")
                st.rerun()

    st.markdown("---")

    # 2. 포트폴리오 저장(백업) 및 불러오기(복원)
    st.subheader("💾 포트폴리오 파일 저장 및 불러오기 (JSON 백업)")

    save_col, load_col = st.columns(2)

    with save_col:
        st.markdown("##### 📥 포트폴리오 파일로 내보내기 (저장)")
        st.write("모든 포트폴리오 데이터와 전략 설정을 JSON 파일로 다운로드합니다.")

        all_json_data = serialize_portfolios(st.session_state.portfolios, st.session_state.portfolio_settings)
        today_str = datetime.date.today().strftime('%Y%m%d')

        st.download_button(
            label="💾 전체 포트폴리오 모음 다운로드 (JSON)",
            data=all_json_data,
            file_name=f"all_portfolios_backup_{today_str}.json",
            mime="application/json",
            help="등록된 모든 포트폴리오와 전략 설정이 포함된 백업 파일입니다."
        )

        curr_only_json = serialize_portfolios(
            {st.session_state.current_portfolio_name: st.session_state.portfolios[st.session_state.current_portfolio_name]},
            {st.session_state.current_portfolio_name: st.session_state.portfolio_settings.get(st.session_state.current_portfolio_name, DEFAULT_SETTINGS)}
        )
        st.download_button(
            label=f"💾 [{st.session_state.current_portfolio_name}]만 다운로드 (JSON)",
            data=curr_only_json,
            file_name=f"portfolio_{st.session_state.current_portfolio_name}_{today_str}.json",
            mime="application/json"
        )

        st.markdown("##### 📊 시뮬레이션 결과 표 다운로드 (CSV)")
        csv_data = pd.DataFrame([
            {
                "번호": idx,
                "Ticker": r["ticker"],
                "Status": r["status"],
                "BuyDate": r["buy_date"],
                "BuyPrice": r["buy_price"],
                "Shares": r["shares"],
                "CurrentPrice": r["current_price"],
                "ExitDate": r["exit_date"],
                "ExitPrice": r["exit_price"],
                "ReturnPct": r["return_pct"],
                "InvestedAmount": r["invested_amt"],
                "FinalValue": r["final_value"],
                "PnL": r["pnl"]
            } for idx, r in enumerate(results, start=1)
        ]).to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            label="📄 시뮬레이션 결과 CSV 다운로드",
            data=csv_data,
            file_name=f"simulation_{st.session_state.current_portfolio_name}_{today_str}.csv",
            mime="text/csv"
        )

    with load_col:
        st.markdown("##### 📤 포트폴리오 파일 불러오기 (복원)")
        st.write("이전에 저장해둔 JSON 백업 파일을 업로드하여 포트폴리오를 복원합니다.")

        uploaded_file = st.file_uploader("JSON 파일 선택", type=["json"])
        import_mode = st.radio(
            "불러오기 방식",
            options=["기존 포트폴리오에 추가 / 병합 (추천)", "기존 데이터를 모두 지우고 완전히 덮어쓰기"],
            index=0
        )

        if uploaded_file is not None:
            if st.button("📂 파일 데이터 불러오기 적용", type="primary"):
                try:
                    raw_content = uploaded_file.read().decode("utf-8")
                    imported_dict, imported_settings = deserialize_portfolios(raw_content)

                    if not imported_dict:
                        st.error("유효한 포트폴리오 데이터가 없습니다.")
                    else:
                        if import_mode == "기존 데이터를 모두 지우고 완전히 덮어쓰기":
                            st.session_state.portfolios = imported_dict
                            st.session_state.portfolio_settings = imported_settings
                            st.session_state.current_portfolio_name = list(imported_dict.keys())[0]
                        else:
                            for p_k, p_v in imported_dict.items():
                                if p_k in st.session_state.portfolios:
                                    alt_k = f"{p_k}_가져옴"
                                    st.session_state.portfolios[alt_k] = p_v
                                    st.session_state.portfolio_settings[alt_k] = imported_settings.get(p_k, DEFAULT_SETTINGS.copy())
                                else:
                                    st.session_state.portfolios[p_k] = p_v
                                    st.session_state.portfolio_settings[p_k] = imported_settings.get(p_k, DEFAULT_SETTINGS.copy())
                            st.session_state.current_portfolio_name = list(imported_dict.keys())[0]

                        save_to_disk(st.session_state.portfolios, st.session_state.portfolio_settings)
                        st.success("포트폴리오와 전략 설정을 성공적으로 불러왔습니다!")
                        st.rerun()
                except Exception as ex:
                    st.error(f"파일을 파싱하는 중 오류가 발생했습니다: {ex}")