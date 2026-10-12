import streamlit as st
import requests
import io
import zipfile
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

st.set_page_config(page_title="Buscador Universal 3x4 & Bandeiras", page_icon="⚽", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# Mapa auxiliar apenas para seleções britânicas/especiais no FlagCDN (o resto busca via API ou fallback universal)
ISO_RAPIDO = {
    "inglaterra": "gb-eng", "escocia": "gb-sct", "gales": "gb-wls", "pais de gales": "gb-wls",
    "irlanda do norte": "gb-nir", "estados unidos": "us", "eua": "us", "holanda": "nl",
    "paises baixos": "nl", "coreia do sul": "kr", "costa do marfim": "ci", "republica tcheca": "cz",
    "espanha": "es", "argentina": "ar", "franca": "fr", "belgica": "be", "marrocos": "ma",
    "suica": "ch", "noruega": "no", "brasil": "br", "egito": "eg", "colombia": "co",
    "portugal": "pt", "alemanha": "de", "croacia": "hr", "canada": "ca", "uruguai": "uy",
    "italia": "it", "japao": "jp", "senegal": "sn", "mexico": "mx", "equador": "ec",
    "chile": "cl", "paraguai": "py", "peru": "pe", "venezuela": "ve", "bolivia": "bo"
}

def normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.strip())
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

def extrair_itens(texto: str) -> list[str]:
    """Limpa numerações, cabeçalhos ('Jogadores (28)') e separa por linha ou vírgula."""
    itens = []
    for linha in texto.splitlines():
        l_strip = linha.strip()
        if not l_strip:
            continue
        # Ignora linhas que sejam apenas títulos como "Jogadores (28)" ou "Bandeiras (17)"
        if re.match(r"^(jogadores|bandeiras|selecoes|paises)\s*(\(\d+\))?:?$", normalizar(l_strip)):
            continue
        # Se a linha tiver vírgulas ou pontos separadores, divide; senão pega a linha inteira
        partes = re.split(r"[,;·]+", l_strip) if "," in l_strip or "·" in l_strip else [l_strip]
        for p in partes:
            limpo = re.sub(r"^\s*\d+[\.\-\)\s]+", "", p).strip()
            if limpo:
                itens.append(limpo)
    return itens

def separar_colagem_mista(texto_jog: str, texto_band: str) -> tuple[list[str], list[str]]:
    """Se o usuário colar Jogadores + Bandeiras tudo na caixa 1 e deixar a caixa 2 vazia, separa sozinho."""
    if not texto_band.strip() and re.search(r"(?i)\bbandeiras\s*(\(\d+\))?", texto_jog):
        partes = re.split(r"(?i)\bbandeiras\s*(?:\(\d+\))?:?", texto_jog, maxsplit=1)
        return extrair_itens(partes[0]), extrair_itens(partes[1])
    return extrair_itens(texto_jog), extrair_itens(texto_band)

def nome_arquivo_padrao(idx: int, nome: str) -> str:
    limpo = re.sub(r"\(.*?\)", "", nome).strip()
    limpo = normalizar(limpo)
    limpo = re.sub(r"[^a-z0-9]+", "_", limpo).strip("_")
    return f"{idx:02d}_{limpo.title()}.png"

def formatar_3x4(img_bytes: bytes, aplicar_corte: bool = True) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    if not aplicar_corte:
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    largura, altura = 600, 800
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGBA")
        cortada = ImageOps.fit(img, (largura, altura), method=Image.Resampling.LANCZOS, centering=(0.5, 0.15))
    else:
        img = img.convert("RGB")
        cortada = ImageOps.fit(img, (largura, altura), method=Image.Resampling.LANCZOS, centering=(0.5, 0.15))

    out = io.BytesIO()
    cortada.save(out, format="PNG")
    return out.getvalue()

