import math
from io import StringIO

from datetime import datetime

import requests
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # 화면 없는 서버에서 그림만 그릴 때
import matplotlib.pyplot as plt

import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units

import streamlit as st


# ==========================
# 0. Streamlit 기본 설정
# ==========================
st.set_page_config(
    page_title="SASA 상층 관측 단열선도",
    page_icon="🌌",
    layout="centered",
)


# ==========================
# 1. ZONDE API 키 / URL 설정
# ==========================
# 🔐 권장: Streamlit Cloud에서 Secrets에 ZONDE_AUTH_KEY 저장하고 쓰기
#   - App settings → Secrets → 아래처럼 입력
#       ZONDE_AUTH_KEY=여기_네_API키
#
# 아래 코드는:
#   1) st.secrets에 키가 있으면 그걸 쓰고
#   2) 없으면 "YOUR_AUTH_KEY_HERE"라는 더미 문자열을 쓴다.
ZONDE_AUTH_KEY = st.secrets.get("ZONDE_AUTH_KEY", "YOUR_AUTH_KEY_HERE")

# ✅ 여기 stn, pa, help 값은 노트북에서 잘 되던 URL이랑 맞추는 게 제일 안전함
ZONDE_URL = (
    "https://apihub.kma.go.kr/api/typ01/url/upp_temp.php"
    f"?stn=47102&pa=0&help=1&authKey={ZONDE_AUTH_KEY}"
)


# ==========================
# 2. 상층관측 데이터 불러오기
# ==========================
def fetch_sounding():
    """
    KMA ZONDE API에서 상층관측(raw 텍스트) 데이터를 가져와서
    pandas DataFrame과 (p, t, td, obs_time)을 반환.

    실패하면 ValueError를 던진다.
    """
    # --- HTTP 요청 ---
    try:
        resp = requests.get(ZONDE_URL, timeout=10)
    except Exception as e:
        raise ValueError(f"ZONDE API에 연결할 수 없습니다: {e}")

    # --- HTTP 상태 코드 체크 ---
    if resp.status_code != 200:
        raise ValueError(f"ZONDE API HTTP 에러: {resp.status_code}")

    # --- 인코딩 설정 ---
    # 기상청 텍스트는 보통 euc-kr
    resp.encoding = "euc-kr"
    text = resp.text

    # --- 응답 내용 대략적인 체크 (인증/에러 메세지) ---
    low = text.lower()
    if "auth" in low or "인증" in text:
        raise ValueError("ZONDE API 인증 오류 가능성(authKey 확인 필요).")
    if "not found" in low or "404" in low:
        raise ValueError("ZONDE API에서 자료를 찾지 못했습니다(URL / 파라미터 확인).")

    buf = StringIO(text)

    # --- CSV 모양으로 파싱 시도 ---
    try:
        df = pd.read_csv(
            buf,
            delim_whitespace=True,
            comment="#",
            header=None,
            names=["YYMMDDHHMI", "STN", "PA", "GH", "TA", "TD", "WD", "WS", "FLAG"],
            na_values=-999.0,
        )
    except Exception as e:
        raise ValueError("ZONDE 응답 텍스트를 표 형식으로 파싱하지 못했습니다.") from e

    # --- 필수 컬럼의 결측 제거 ---
    df = df.dropna(subset=["PA", "TA", "TD"])

    # 👉 여기서 df가 비었는지 먼저 확인
    if df.empty:
        raise ValueError(
            "상층관측 데이터가 비어 있습니다(0행). "
            "· authKey, stn, pa 파라미터 또는 응답 형식을 확인하세요."
        )

    # --- 날짜/시간 파싱 ---
    try:
        df["datetime"] = pd.to_datetime(df["YYMMDDHHMI"], format="%Y%m%d%H%M")
    except Exception as e:
        raise ValueError("YYMMDDHHMI를 날짜/시간으로 변환하는 데 실패했습니다.") from e

    # --- 압력 큰 순(지상) → 작은 순(상층) ---
    df = df.sort_values("PA", ascending=False)

    # --- 단위 붙이기 ---
    p = df["PA"].values * units.hPa
    t = df["TA"].values * units.degC
    td = df["TD"].values * units.degC

    # --- 관측 시각 (첫 행) ---
    try:
        obs_time = df["datetime"].iloc[0]
    except IndexError as e:
        # 이론상 여기 올 일은 거의 없지만, 안전하게 한 번 더 방어
        raise ValueError("datetime 컬럼에서 관측 시각을 읽지 못했습니다.") from e

    return df, p, t, td, obs_time


