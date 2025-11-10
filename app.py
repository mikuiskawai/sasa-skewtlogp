import io
import math
from datetime import datetime

import requests
import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("Agg")  # 화면 없이 그림만 그릴 거라 Agg backend 사용
import matplotlib.pyplot as plt

import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units

import streamlit as st


# ==========================
# 1) 여기 네 ZONDE API URL (authKey는 절대 공개 repo에 그대로 올리지 말고,
#    Streamlit Cloud의 Secrets 기능 쓰는 걸 권장!)
# ==========================
# 가장 안전한 방식:
#   - Streamlit Cloud에서 "Secrets"에 ZONDE_AUTH_KEY 저장
#   - 코드에서는 st.secrets["ZONDE_AUTH_KEY"]로 읽기
#
# 편의상 여기선 그냥 문자열 넣는 형태로 보여줄게.
ZONDE_AUTH_KEY = "여기에_네_API키_임시로"  # 진짜 배포할 땐 secrets로!
ZONDE_URL = (
    "https://apihub.kma.go.kr/api/typ01/url/upp_temp.php"
    f"?stn=47102&pa=0&help=1&authKey={ZONDE_AUTH_KEY}"
)


# ==========================
# 2) ZONDE 데이터 불러오기 함수
# ==========================
def fetch_sounding():
    """
    KMA ZONDE API에서 raw 텍스트 데이터를 받아서
    pandas DataFrame + (p, t, td, obs_time) 반환.
    """
    resp = requests.get(ZONDE_URL, timeout=10)

    # 기상청 텍스트 인코딩 (대부분 euc-kr)
    resp.encoding = "euc-kr"
    text = resp.text

    from io import StringIO
    buf = StringIO(text)

    df = pd.read_csv(
        buf,
        delim_whitespace=True,
        comment="#",
        header=None,
        names=["YYMMDDHHMI", "STN", "PA", "GH", "TA", "TD", "WD", "WS", "FLAG"],
        na_values=-999.0,
    )

    # 결측값 제거
    df = df.dropna(subset=["PA", "TA", "TD"])

    # 날짜 파싱
    df["datetime"] = pd.to_datetime(df["YYMMDDHHMI"], format="%Y%m%d%H%M")

    # 압력 큰(지상에 가까운) 순서 → 작은 순서(높은 고도)
    df = df.sort_values("PA", ascending=False)

    p = df["PA"].values * units.hPa
    t = df["TA"].values * units.degC
    td = df["TD"].values * units.degC

    obs_time = df["datetime"].iloc[0]

    return df, p, t, td, obs_time


# ==========================
# 3) Skew-T 그림 생성 함수
# ==========================
def create_skewt_figure(p, t, td, obs_time):
    """
    MetPy SkewT로 단열선도 그리는 함수.
    Streamlit에서는 fig를 st.pyplot(fig)으로 보여주면 됨.
    """
    # 기단(parcel) 궤적
    prof = mpcalc.parcel_profile(p, t[0], td[0]).to("degC")

    fig = plt.figure(figsize=(6, 9))
    skew = SkewT(fig, rotation=45)

    # 관측 온도 / 이슬점 / parcel
    skew.plot(p, t, "r", linewidth=1, label="Temperature")
    skew.plot(p, td, "g", linewidth=1, linestyle="dashed", label="Dewpoint")
    skew.plot(p, prof, "k", linewidth=1, linestyle="dashed", label="Parcel")

    # 배경선
    skew.plot_dry_adiabats()
    skew.plot_moist_adiabats()
    skew.plot_mixing_lines()

    # CAPE / CIN (있으면) 음영
    try:
        cape, cin = mpcalc.cape_cin(p, t, td, prof)
        skew.shade_cape(p, t, prof, alpha=0.2)
        skew.shade_cin(p, t, prof, alpha=0.2)
        cape_val = float(cape.m)
        cin_val = float(cin.m)
    except Exception:
        cape_val = math.nan
        cin_val = math.nan

    # 축 범위
    skew.ax.set_ylim(1050, 100)   # hPa
    skew.ax.set_xlim(-40, 40)     # °C
    skew.ax.set_xlabel("Temperature (°C)")
    skew.ax.set_ylabel("Pressure (hPa)")

    # 제목
    title_main = "Skew-T Log-P Diagram"
    title_sub = obs_time.strftime("(%Y-%m-%d %H:%M KST)")
    skew.ax.set_title(f"{title_main}\n{title_sub}", loc="center", fontsize=11)

    # 범례
    skew.ax.legend(loc="best", fontsize=9)

    # CAPE/CIN 텍스트
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
# 4) 여기서부터가 "Flask가 아니라 Streamlit" 파트
#    ❗ app = Flask(...) 도, app.run(...) 도 없음
# ==========================

st.set_page_config(
    page_title="SASA 상층 관측 단열선도",
    page_icon="🌌",
    layout="centered",
)

st.title("SASA 전천 모니터링 시스템")
st.subheader("상층 관측 단열선도 (Skew-T Log-P, KMA ZONDE)")

st.markdown(
    """
기상청 ZONDE API에서 상층관측 자료를 받아, MetPy로 단열선도를 그리고 있습니다.  
**CAPE / CIN**, 기온 / 이슬점 / Parcel 프로파일을 한 번에 확인할 수 있습니다.
"""
)

if st.button("🔄 최신 관측으로 업데이트"):
    st.experimental_rerun()

with st.spinner("기상청 상층관측 자료를 불러오는 중입니다..."):
    try:
        df, p, t, td, obs_time = fetch_sounding()
        fig = create_skewt_figure(p, t, td, obs_time)
        st.pyplot(fig)
        st.caption(
            f"관측 시각: {obs_time.strftime('%Y-%m-%d %H:%M KST')} · "
            f"자료 출처: KMA ZONDE API"
        )
    except Exception as e:
        st.error("데이터를 불러오거나 그리는 중 오류가 발생했습니다.")
        st.exception(e)
