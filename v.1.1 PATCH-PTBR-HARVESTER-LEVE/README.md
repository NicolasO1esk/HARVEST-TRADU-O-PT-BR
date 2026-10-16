# Harvester (1996) — Tradução PT-BR

Tradução para português do Brasil do jogo **Harvester** (DigiFX / Merit Studios, 1996), versão da **Steam**.

Todas as legendas, opções de resposta, tópicos de conversa, descrições de objetos, nomes, menu e várias telas da interface foram traduzidos. As **vozes continuam em inglês**: as legendas é que aparecem em português.

> ⚠️ **Você precisa ter o jogo original da Steam.** Este repositório **não contém arquivos do jogo**: só um patch de diferenças (menos de 600 KB) que é aplicado por cima dos arquivos do seu Harvester. O instalador confere os arquivos antes e não mexe em nada se eles não forem os da versão Steam.

---

## O que está traduzido

| Parte do jogo | Situação |
|---|---|
| Falas dos personagens (legendas) — 2.533 falas | ✅ traduzido |
| Opções de resposta do Steve | ✅ traduzido |
| Tópicos de conversa ("Lodge", "Stephanie", "FIM"…) | ✅ traduzido |
| Descrições ao examinar objetos, inventário, avisos | ✅ traduzido |
| Nomes de objetos e personagens ("Examine antena", "Falar: Jimmy James") | ✅ traduzido |
| Nomes dos lugares no mapa da cidade | ✅ traduzido |
| Menu principal e de opções, pausa | ✅ traduzido |
| Telas de Carregar/Salvar jogo, troca de disco, inventário, títulos das caixas | ✅ traduzido (imagens editadas) |
| Telas de ajuda (teclado/mouse/joystick) | ❌ em inglês |
| Tela "GAME OVER" | ❌ em inglês |
| Documentos desenhados que se leem com o botão direito (bilhetes, convite, jornais, ficha do Lodge…) | ❌ em inglês |
| Vozes | ❌ em inglês (legendas em português) |

A tradução usa **somente letras sem acento** (ex.: "voce", "nao"), porque as fontes do jogo não têm acentos.

---

## Requisitos

- Harvester da **Steam** instalado (Windows).
- Uns 1,6 GB livres para o backup dos originais (os 3 discos do jogo são copiados para `BACKUP-ORIGINAL-PTBR` antes de serem modificados).
- Não precisa instalar nada: o instalador usa o PowerShell que já vem no Windows.

---

## Download

Baixe este repositório (**Code → Download ZIP**) e extraia. A estrutura é:

```
PATCH-PTBR-HARVESTER-LEVE\
├── INSTALAR.bat          ← instala a tradução
├── RESTAURAR.bat         ← volta para o inglês
├── LEIA-ME.txt
├── PATCH\                ← diferenças (.hvp) + MANIFESTO.csv com os SHA-256
└── FERRAMENTA\           ← ferramenta e planilhas da tradução
```

---

## Instalação

1. **Feche o jogo.**
2. Dê dois cliques em **`INSTALAR.bat`**.
3. Digite a pasta do jogo, ou só aperte **Enter** se for o caminho padrão:
   ```
   C:\Program Files (x86)\Steam\steamapps\common\Harvester
   ```
   Para achar a pasta: na Steam, clique com o botão direito em **Harvester → Gerenciar → Explorar arquivos locais**. Ela tem as pastas `HARVEST` e `HARVEST_CD`.
4. Espere a mensagem verde **"Traducao instalada"**. A conferência das ISOs demora um pouco.
5. Abra o Harvester pela Steam normalmente.