# ==========================
# 3. Skew-T 그림 생성
# ==========================
def create_skewt_figure(p, t, td, obs_time):
    """
    MetPy SkewT로 단열선도를 그리는 함수.
    반환값(fig)을 Streamlit에서 st.pyplot(fig)으로 표시.
    """
    # 기단(parcel) 온도 프로파일
    prof = mpcalc.parcel_profile(p, t[0], td[0]).to("degC")

    fig = plt.figure(figsize=(6, 9))
    skew = SkewT(fig, rotation=45)

    # 관측 온도 / 이슬점 / parcel
    skew.plot(p, t, "r", linewidth=1, label="Temperature")
    skew.plot(p, td, "g", linewidth=1, linestyle="dashed", label="Dewpoint")
    skew.plot(p, prof, "k", linewidth=1, linestyle="dashed", label="Parcel")

    # 배경선 (건조/습윤 단열선, 혼합비선)
    skew.plot_dry_adiabats()
    skew.plot_moist_adiabats()
    skew.plot_mixing_lines()

    # CAPE / CIN 계산 + 음영
    try:
        cape, cin = mpcalc.cape_cin(p, t, td, prof)
        skew.shade_cape(p, t, prof, alpha=0.2)
        skew.shade_cin(p, t, prof, alpha=0.2)
        cape_val = float(cape.m)
        cin_val = float(cin.m)
    except Exception:
        cape_val = math.nan
        cin_val = math.nan

    # 축 / 라벨 설정
    skew.ax.set_ylim(1050, 100)   # hPa
    skew.ax.set_xlim(-40, 40)     # °C
    skew.ax.set_xlabel("Temperature (°C)")
    skew.ax.set_ylabel("Pressure (hPa)")

    title_main = "Skew-T Log-P Diagram"
    title_sub = obs_time.strftime("(%Y-%m-%d %H:%M KST)")
    skew.ax.set_title(f"{title_main}\n{title_sub}", loc="center", fontsize=11)

    # 범례
    skew.ax.legend(loc="best", fontsize=9)

    # CAPE/CIN 간단 텍스트
    text_lines = []
    if not math.isnan(cape_val):
        text_lines.append(f"CAPE: {cape_val:.0f} J/kg")
    if not math.isnan(cin_val):
        text_lines.append(f"CIN: {cin_val:.0f} J/kg")
    if text_lines:
        skew.ax.text(
            0.98,
            0.02,
            "\n".join(text_lines),
            transform=skew.ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            bbox=dict(boxstyle="round", alpha=0.15),
        )

    fig.tight_layout()
    return fig


# ==========================
# 4. Streamlit UI
# ==========================
st.title("SASA 전천 모니터링 시스템")
st.subheader("상층 관측 단열선도 (Skew-T Log-P, KMA ZONDE)")

st.markdown(
    """
기상청 ZONDE 상층관측 자료를 이용해, MetPy로 Skew-T Log-P 단열선도를 그립니다.  
CAPE / CIN, 기온 / 이슬점 / 기단(parcel) 프로파일을 한 번에 확인할 수 있습니다.
"""
)

# 🔄 버튼: 그냥 누르면 페이지 전체가 rerun됨
if st.button("🔄 최신 관측으로 업데이트"):
    st.experimental_rerun()

# 실제 데이터 불러오기 + 그림 그리기
with st.spinner("기상청 상층관측 자료를 불러오는 중입니다..."):
    try:
        df, p, t, td, obs_time = fetch_sounding()
        fig = create_skewt_figure(p, t, td, obs_time)
        st.pyplot(fig)
        st.caption(
            f"관측 시각: {obs_time.strftime('%Y-%m-%d %H:%M KST')} · "
            f"자료 출처: KMA ZONDE API"
        )

        with st.expander("원시 데이터 (상위 10행 미리보기)"):
            st.dataframe(df.head(10))

    except Exception as e:
        st.error("데이터를 불러오거나 그리는 중 오류가 발생했습니다.")
        # 디버깅 위해 상세 에러도 같이 표시 (배포 후에는 빼도 됨)
        st.exception(e)
