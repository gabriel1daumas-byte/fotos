import streamlit as st
import requests
import io
import zipfile
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageOps

st.set_page_config(page_title="Buscador 3x4 Frontal & Bandeiras", page_icon="⚽", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

ISO_RAPIDO = {
    "inglaterra": "gb-eng", "escocia": "gb-sct", "gales": "gb-wls", "pais de gales": "gb-wls",
    "irlanda do norte": "gb-nir", "estados unidos": "us", "eua": "us", "holanda": "nl",
    "paises baixos": "nl", "coreia do sul": "kr", "costa do marfim": "ci", "republica tcheca": "cz",
    "espanha": "es", "argentina": "ar", "franca": "fr", "belgica": "be", "marrocos": "ma",
    "suica": "ch", "noruega": "no", "brasil": "br", "egito": "eg", "colombia": "co",
    "portugal": "pt", "alemanha": "de", "croacia": "hr", "canada": "ca", "uruguai": "uy",
    "italia": "it", "japao": "jp", "senegal": "sn", "mexico": "mx", "equador": "ec",
    "chile": "cl", "paraguai": "py", "peru": "pe", "venezuela": "ve", "bolivia": "bo",
    "dinamarca": "dk", "suecia": "se", "polonia": "pl", "servia": "rs", "gana": "gh",
    "camaroes": "cm", "nigeria": "ng", "australia": "au", "arabia saudita": "sa",
    "catar": "qa", "ira": "ir", "costa rica": "cr", "panama": "pa", "argelia": "dz",
    "tunisia": "tn", "mali": "ml", "africa do sul": "za", "turquia": "tr", "ucrania": "ua",
    "austria": "at", "hungria": "hu", "grecia": "gr", "romenia": "ro", "eslovaquia": "sk",
    "eslovenia": "si", "russia": "ru", "china": "cn", "nova zelandia": "nz"
}

def normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto.strip())
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()

def extrair_itens(texto: str) -> list[str]:
    itens = []
    for linha in texto.splitlines():
        l_strip = linha.strip()
        if not l_strip:
            continue
        if re.match(r"^(jogadores|bandeiras|selecoes|paises)\s*(\(\d+\))?:?$", normalizar(l_strip)):
            continue
        partes = re.split(r"[,;·]+", l_strip) if "," in l_strip or "·" in l_strip else [l_strip]
        for p in partes:
            limpo = re.sub(r"^\s*\d+[\.\-\)\s]+", "", p).strip()
            if limpo:
                itens.append(limpo)
    return itens

def separar_colagem_mista(texto_jog: str, texto_band: str) -> tuple[list[str], list[str]]:
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
        r = requests.get(url, headers=HEADERS, timeout=7)
        if r.ok and "image" in r.headers.get("Content-Type", "") and len(r.content) > 1500:
            return r.content
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_jogador_olhando_camera(nome_input: str) -> tuple[bytes | None, list[str]]:
    """
    Prioriza Cutouts oficiais de estúdio (TheSportsDB) e Retratos 3x4 com Smart-Face Crop (c=7&p=0)
    onde o jogador está de frente a olhar para a câmara.
    """
    sem_parenteses = re.sub(r"\(.*?\)", "", nome_input).strip()
    contexto_extra = " ".join(re.findall(r"\((.*?)\)", nome_input))
    termo_completo = f"{sem_parenteses} {contexto_extra}".strip()

    urls_candidatas = []

    # 1. TheSportsDB API (Cutouts PNG e Thumbs de estúdio posados de frente)
    try:
        r = requests.get(
            "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php",
            params={"p": sem_parenteses}, headers=HEADERS, timeout=5
        )
        if r.ok and r.json().get("player"):
            for p in r.json()["player"]:
                if p.get("strSport") in ("Soccer", "Football", None):
                    for campo in ["strCutout", "strThumb"]:
                        if p.get(campo) and p[campo] not in urls_candidatas:
                            urls_candidatas.append(p[campo])
    except Exception:
        pass

    # 2. Retratos 3x4 com Face-Crop nativo do servidor (c=7 & p=0 foca automaticamente na cara de frente)
    queries_frontais = [
        f"{termo_completo} official player headshot portrait front",
        f"{termo_completo} ea fc fifa card render official headshot",
        f"{termo_completo} jogador futebol foto perfil 3x4 oficial",
        f"{sem_parenteses} footballer portrait looking at camera"
    ]
    for q in queries_frontais:
        q_enc = requests.utils.quote(q)
        urls_candidatas.append(f"https://tse1.mm.bing.net/th?q={q_enc}&w=600&h=800&c=7&rs=1&p=0")

    urls_validas = []
    primeira_img = None

    for u in urls_candidatas:
        b = baixar_bytes(u)
        if b:
            urls_validas.append(u)
            if primeira_img is None:
                primeira_img = b

    return primeira_img, urls_validas

