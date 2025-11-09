import io
import math
import requests
import pandas as pd
import numpy as np
from datetime import datetime

from flask import Flask, Response, render_template

import matplotlib
matplotlib.use("Agg")  # Flask 서버에서 그림만 그릴 거라 GUI backend 필요 없음
import matplotlib.pyplot as plt

import metpy.calc as mpcalc
from metpy.plots import SkewT
from metpy.units import units

# ==========================
# 1) 여기에 본인 ZONDE API URL 넣기
#    (노트북에서 쓰던 url 그대로 가져오되 authKey는 본인 키로 교체)
# ==========================
ZONDE_URL = (
    "https://apihub.kma.go.kr/api/typ01/url/upp_temp.php"
    "?stn=47102&pa=0&help=1&authKey=Pm148yhLTsOtePMoS77DcA"
)

app = Flask(__name__)


def fetch_sounding():
    """
    KMA ZONDE API에서 raw 텍스트 데이터를 받아서
    pandas DataFrame + MetPy 단위가 붙은 배열(p, t, td)로 변환.
    """
    # API 호출
    resp = requests.get(ZONDE_URL, timeout=10)

    # 기상청 텍스트가 EUC-KR인 경우가 많아서 인코딩 지정
    resp.encoding = "euc-kr"

    text = resp.text

    # 주석(#)으로 시작하는 줄은 자동으로 무시하게 설정
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

    # 날짜 컬럼 파싱 (YYMMDDHHMI)
    df["datetime"] = pd.to_datetime(df["YYMMDDHHMI"], format="%Y%m%d%H%M")

    # 압력 기준으로 정렬 (보통 높은 압력 -> 낮은 압력 순)
    df = df.sort_values("PA", ascending=False)

    # MetPy 단위 붙이기
    p = df["PA"].values * units.hPa
    t = df["TA"].values * units.degC
    td = df["TD"].values * units.degC

    # 관측 시각 (맨 아래나 맨 위 아무 거 하나 쓰면 됨)
    obs_time = df["datetime"].iloc[0]

    return df, p, t, td, obs_time


def create_skewt_figure(p, t, td, obs_time):
    """
    MetPy SkewT로 단열선도 그리는 함수.
    """
    # 기단(덩이공기) 온도 프로파일
    prof = mpcalc.parcel_profile(p, t[0], td[0]).to("degC")

    fig = plt.figure(figsize=(6, 9))
    skew = SkewT(fig, rotation=45)

    # 관측 온도 / 이슬점 / 기단 궤적
    skew.plot(p, t, "r", linewidth=1, label="Temperature")
    skew.plot(p, td, "g", linewidth=1, linestyle="dashed", label="Dewpoint")
    skew.plot(p, prof, "k", linewidth=1, linestyle="dashed", label="Parcel")

    # 배경선 (건조 / 습윤 단열선, 혼합비선)
    skew.plot_dry_adiabats()
    skew.plot_moist_adiabats()
    skew.plot_mixing_lines()

    # CAPE / CIN 음영 (있으면)
    try:
        cape, cin = mpcalc.cape_cin(p, t, td, prof)
        # 그냥 잘 그려지면 음영 칠해주고, 에러나면 패스
        skew.shade_cape(p, t, prof, alpha=0.2)
        skew.shade_cin(p, t, prof, alpha=0.2)
        cape_val = float(cape.m)
        cin_val = float(cin.m)
    except Exception:
        cape_val = math.nan
        cin_val = math.nan

    # 축 범위 / 라벨 등
    skew.ax.set_ylim(1050, 100)   # hPa
    skew.ax.set_xlim(-40, 40)     # °C
    skew.ax.set_xlabel("Temperature (°C)")
    skew.ax.set_ylabel("Pressure (hPa)")

    title_main = "Skew-T Log-P Diagram"
    title_sub = obs_time.strftime("(%Y-%m-%d %H:%M KST)")
    skew.ax.set_title(f"{title_main}\n{title_sub}", loc="center", fontsize=11)

    # 범례
    skew.ax.legend(loc="best", fontsize=9)

    # CAPE/CIN 값 텍스트로 오른쪽 위에 살짝 표시
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


@app.route("/")
def index():
    # templates/index.html 렌더링
    return render_template("index.html")


@app.route("/skewt.png")
def skewt_png():
    """
    이 URL로 접근하면 최신 ZONDE 데이터를 가져와서
    단열선도 PNG 이미지를 돌려줌.
    """
    df, p, t, td, obs_time = fetch_sounding()
    fig = create_skewt_figure(p, t, td, obs_time)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")


if __name__ == "__main__":
    # 개발용 실행
    app.run(host="0.0.0.0", port=5000, debug=True)
