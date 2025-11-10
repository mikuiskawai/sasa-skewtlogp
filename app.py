import time
import requests

def fetch_sounding(max_retries=3):
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # connect 5초, read 20초로 분리
            resp = requests.get(ZONDE_URL, timeout=(5, 20))
            break  # 성공하면 루프 탈출
        except requests.exceptions.Timeout as e:
            last_error = e
            # 마지막 시도 아니면 조금 쉬고 다시
            if attempt < max_retries:
                time.sleep(2)
                continue
            else:
                raise ValueError(
                    f"ZONDE API에 연결할 수 없습니다(타임아웃, {max_retries}회 재시도 실패): {e}"
                )
        except Exception as e:
            # 다른 네트워크 에러
            raise ValueError(f"ZONDE API에 연결할 수 없습니다: {e}")
    
    # 여기까지 왔다는 건 resp가 성공적으로 들어온 상태
    if resp.status_code != 200:
        preview = resp.text[:200]
        raise ValueError(
            f"ZONDE API HTTP 에러: {resp.status_code}\n"
            f"응답 내용 일부: {preview}"
        )

    resp.encoding = "euc-kr"
    text = resp.text
    ...
    # 이하 나머지 파싱 코드는 그대로