@st.cache_data(ttl=3600, show_spinner=False)
def baixar_bytes(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.ok and "image" in r.headers.get("Content-Type", "") and len(r.content) > 1200:
            return r.content
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_opcoes_jogador_universal(nome_input: str) -> tuple[bytes | None, list[str]]:
    """Busca 100% dinâmica para qualquer jogador que o usuário digitar."""
    sem_parenteses = re.sub(r"\(.*?\)", "", nome_input).strip()
    contexto_extra = " ".join(re.findall(r"\((.*?)\)", nome_input))
    termo_completo = f"{sem_parenteses} {contexto_extra}".strip()

    urls = []

    # 1. Retrato 3x4 Público Direto (Alta precisão para qualquer jogador do mundo, mesmo com apelido/clube)
    queries_retrato = [
        f"{termo_completo} jogador futebol portrait headshot",
        f"{sem_parenteses} footballer portrait",
        f"{termo_completo} soccer player face"
    ]
    for q in queries_retrato:
        q_enc = requests.utils.quote(q)
        urls.append(f"https://tse1.mm.bing.net/th?q={q_enc}&w=600&h=800&c=7&rs=1&p=0")

    # 2. TheSportsDB API Pública (Cutouts transparentes e fotos de perfil)
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php",
            params={"p": sem_parenteses}, headers=HEADERS, timeout=5
        )
        if r.ok and r.json().get("player"):
            for p in r.json()["player"]:
                if p.get("strSport") in ("Soccer", "Football", None):
                    for campo in ["strCutout", "strThumb", "strRender"]:
                        if p.get(campo) and p[campo] not in urls:
                            urls.insert(0, p[campo])  # Prioriza cutout oficial se existir
    except Exception:
        pass

    # 3. Wikipedia API (PT e EN)
    for lang, sufixo in [("pt", "futebolista"), ("en", "footballer")]:
        try:
            s = requests.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": f"{termo_completo} {sufixo}", "srlimit": 1, "format": "json"},
                headers=HEADERS, timeout=5
            )
            if s.ok:
                busca = s.json().get("query", {}).get("search", [])
                if busca:
                    titulo = busca[0]["title"]
                    res = requests.get(
                        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(titulo)}",
                        headers=HEADERS, timeout=5
                    )
                    if res.ok:
                        d = res.json()
                        if "thumbnail" in d and d["thumbnail"].get("source"):
                            u = re.sub(r"/\d+px-", "/800px-", d["thumbnail"]["source"])
                            if u not in urls:
                                urls.append(u)
        except Exception:
            pass

    # Testa na ordem e retorna a primeira imagem válida + lista de opções para troca
    for u in urls:
        b = baixar_bytes(u)
        if b:
            return b, urls

    return None, []

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_bandeira_universal(nome_pais: str) -> bytes | None:
    chave = normalizar(nome_pais)
    codigo = ISO_RAPIDO.get(chave)

    # Consulta API pública RestCountries para qualquer país digitado em qualquer idioma
    if not codigo:
        for ep in [f"translation/{requests.utils.quote(nome_pais)}", f"name/{requests.utils.quote(nome_pais)}"]:
            try:
                r = requests.get(f"https://restcountries.com/v3.1/{ep}", headers=HEADERS, timeout=5)
                if r.ok and isinstance(r.json(), list) and len(r.json()) > 0:
                    codigo = r.json()[0].get("cca2", "").lower()
                    if codigo:
                        break
            except Exception:
                pass

    if codigo:
        b = baixar_bytes(f"https://flagcdn.com/w640/{codigo}.png")
        if b:
            return b

    # Fallback universal para qualquer seleção/território/bandeira
    q_flag = requests.utils.quote(f"bandeira oficial {nome_pais} flag")
    return baixar_bytes(f"https://tse1.mm.bing.net/th?q={q_flag}&w=640&h=420&c=7&rs=1")

# ================= INTERFACE ABERTA =================
st.title("⚽ Buscador Aberto de Jogadores (3x4) & Bandeiras")
st.markdown("Digite ou cole **qualquer lista de jogadores e bandeiras** nas caixas abaixo (ou cole o pacote inteiro direto na primeira caixa).")

col1, col2 = st.columns(2)

with col1:
    txt_jogadores = st.text_area(
        "👤 Caixa de Jogadores (1 por linha ou separados por vírgula):",
        height=280,
        placeholder="Cole aqui qualquer lista de jogadores...\nEx:\n1. Rodri\n2. Mbappé\n3. Rayan\n\n(Ou cole o texto inteiro com Jogadores + Bandeiras aqui)"
    )

with col2:
    txt_bandeiras = st.text_area(
        "🏳️ Caixa de Bandeiras (1 por linha ou separados por vírgula):",
        height=280,
        placeholder="Cole aqui os países/seleções...\nEx:\nEspanha, Argentina, Inglaterra, Brasil..."
    )

recorte_3x4 = st.checkbox("✂️ Cortar fotos dos jogadores automaticamente em 3x4 (600x800px)", value=True)