@st.cache_data(ttl=3600, show_spinner=False)
def buscar_bandeira_universal(nome_pais: str) -> bytes | None:
    chave = normalizar(nome_pais)
    codigo = ISO_RAPIDO.get(chave)

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

    q_flag = requests.utils.quote(f"bandeira oficial {nome_pais} flag")
    return baixar_bytes(f"https://tse1.mm.bing.net/th?q={q_flag}&w=640&h=420&c=7&rs=1")

# ================= INTERFACE =================
st.title("⚽ Buscador 3x4 (Rosto Frontal) & Bandeiras")
st.markdown("Cole qualquer lista de jogadores e bandeiras abaixo (separados ou tudo junto na primeira caixa).")

col1, col2 = st.columns(2)

with col1:
    txt_jogadores = st.text_area(
        "👤 Caixa de Jogadores (ou cole a lista completa aqui):",
        height=280,
        placeholder="Ex:\nJogadores (28)\n1. Rodri\n2. Mbappé...\n\nBandeiras (17)\nEspanha, Argentina..."
    )

with col2:
    txt_bandeiras = st.text_area(
        "🏳️ Caixa de Bandeiras:",
        height=280,
        placeholder="Ex:\nEspanha, Argentina, Inglaterra, Brasil..."
    )

recorte_3x4 = st.checkbox("✂️ Padronizar fotos dos jogadores em 3x4 (600x800px)", value=True)

if st.button("🚀 Buscar Fotos Frontais e Gerar .ZIP", type="primary", use_container_width=True):
    lista_j, lista_b = separar_colagem_mista(txt_jogadores, txt_bandeiras)
    total = len(lista_j) + len(lista_b)

    if total == 0:
        st.warning("Cole pelo menos um jogador ou bandeira!")
    else:
        st.info(f"A processar **{len(lista_j)} jogadores** e **{len(lista_b)} bandeiras** ({total} imagens)...")
        barra = st.progress(0, text="A transferir retratos frontais...")

        res_j = [None] * len(lista_j)
        res_b = [None] * len(lista_b)
        feitos = 0

        with ThreadPoolExecutor(max_workers=8) as ex:
            fut_j = {ex.submit(buscar_jogador_olhando_camera, n): i for i, n in enumerate(lista_j)}
            fut_b = {ex.submit(buscar_bandeira_universal, p): i for i, p in enumerate(lista_b)}

            for f in fut_j:
                i = fut_j[f]
                img_b, urls = f.result()
                res_j[i] = {"nome": lista_j[i], "bytes": img_b, "urls": urls}
                st.session_state[f"op_jog_{i}"] = 0
                feitos += 1
                barra.progress(feitos / total, text=f"Concluído ({feitos}/{total}): {lista_j[i]}")

            for f in fut_b:
                i = fut_b[f]
                img_b = f.result()
                res_b[i] = {"nome": lista_b[i], "bytes": img_b}
                feitos += 1
                barra.progress(feitos / total, text=f"Concluído ({feitos}/{total}): {lista_b[i]}")

        barra.empty()
        st.session_state["res_j"] = res_j
        st.session_state["res_b"] = res_b

# ================= GALERIA E DOWNLOAD =================
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

    st.success(f"✅ Pacote pronto! **{cont_j}/{len(res_j)} jogadores** + **{cont_b}/{len(res_b)} bandeiras** = **{cont_j + cont_b} imagens**.")

    st.download_button(
        label=f"⬇️ BAIXAR TUDO EM .ZIP ({cont_j + cont_b} imagens)",
        data=zip_buffer.getvalue(),
        file_name="pacote_3x4_frontal.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )

    if res_j:
        st.subheader(f"👤 Jogadores ({cont_j}/{len(res_j)})")
        st.caption("Se quiser outro ângulo frontal de algum jogador, mude no seletor acima da foto que o ZIP atualiza sozinho.")
        cols = st.columns(6)
        for i, item in enumerate(res_j):
            with cols[i % 6]:
                if item["urls"]:
                    op = st.selectbox(
                        f"{i+1:02d}. {item['nome']}",
                        options=range(len(item["urls"])),
                        format_func=lambda x: f"Opção Frontal {x+1}",
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