O instalador:
- confere se os seus 6 arquivos são os da versão Steam (por SHA-256);
- guarda os originais em `<pasta do jogo>\BACKUP-ORIGINAL-PTBR\`;
- grava só os trechos traduzidos dentro dos seus arquivos;
- confere se o resultado ficou idêntico ao esperado (se não ficar, volta o original).

Se você já tinha uma versão anterior desta tradução, é só rodar o `INSTALAR.bat` de novo: ele reconhece e atualiza.

> Se o Windows mostrar um aviso de segurança ao abrir o `.bat`, clique em **Mais informações → Executar assim mesmo**. O script só mexe em arquivos dentro da pasta do jogo; dá para ler o que ele faz em `INSTALAR.ps1`.

### Para ver as legendas

No jogo, abra **OPCOES** e deixe **TEXTO** ligado.

---

## Desinstalar

Dê dois cliques em **`RESTAURAR.bat`** e informe a pasta do jogo. Os originais voltam do backup.

---

## Problemas comuns

**O jogo voltou para o inglês.**
A opção da Steam *"Verificar integridade dos arquivos"* (ou uma atualização da Steam) troca os arquivos de volta. Rode o `INSTALAR.bat` de novo.

**O instalador diz "VERSAO DIFERENTE".**
Seus arquivos não são os da versão Steam usada nesta tradução, e nada foi alterado. Dá para gerar a tradução a partir dos seus próprios arquivos com a ferramenta (precisa do [Python 3](https://www.python.org/)). Abra o PowerShell dentro de `FERRAMENTA\`:

```powershell
python harvester_texto.py aplicar --traducao TRADUCAO --jogo "<pasta do jogo>\HARVEST" --isos "<pasta do jogo>\HARVEST_CD" --saida NOVO-PATCH
```

Ela valida tudo e cria `NOVO-PATCH\` com a pasta `HARVEST` e as 3 ISOs traduzidas, sem mexer no jogo. Depois é só copiar esses arquivos para a pasta do jogo (guarde os originais antes).

**Saves antigos funcionam?**
Sim. A tradução não muda a lógica do jogo.

---

## Como a tradução foi feita

O Harvester guarda os textos em vários lugares, cada um com um formato próprio. Tudo foi descoberto por engenharia reversa e confirmado com testes no jogo, um mecanismo de cada vez.

| Onde | O que contém | Como foi tratado |
|---|---|---|
| `HARVEST\DIALOG.RSP` | opções de resposta e tópicos | texto puro; o executável pede cada linha pelo **número**, então as 806 linhas são mantidas na mesma ordem |
| `DIALOGUE.IDX` (nos discos) | as falas, indexadas pelo número do arquivo de voz | cifrado com **XOR 0xAA**; decodificado, traduzido e cifrado de novo |
| `HARVEST.SCR` (nos discos) | script do jogo: descrições, nomes de objetos e lugares | também XOR 0xAA; `_` no lugar de espaço; caixas de texto (BOX1–BOX4) aumentadas automaticamente quando a tradução não cabe |
| `HARVEST\MENU.INI` | menus | texto puro |
| `HARVEST\HARVEST.EXE` | ações do mouse, pausa, avisos | editado no lugar, sem passar do tamanho original |
| `HARVEST.DAT` (nos discos) | imagens da interface (`.BM`) | imagens 8 bits sem compressão; o texto foi reescrito com as **fontes do próprio jogo** (`.CFT`, também decodificadas) |

Pontos importantes:
- **Tópicos de conversa:** o executável compara o tópico escolhido com palavras-chave por igualdade (sem diferenciar maiúsculas). Por isso os tópicos foram traduzidos por um **glossário único**, validado automaticamente. "BYE", que encerra as conversas, virou "FIM" também dentro do executável.
- **Discos:** os arquivos traduzidos são gravados dentro das ISOs (ISO 9660). Quando ficam maiores que o espaço original, vão para o fim da imagem, e o diretório da ISO é atualizado.
- **Patch sem arquivos do jogo:** `FERRAMENTA\gerar_diff.py` compara os arquivos originais com os traduzidos e guarda só os bytes diferentes (formato `.hvp`: gzip com `"HVP1"`, tamanho final, e uma lista de offset + bytes). O `INSTALAR.ps1` grava esses trechos e confere o SHA-256 final.
- Os detalhes de cada descoberta e de cada teste estão em [`FERRAMENTA/LOG-ANALISE-TRADUCAO.txt`](FERRAMENTA/LOG-ANALISE-TRADUCAO.txt).

---

## Para quem quer corrigir ou melhorar a tradução

Tudo fica em planilhas CSV em `FERRAMENTA\TRADUCAO\` (abrem no Excel, LibreOffice ou num editor de texto):

| Planilha | Conteúdo |
|---|---|
| `TRADUCAO-IDX.csv` | falas (ID, personagem, original, tradução) |
| `TRADUCAO-RSP.csv` | opções de resposta |
| `GLOSSARIO-TOPICOS.csv` | tópicos de conversa |
| `TRADUCAO-SCR.csv` | descrições, nomes, lugares (coluna `NovaCaixa` para forçar o tamanho da caixa) |
| `TRADUCAO-MENU.csv` | menu |
| `TRADUCAO-EXE.csv` | textos do executável (respeite o tamanho máximo) |
| `IMAGENS\` | imagens editadas e o gerador (`GERADOR\imgedit.py`) |

Depois de editar, gere os arquivos traduzidos e o novo patch (em `FERRAMENTA\`):

```powershell
python harvester_texto.py status --traducao TRADUCAO
python harvester_texto.py aplicar --traducao TRADUCAO --jogo "<pasta do jogo>\HARVEST" --isos "<pasta do jogo>\HARVEST_CD" --saida NOVO-PATCH
python gerar_diff.py "<pasta do jogo>" NOVO-PATCH ..\PATCH
```

O `aplicar` recusa a gravação se encontrar problemas: acento, número de opções diferente, tópico que deixaria de funcionar, texto do EXE maior que o espaço, `%s` perdido etc. O `gerar_diff.py` precisa da pasta do jogo **original** (sem a tradução instalada).

---

## Conferência (SHA-256)

| Arquivo | Original (Steam) | Traduzido (versão 3) |
|---|---|---|
| `HARVEST\DIALOG.RSP` | `81C37E07…BCDBE85A` | `FFF47F88…AE3A0756` |
| `HARVEST\MENU.INI` | `329D4692…4256B5DD1` | `2F8B413F…F33992F0` |
| `HARVEST\HARVEST.EXE` | `6A9F3844…CD217E72C` | `1CC79C8B…22A4D1B0` |
| `HARVEST_CD\HARVESTER_DISC1.ISO` | `DC0F61FF…01397DF6` | `DF816448…9C35845E` |
| `HARVEST_CD\HARVESTER_DISC2.ISO` | `7DD48307…5556C676` | `7DCBE5B4…8B88F2E2` |
| `HARVEST_CD\HARVESTER_DISC3.ISO` | `921F5C7E…B3CEDFED` | `4BD8DEBF…6473B959` |

Os códigos completos estão em `PATCH\MANIFESTO.csv` e no `LEIA-ME.txt`. Para conferir um arquivo no PowerShell: `Get-FileHash "caminho\do\arquivo"`.

---

## Aviso

Projeto de fã, sem fins lucrativos e sem ligação com os donos do jogo. *Harvester* é marca e propriedade de seus respectivos detentores. Este repositório não distribui arquivos do jogo; para usar a tradução é preciso ter uma cópia legítima.

Encontrou texto em inglês, texto fora da caixa ou algum travamento? Abra uma **Issue** com uma captura de tela e diga em que parte do jogo aconteceu.
