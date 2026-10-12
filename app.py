import streamlit as st
import requests
import io
import zipfile
import re
import unicodedata
from PIL import Image, ImageOps

st.set_page_config(page_title="Buscador 3x4 & Bandeiras", page_icon="⚽", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# Mapa base de seleções que não são países independentes na ISO padrão (ex: Reino Unido) + nomes comuns em PT
ISO_ESPECIAIS_PT = {
    "inglaterra": "gb-eng", "escocia": "gb-sct", "gales": "gb-wls", "pais de gales": "gb-wls",
    "irlanda do norte": "gb-nir", "estados unidos": "us", "eua": "us", "holanda": "nl",
    "paises baixos": "nl", "coreia do sul": "kr", "coreia do norte": "kp", "costa do marfim": "ci",
    "republica tcheca": "cz", "tchequia": "cz", "bosnia": "ba", "macedonia do norte": "mk",
    "arabia saudita": "sa", "emirados arabes": "ae", "africa do sul": "za", "nova zelandia": "nz",
    "espanha": "es", "argentina": "ar", "franca": "fr", "belgica": "be", "marrocos": "ma",
    "suica": "ch", "noruega": "no", "brasil": "br", "egito": "eg", "colombia": "co",
    "portugal": "pt", "alemanha": "de", "croacia": "hr", "canada": "ca", "uruguai": "uy",
    "italia": "it", "japao": "jp", "senegal": "sn", "mexico": "mx", "equador": "ec",
    "chile": "cl", "paraguai": "py", "peru": "pe", "venezuela": "ve", "bolivia": "bo",
    "dinamarca": "dk", "suecia": "se", "polonia": "pl", "servia": "rs", "gana": "gh",
    "camaroes": "cm", "nigeria": "ng", "australia": "au", "catar": "qa", "ira": "ir",
    "costa rica": "cr", "panama": "pa", "argelia": "dz", "tunisia": "tn", "mali": "ml",
    "turquia": "tr", "ucrania": "ua", "austria": "at", "hungria": "hu", "grecia": "gr",
    "romenia": "ro", "eslovaquia": "sk", "eslovenia": "si", "russia": "ru", "china": "cn"
}

def normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.strip())
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

def limpar_lista(texto_bruto: str) -> list[str]:
    """Aceita itens separados por quebra de linha, vírgula ou ponto-e-vírgula e remove numerações."""
    if not texto_bruto.strip():
        return []
    # Se o usuário colou tudo numa linha separado por vírgula ou ·
    linhas = re.split(r"[\n,;·]+", texto_bruto)
    itens = []
    for l in linhas:
        limpo = re.sub(r"^\s*\d+[\.\-\)\s]+", "", l).strip()
        if limpo:
            itens.append(limpo)
    return itens

def nome_arquivo_padrao(idx: int, nome: str) -> str:
    limpo = re.sub(r"\(.*?\)", "", nome).strip()
    limpo = normalizar(limpo)
    limpo = re.sub(r"[^a-z0-9]+", "_", limpo).strip("_")
    return f"{idx:02d}_{limpo.title()}.png"

