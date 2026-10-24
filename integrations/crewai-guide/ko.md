**백그라운드 작업을 위한 로컬 추론 공유:**

대화형 Agent와 자율 Agent가 하나의 로컬 모델 서버를 공유할 때 선택적으로 외부 요청 수락 게이트웨이를 사용하여 대기 중인 요청을 구분할 수 있습니다. [Adaptive Inference v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0)은 하나의 큐에서 `/v1`과 `/background/v1`을 제공합니다. 기존 모델 서버와 품질 설정을 유지하면서 릴리스 지침에 따라 게이트웨이를 별도로 구성하고 시작하세요.

`ADAPTIVE_GATEWAY_ROOT`를 `/v1` 없이 게이트웨이 루트 주소(예: `http://127.0.0.1:18100`)로 설정하세요. 인증을 활성화한 경우 `ADAPTIVE_GATEWAY_KEY`로 키를 제공하세요. `llm-settings.json`에는 기존 `model`, 명시적인 출력 및 추론 한도, 지원되는 `extra_body` 등 검증된 생성 인수를 넣습니다. 라우팅 정보와 자격 증명은 넣지 않습니다.

```python Code
import json
import os
from pathlib import Path

from crewai import LLM

# Keep the existing served model and its verified generation settings.
settings = json.loads(Path("llm-settings.json").read_text(encoding="utf-8"))
reserved = {"base_url", "api_key", "custom_openai", "max_retries"}
if reserved.intersection(settings):
    raise ValueError("Keep gateway routing separate from model settings")
gateway = os.environ["ADAPTIVE_GATEWAY_ROOT"].rstrip("/")
key = os.environ.get("ADAPTIVE_GATEWAY_KEY", "local")

interactive_llm = LLM(
    **settings, custom_openai=True, base_url=gateway + "/v1",
    api_key=key, max_retries=0,
)
background_llm = LLM(
    **settings, custom_openai=True, base_url=gateway + "/background/v1",
    api_key=key, max_retries=0,
)
```

애플리케이션이 정한 역할에 따라 Agent의 `llm`에 `interactive_llm` 또는 `background_llm`을 전달하세요. 이는 호스트가 명시적으로 선택하는 라우팅이며, 프롬프트에서 우선순위를 추론하거나 모든 하위 Agent를 자동으로 분류하지 않습니다. 외부 큐는 한 번에 하나의 업스트림 요청만 허용하므로 서버의 기본 배치 처리량이 줄어들 수 있습니다. 진행 중인 생성을 선점하거나 모델을 언로드하거나 GPU 메모리를 예약할 수 없습니다. 완료 여부가 불명확한 요청의 자동 재시도를 비활성화하고 클라이언트 제한 시간이 큐 대기 및 실행 한도를 포함하도록 설정하세요. Chat Completions를 사용하세요. 이 게이트웨이는 Responses 또는 기본 관리 경로를 제공하지 않습니다.

엔진 간 제어 값을 변환하는 대신 백엔드가 지원하는 필드를 유지하세요. CrewAI의 OpenAI 클라이언트는 함수 스키마를 엄격 모드로 변환하므로 도구와의 적합성을 확인해야 합니다. 구성 및 HTTP 픽스처 검사는 실제 모델 품질이나 리소스 반환을 입증하지 않습니다. [재현 방법 및 호환성 제한](https://github.com/midhatn/adaptive-inference/blob/v0.2.0/docs/integrations.md).
