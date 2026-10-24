**Inferência local compartilhada para tarefas em segundo plano:**

Quando Agents interativos e autônomos compartilham um servidor de modelo local, um gateway externo opcional de admissão pode distinguir as solicitações em espera. O [Adaptive Inference v0.2.0](https://github.com/midhatn/adaptive-inference/releases/tag/v0.2.0) oferece `/v1` e `/background/v1` na mesma fila. Configure e inicie o gateway separadamente conforme as instruções da versão, mantendo o servidor de modelo e as configurações de qualidade existentes.

Defina `ADAPTIVE_GATEWAY_ROOT` como a raiz do endereço do gateway, por exemplo `http://127.0.0.1:18100`, sem `/v1`. Forneça a chave por `ADAPTIVE_GATEWAY_KEY` se a autenticação estiver habilitada. O arquivo `llm-settings.json` contém o `model` existente e os argumentos de geração verificados, incluindo limites explícitos de saída e raciocínio e o `extra_body` compatível; ele não contém roteamento nem credenciais.

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

Passe `interactive_llm` ou `background_llm` como `llm` de um Agent conforme o papel escolhido pela aplicação. Esse roteamento é explícito: não infere prioridade dos prompts nem classifica todos os Agents filhos automaticamente. A fila externa admite uma solicitação ao servidor por vez, o que pode reduzir a vazão do processamento em lote nativo. Ela não interrompe uma geração ativa, descarrega modelos nem reserva memória de GPU. Desabilite novas tentativas automáticas quando a conclusão for incerta e configure o tempo limite do cliente para cobrir os limites da fila e da execução. Use Chat Completions; esse gateway não oferece Responses nem rotas de gerenciamento nativo.

Preserve os campos compatíveis com o servidor em vez de traduzir controles entre mecanismos. O cliente OpenAI do CrewAI converte esquemas de funções para o modo estrito; verifique se isso atende às suas ferramentas. Verificações de configuração e HTTP com respostas simuladas não comprovam qualidade do modelo real nem transferência de recursos. [Reprodução e limites de compatibilidade](https://github.com/midhatn/adaptive-inference/blob/v0.2.0/docs/integrations.md).