def processar_imagem_3x4(img_bytes: bytes, recorte_3x4: bool = True) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    if not recorte_3x4:
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    largura, altura = 600, 800
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGBA")
        # Mantém fundo transparente se for PNG cutout
        cortada = ImageOps.fit(img, (largura, altura), method=Image.Resampling.LANCZOS, centering=(0.5, 0.15))
    else:
        img = img.convert("RGB")
        # Foca nos 15% superiores para priorizar o rosto do jogador
        cortada = ImageOps.fit(img, (largura, altura), method=Image.Resampling.LANCZOS, centering=(0.5, 0.15))

    out = io.BytesIO()
    cortada.save(out, format="PNG")
    return out.getvalue()

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_opcoes_jogador(nome_input: str) -> list[str]:
    """Retorna uma lista de URLs públicas de fotos do jogador sem precisar de login."""
    termo_sem_parenteses = re.sub(r"\(.*?\)", "", nome_input).strip()
    urls = []

    # 1. TheSportsDB API (Pública - traz cutouts em PNG e headshots oficiais)
    for q in [nome_input, termo_sem_parenteses]:
        try:
            r = requests.get(
                "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php",
                params={"p": q}, headers=HEADERS, timeout=6
            )
            if r.ok and r.json().get("player"):
                for p in r.json()["player"]:
                    if p.get("strSport") in ("Soccer", "Football", None):
                        for campo in ["strCutout", "strThumb", "strRender"]:
                            if p.get(campo) and p[campo] not in urls:
                                urls.append(p[campo])
        except Exception:
            pass

    # 2. Wikipedia API (PT e EN) com busca semântica de futebolista
    consultas_wiki = [
        ("pt", f"{nome_input} futebolista"),
        ("pt", nome_input),
        ("en", f"{termo_sem_parenteses} footballer"),
        ("en", termo_sem_parenteses),
    ]
    for lang, query in consultas_wiki:
        try:
            s_res = requests.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": query, "srlimit": 2, "format": "json"},
                headers=HEADERS, timeout=6
            )
            if s_res.ok:
                resultados = s_res.json().get("query", {}).get("search", [])
                for item in resultados:
                    titulo = item["title"]
                    sum_res = requests.get(
                        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(titulo)}",
                        headers=HEADERS, timeout=6
                    )
                    if sum_res.ok:
                        dados = sum_res.json()
                        if "thumbnail" in dados and dados["thumbnail"].get("source"):
                            u_thumb = re.sub(r"/\d+px-", "/800px-", dados["thumbnail"]["source"])
                            if u_thumb not in urls:
                                urls.append(u_thumb)
                        if "originalimage" in dados and dados["originalimage"].get("source"):
                            u_orig = dados["originalimage"]["source"]
                            if u_orig not in urls and not u_orig.lower().endswith(".svg"):
                                urls.append(u_orig)
        except Exception:
            pass

    # 3. Wikimedia Commons Direct Image Search (Fallback caso não tenha página na Wiki)
    if len(urls) < 2:
        try:
            c_res = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query", "generator": "search",
                    "gsrsearch": f"filetype:bitmap {termo_sem_parenteses} football",
                    "gsrlimit": 4, "prop": "imageinfo", "iiprop": "url", "format": "json"
                },
                headers=HEADERS, timeout=6
            )
            if c_res.ok:
                pages = c_res.json().get("query", {}).get("pages", {})
                for p in pages.values():
                    ii = p.get("imageinfo", [{}])[0]
                    if ii.get("url") and ii["url"] not in urls:
                        urls.append(ii["url"])
        except Exception:
            pass

    return urls

