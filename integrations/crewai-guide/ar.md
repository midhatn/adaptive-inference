**استدلال محلي مشترك للمهام الخلفية:**

عندما تشترك Agents تفاعلية ومستقلة في خادم نموذج محلي واحد، يمكن لبوابة اختيارية خارجية لتنظيم قبول الطلبات أن تميّز الطلبات المنتظرة. يوفّر [Adaptive Inference v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0) المسارين `/v1` و`/background/v1` عبر قائمة انتظار واحدة. اضبط البوابة وشغّلها بصورة منفصلة وفق تعليمات الإصدار، مع الاحتفاظ بخادم النموذج الحالي وإعدادات الجودة.

اضبط `ADAPTIVE_GATEWAY_ROOT` على عنوان البوابة الأساسي، مثل `http://127.0.0.1:18100`، دون `/v1`. وفّر مفتاحها عبر `ADAPTIVE_GATEWAY_KEY` إذا كانت المصادقة مفعّلة. يحتوي `llm-settings.json` على `model` الحالي ومعاملات التوليد التي تحققت منها، بما فيها حدود الإخراج والاستدلال الصريحة و`extra_body` المدعوم، دون إعدادات التوجيه أو بيانات الاعتماد.

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

مرّر `interactive_llm` أو `background_llm` إلى حقل `llm` في Agent بحسب الدور الذي يختاره تطبيقك. هذا توجيه صريح من التطبيق؛ لا يستنتج الأولوية من المطالبات ولا يصنّف كل Agent فرعي تلقائيًا. تسمح القائمة الخارجية بطلب واحد إلى الخادم في كل مرة، مما قد يقلل إنتاجية التجميع الأصلية. لا يمكنها إيقاف توليد نشط أو إلغاء تحميل النموذج أو حجز ذاكرة GPU. عطّل المحاولات التلقائية عند غموض اكتمال الطلب، واضبط مهلة العميل لتشمل حدود الانتظار والتنفيذ. استخدم Chat Completions؛ لا توفّر هذه البوابة مسارات Responses أو الإدارة الأصلية.

احتفظ بالحقول التي يدعمها الخادم بدل ترجمة عناصر التحكم بين المحركات. يحوّل عميل OpenAI في CrewAI مخططات الدوال إلى الوضع الصارم؛ تأكد من ملاءمة ذلك لأدواتك. لا تثبت فحوص الإعداد أو HTTP ذات الاستجابات المحاكية جودة النموذج الفعلي أو تسليم الموارد. [إعادة الإنتاج وحدود التوافق](https://github.com/midhatn/adaptive-inference/blob/v0.2.0/docs/integrations.md).