if st.button("🚀 Buscar Imagens e Montar .ZIP", type="primary", use_container_width=True):
    lista_j, lista_b = separar_colagem_mista(txt_jogadores, txt_bandeiras)
    total = len(lista_j) + len(lista_b)

    if total == 0:
        st.warning("Coloque pelo menos um nome nas caixas de texto acima!")
    else:
        st.info(f"Processando **{len(lista_j)} jogadores** e **{len(lista_b)} bandeiras** ({total} itens no total)...")
        barra = st.progress(0, text="Buscando em repositórios públicos...")

        res_j = [None] * len(lista_j)
        res_b = [None] * len(lista_b)
        feitos = 0

        with ThreadPoolExecutor(max_workers=8) as ex:
            fut_j = {ex.submit(buscar_opcoes_jogador_universal, n): i for i, n in enumerate(lista_j)}
            fut_b = {ex.submit(buscar_bandeira_universal, p): i for i, p in enumerate(lista_b)}

            for f in fut_j:
                i = fut_j[f]
                img_b, urls = f.result()
                res_j[i] = {"nome": lista_j[i], "bytes": img_b, "urls": urls}
                st.session_state[f"op_jog_{i}"] = 0
                feitos += 1
                barra.progress(feitos / total, text=f"Baixado ({feitos}/{total}): {lista_j[i]}")

            for f in fut_b:
                i = fut_b[f]
                img_b = f.result()
                res_b[i] = {"nome": lista_b[i], "bytes": img_b}
                feitos += 1
                barra.progress(feitos / total, text=f"Baixado ({feitos}/{total}): {lista_b[i]}")

        barra.empty()
        st.session_state["res_j"] = res_j
        st.session_state["res_b"] = res_b

# ================= GALERIA E BOTÃO ZIP =================
if "res_j" in st.session_state or "res_b" in st.session_state:
    res_j = st.session_state.get("res_j", [])
    res_b = st.session_state.get("res_b", [])

    zip_buffer = io.BytesIO()
    cont_j, cont_b = 0, 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, item in enumerate(res_j):
            op = st.session_state.get(f"op_jog_{i}", 0)
            img_atual = baixar_bytes(item["urls"][op]) if (item["urls"] and op < len(item["urls"])) else item["bytes"]
            if img_atual:
                zf.writestr(f"jogadores/{nome_arquivo_padrao(i + 1, item['nome'])}", formatar_3x4(img_atual, recorte_3x4))
                cont_j += 1

        for i, item in enumerate(res_b):
            if item["bytes"]:
                zf.writestr(f"bandeiras/{nome_arquivo_padrao(i + 1, item['nome'])}", item["bytes"])
                cont_b += 1

    st.success(f"✅ Pronto! **{cont_j}/{len(res_j)} jogadores** + **{cont_b}/{len(res_b)} bandeiras** = **{cont_j + cont_b} arquivos** prontos.")

    st.download_button(
        label=f"⬇️ BAIXAR TUDO EM .ZIP ({cont_j + cont_b} imagens numeradas)",
        data=zip_buffer.getvalue(),
        file_name="pacote_jogadores_bandeiras.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )

    if res_j:
        st.subheader(f"👤 Jogadores ({cont_j}/{len(res_j)})")
        cols = st.columns(6)
        for i, item in enumerate(res_j):
            with cols[i % 6]:
                if item["urls"]:
                    op = st.selectbox(
                        f"{i+1:02d}. {item['nome']}",
                        options=range(len(item["urls"])),
                        format_func=lambda x: f"Foto {x+1}",
                        key=f"op_jog_{i}"
                    )
                    img_mostrar = baixar_bytes(item["urls"][op]) or item["bytes"]
                    if img_mostrar:
                        st.image(formatar_3x4(img_mostrar, recorte_3x4), use_container_width=True)
                else:
                    st.error(f"{i+1:02d}. {item['nome']}")

    if res_b:
        st.subheader(f"🏳️ Bandeiras ({cont_b}/{len(res_b)})")
        cols_b = st.columns(6)
        for i, item in enumerate(res_b):
            with cols_b[i % 6]:
                if item["bytes"]:
                    st.image(item["bytes"], caption=f"{i+1:02d}. {item['nome']}", use_container_width=True)
                else:
                    st.error(f"{i+1:02d}. {item['nome']}")