@st.cache_data(ttl=3600, show_spinner=False)
def baixar_imagem_url(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok and "image" in r.headers.get("Content-Type", ""):
            return r.content
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_bandeira_dinamica(nome_pais: str) -> tuple[bytes | None, str | None]:
    chave = normalizar(nome_pais)
    codigo = ISO_ESPECIAIS_PT.get(chave)

    # Busca na API pública RestCountries caso o usuário digite qualquer outro país do mundo
    if not codigo:
        for endpoint in [f"translation/{requests.utils.quote(nome_pais)}", f"name/{requests.utils.quote(nome_pais)}"]:
            try:
                r = requests.get(f"https://restcountries.com/v3.1/{endpoint}", headers=HEADERS, timeout=6)
                if r.ok and isinstance(r.json(), list) and len(r.json()) > 0:
                    codigo = r.json()[0].get("cca2", "").lower()
                    if codigo:
                        break
            except Exception:
                pass

    if codigo:
        url = f"https://flagcdn.com/w640/{codigo}.png"
        b = baixar_imagem_url(url)
        if b:
            return b, url

    # Fallback: busca bandeira direto na Wikipedia PT
    try:
        sum_res = requests.get(
            f"https://pt.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(nome_pais)}",
            headers=HEADERS, timeout=6
        )
        if sum_res.ok:
            dados = sum_res.json()
            if "thumbnail" in dados and dados["thumbnail"].get("source"):
                u_thumb = re.sub(r"/\d+px-", "/640px-", dados["thumbnail"]["source"])
                b = baixar_imagem_url(u_thumb)
                if b:
                    return b, u_thumb
    except Exception:
        pass

    return None, None

def gerar_zip_atual(recorte_3x4: bool) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, item in enumerate(st.session_state.get("jogadores_data", []), 1):
            urls = item["urls"]
            escolha = st.session_state.get(f"sel_jog_{idx}", 0)
            if urls and escolha < len(urls):
                raw = baixar_imagem_url(urls[escolha])
                if raw:
                     processada = processar_imagem_3x4(raw, recorte_3x4)
                     zf.writestr(f"jogadores/{nome_arquivo_padrao(idx, item['nome'])}", processada)

        for idx, item in enumerate(st.session_state.get("bandeiras_data", []), 1):
            if item["bytes"]:
                zf.writestr(f"bandeiras/{nome_arquivo_padrao(idx, item['nome'])}", item["bytes"])
    return buf.getvalue()

# ================= INTERFACE =================
st.title("⚽ Gerador Dinâmico de Fotos 3x4 & Bandeiras")
st.caption("Cole os jogadores e seleções que quiser (1 por linha ou separados por vírgula). Busca 100% em links públicos sem login.")

col_j, col_b = st.columns(2)

with col_j:
    input_jogadores = st.text_area(
        "👤 Jogadores (digite ou cole qualquer lista):",
        placeholder="Ex:\nRodri\nMbappé\nRayan Vasco\nRonaldo Fenômeno...",
        height=260
    )

with col_b:
    input_bandeiras = st.text_area(
        "🏳️ Países / Bandeiras (digite ou cole qualquer lista):",
        placeholder="Ex:\nBrasil\nEspanha\nNoruega\nMarrocos...",
        height=260
    )

col_opt1, col_opt2 = st.columns([2, 1])
with col_opt1:
    recorte_3x4 = st.checkbox("✂️ Cortar fotos dos jogadores automaticamente em 3x4 (600x800px)", value=True)

if st.button("🔍 Buscar Fotos e Bandeiras", type="primary", use_container_width=True):
    lista_j = limpar_lista(input_jogadores)
    lista_b = limpar_lista(input_bandeiras)

    if not lista_j and not lista_b:
        st.warning("Digite pelo menos um jogador ou uma bandeira para buscar.")
    else:
        total = len(lista_j) + len(lista_b)
        prog = st.progress(0, text="Iniciando busca pública...")
        atual = 0

        jog_data = []
        for idx, nome in enumerate(lista_j, 1):
            atual += 1
            prog.progress(atual / total, text=f"Buscando jogador ({idx}/{len(lista_j)}): {nome}...")
            urls = buscar_opcoes_jogador(nome)
            # Filtra apenas URLs que realmente abrem como imagem
            urls_validas = [u for u in urls if baixar_imagem_url(u) is not None]
            jog_data.append({"nome": nome, "urls": urls_validas})
            st.session_state[f"sel_jog_{idx}"] = 0

        band_data = []
        for idx, pais in enumerate(lista_b, 1):
            atual += 1
            prog.progress(atual / total, text=f"Buscando bandeira ({idx}/{len(lista_b)}): {pais}...")
            b_bytes, b_url = buscar_bandeira_dinamica(pais)
            band_data.append({"nome": pais, "bytes": b_bytes, "url": b_url})

        prog.empty()
        st.session_state["jogadores_data"] = jog_data
        st.session_state["bandeiras_data"] = band_data

# ================= RESULTADOS E DOWNLOAD =================
if st.session_state.get("jogadores_data") or st.session_state.get("bandeiras_data"):
    st.divider()
    zip_bytes = gerar_zip_atual(recorte_3x4)

    st.download_button(
        label="⬇️ BAIXAR TUDO EM .ZIP (Pastas 'jogadores/' e 'bandeiras/' numeradas)",
        data=zip_bytes,
        file_name="pacote_imagens.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )

    if st.session_state.get("jogadores_data"):
        st.subheader(f"👤 Jogadores ({len(st.session_state['jogadores_data'])})")
        st.caption("Dica: Se quiser trocar a foto de algum jogador, mude a opção abaixo da foto que o ZIP atualiza automaticamente.")
        cols = st.columns(5)
        for idx, item in enumerate(st.session_state["jogadores_data"], 1):
            with cols[(idx - 1) % 5]:
                urls = item["urls"]
                if urls:
                    if len(urls) > 1:
                        escolha = st.selectbox(
                            f"Foto #{idx} ({item['nome']})",
                            options=range(len(urls)),
                            format_func=lambda i: f"Opção {i+1} de {len(urls)}",
                            key=f"sel_jog_{idx}"
                        )
                    else:
                        escolha = 0
                    raw = baixar_imagem_url(urls[escolha])
                    if raw:
                        img_exibir = processar_imagem_3x4(raw, recorte_3x4)
                        st.image(img_exibir, caption=f"{idx:02d}. {item['nome']}", use_container_width=True)
                else:
                    st.error(f"❌ {idx:02d}. {item['nome']} (Não encontrado — tente adicionar o clube ao lado, ex: '{item['nome']} Vasco')")

    if st.session_state.get("bandeiras_data"):
        st.subheader(f"🏳️ Bandeiras ({len(st.session_state['bandeiras_data'])})")
        cols_b = st.columns(6)
        for idx, item in enumerate(st.session_state["bandeiras_data"], 1):
            with cols_b[(idx - 1) % 6]:
                if item["bytes"]:
                    st.image(item["bytes"], caption=f"{idx:02d}. {item['nome']}", use_container_width=True)
                else:
                    st.error(f"❌ {idx:02d}. {item['nome']}")