# Fiberhome ONT — ACS Auto-Configurator

Script Python para consulta automática de ONUs via SSH em OLTs Fiberhome e aplicação em massa da URL do ACS (TR-069), com controle de falhas, retentativa e geração de relatórios.

⚠️ Observação Importante

Antes de utilizar este script em massa, é obrigatório validar o funcionamento da ONT com o servidor ACS de forma individual e manual.

Para isso:

    Configure manualmente a WAN como TR069_INTERNET (ou uma segunda WAN dedicada ao TR069), conforme o planejamento da sua rede.

    Confirme que a ONT estabelece conexão corretamente com o servidor ACS configurando manualmente também os dados url que devem ser configurados aqui.

    Somente após essa validação individual, utilize esta ferramenta para configuração em massa.

    Atenção: A não realização dessa validação prévia pode resultar em falhas de funcionamento da comunicação do ACS com as CPE's em toda a frota de ONTs.
---

## Compatibilidade

| Equipamento | Firmware suportado |
|---|---|
| Fiberhome AN5516-01 | RP1000 ~ RP1400 |
| Fiberhome AN5516-06 | RP1000 ~ RP1400 |
| Fiberhome AN5516-04 | RP1000 ~ RP1400 |

> Firmwares inferiores a esta faixa podem apresentar diferenças na sintaxe dos comandos e não foram validados, superiores a esta faixa possuem recursos que podem suprir a necessidade do uso desta ferramenta.

---

## ⚠️ Aviso de Responsabilidade

> **O uso deste script é de total responsabilidade do usuário.**

> OLTs Fiberhome da série 5000 são equipamentos sensíveis a alto processamento. O script foi desenvolvido com intervalos de segurança entre comandos (`CMD_DELAY = 3s`) e timeout por ONU (`TIMEOUT = 7s`) justamente para minimizar impacto no equipamento.
>
> **Recomendação:** processe no máximo **40 ONUs por execução** de forma simultânea. Para lotes maiores, divida o arquivo `base.csv` em partes e execute separadamente.
>
> O autor não se responsabiliza por instabilidades, quedas de serviço ou qualquer dano causado pelo uso indevido deste script em ambiente de produção.

---

## Pré-requisitos

- Python **3.8** ou superior
- Acesso SSH à OLT (porta 22 liberada)
- Sistema operacional: **Linux** ou **macOS** (pexpect não tem suporte nativo no Windows)

---

## Instalação

**1. Clone o repositório**
```bash
git clone https://github.com/seu-usuario/fiberhome-acs-configurator.git
cd fiberhome-acs-configurator
```

**2. Crie e ative um ambiente virtual (recomendado)**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Instale as dependências**
```bash
pip install -r requirements.txt
```

**4. Configure as credenciais da OLT**

Copie o arquivo de exemplo e preencha com os dados do seu equipamento:
```bash
cp .env.example .env
```

Edite o `.env`:
```
ip    = 10.0.0.211
login = SEU_USUARIO
senha = SUA_SENHA

url          = http://meuservidor.com.br:7547
username_acs = admin
passwd_acs   = admin
inform       = 300
port         = 7547
username_conn = admin
passwd_conn   = admin
```

**5. Prepare o arquivo de entrada**

Coloque o arquivo `base.csv` na pasta `olt/` com o seguinte formato (abaixo do cabeçalho exato sem espaço `nome,serial`):
```
NOME DO CLIENTE,FHTTxxxxxxxx
OUTRO CLIENTE,FHTTyyyyyyyy
```

> O script ignora automaticamente linhas com seriais inválidos (que não seguem o padrão `FHTT` + hexadecimal).

---

## Estrutura do Projeto

```
fiberhome-acs-configurator/
├── olt/
│   ├── base.csv                  # Arquivo de entrada (nome, serial)
│   ├── dados_atualizados.csv     # Gerado: SLOT, PON, ONU coletados
│   ├── falhas_manuais.csv        # Gerado: ONUs que precisam de atenção manual
│   └── acs_YYYYMMDD_HHMMSS.log  # Gerado: log completo da execução
├── main.py
├── requirements.txt
├── .env.example
├── .env                          # NÃO versionar (já no .gitignore)
└── README.md
```

---

## Uso

```bash
python3 main.py
```

### Fluxo de execução

**Etapa 1 — Coleta de dados (SLOT / PON / ONU)**

O script conecta via SSH na OLT e consulta cada serial do `base.csv`:
```
show onu-info by FHTTxxxxxxxx
```
- Exibe barra de progresso com tempo estimado em tempo real
- Timeout por ONU: 7 segundos
- ONUs sem retorno ou com timeout são listadas ao final

Caso haja falhas na coleta, o usuário recebe três opções:
```
Os dados foram capturados corretamente? [Y] Continuar  [X] Fechar  [R] Tentar nova coleta
```
- `[R]` realiza uma segunda tentativa **somente nas ONUs pendentes**
- Após a segunda tentativa, o script segue sem oferecer nova retentativa

**Etapa 2 — Aplicação da URL do ACS (TR-069)**

Executada apenas nas ONUs com dados coletados com sucesso:
```
set remote_manage_cfg slot {SLOT} pon {PON} onu {ONU} tr069 enable acs_url http://... 
```

**Encerramento**

Ao finalizar, o script:
- Exibe resumo de sucesso e falhas
- Gera `falhas_manuais.csv` com todas as ONUs que não foram configuradas e o motivo
- Gera arquivo `.log` com timestamp com todos os eventos da sessão
- Encerra a sessão SSH de forma limpa (`cd .` → `exit`)

---

## Arquivos gerados

| Arquivo | Descrição |
|---|---|
| `olt/dados_atualizados.csv` | Todos os registros com SLOT, PON e ONU coletados |
| `olt/falhas_manuais.csv` | ONUs com falha na coleta ou no envio do ACS |
| `olt/acs_YYYYMMDD_HHMMSS.log` | Log completo com todos os eventos da execução |

> Arquivos existentes são renomeados automaticamente antes de serem substituídos (`_old1`, `_old2`, etc.), preservando execuções anteriores.

---

## Dependências

| Pacote | Uso |
|---|---|
| `pexpect` | Automação da sessão SSH interativa |
| `python-dotenv` | Leitura das credenciais do arquivo `.env` |

---

## Licença

Este projeto está licenciado sob **CC BY-NC-ND 4.0**.

- ✅ Uso pessoal e profissional permitido
- ❌ Modificações e obras derivadas não permitidas
- ❌ Uso comercial não permitido

Veja o arquivo [LICENSE](LICENSE) ou acesse [creativecommons.org/licenses/by-nc-nd/4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/) para detalhes.
