# actualizar.py — genera docs/index.html (y docs/vista.png) con la cartera global y la comparativa del día. Lo ejecuta GitHub Actions todos los días a las 18:00
# (Buenos Aires). Es el mismo programa del cuaderno de Colab, sin la parte interactiva de Colab. Los pesos iniciales se editan abajo; otros símbolos van en activos.txt.
Peso_SPY = 60
Peso_QQQ = 25
Peso_BRK = 15
Otro_activo = ""

# =====================================================================================================
# CRITERIOS DE DISEÑO (leer antes de modificar; vigentes para cualquier mejora futura)
# Objetivo: ponderación económica final de una cartera SPY + QQQ + BRK desarmando cada una en sus empresas (descomposición recursiva).
# Forma:    una sola celda oculta (formulario) y una sola salida; la salida es una página HTML autosuficiente (datos embebidos, Plotly por CDN).
# Idioma:   castellano rioplatense, cero anglicismos en tablas y gráficos ("Efectivo", "Privados de BRK", "Resto", "Símbolo"); mayúscula solo inicial.
# Números:  asignaciones SPY/QQQ/BRK en enteros (60%); todo lo demás con un decimal (x.x%); punto decimal; nunca mezclar "pp" con "%".
# Valor:    no mostrar lo que no agrega valor ni repetir información (la fecha de consulta aparece una sola vez); sin títulos ni ejes redundantes.
# Selector: se fija SPY (QQQ y BRK se reparten el resto en su proporción); luego QQQ (solo se ajusta BRK; SPY no se toca); si se mueve BRK se ajustan
#           SPY y QQQ. Unidad mínima 1%. Siempre suma 100. Todo se recalcula en el navegador, sin volver a consultar las fuentes.
# Gráficos: Cartera global (asignación), Ponderación en la cartera (10 primeros por fuente, barras apiladas), Composición final (10 primeros + Resto).
#           Los 10 incluyen siempre "Efectivo" y "Privados de BRK". Colores: SPY #6FA3DB, QQQ #F5973A, BRK #6CBF6A. Nada recortado en ningún ancho.
# Cálculo:  aporte = peso en la fuente × asignación de la fuente; BRK dentro de SPY se reemplaza por la composición de BRK (sin doble conteo);
#           doble clase por símbolo canónico; cada fuente se reescala a 100%; "Privados de BRK" = capitalización − acciones − efectivo (residual,
#           no valuación contable); el efectivo de QQQ incluye futuros y colaterales de divisa; la cartera debe cerrar en 100% (assert).
# Datos:    sin valores estáticos de respaldo: si una fuente falla se informa cuál y por qué (nunca inventar ni aproximar con otra fuente).
#           SPY: archivo diario de State Street; QQQ: Invesco (CSV directo, Chrome con lectura de red, Playwright); BRK: CNBC (se reabre la
#           página y se espera a que cargue la tabla). Las tres consultas son independientes: se informa la fecha de dato de cada una.
# Fechas:   acciones de BRK = cantidades del último 13F (más excepciones informadas por CNBC) valuadas a precio de mercado del último cierre
#           hábil de la consulta (si es fin de semana, el viernes); efectivo = último balance trimestral; se verifica contra el TOTAL de CNBC.
# Eficiencia: descargas en paralelo, un solo navegador, sin recálculo en Python al mover selectores, JSON mínimo, tabla completa solo al abrirla.
# Publicación: GitHub Pages desde /docs; GitHub Actions regenera la página todos los días a las 18:00 (hora de Buenos Aires). Salida siempre en
#           modo nocturno (estética Claude: fondo carbón cálido #262624, texto crema #faf9f5, acento terracota #d97757, títulos en serif),
#           legible en pantallas anchas y en celulares, con presentación cuidada para lectores no técnicos.
# Comparativa: pestaña "Comparativa cuantitativa" en la misma página. Activos: SPY, QQQ, BRK (BRK-B en Yahoo), Cartera global y uno más (catálogo).
#           Cartera global = SPY/QQQ/BRK con los pesos del selector, rebalanceo trimestral sin fricciones. Siempre precios ajustados (retorno total).
#           Δ por defecto = Cartera global menos SPY, pero se elige cualquier par. Métricas: retorno total (0 dec.), rendimiento anual, volatilidad anual y
#           negativa, distancia al máximo (1 dec.), máxima caída (0 dec.), rendimiento/volatilidad, correlación, beta y volumen promedio de 3 meses.
#           Botones: Establecer (guarda en el navegador), Portafolio (SPY+QQQ+BRK+Cartera global, Δ vs SPY), Vacío (solo el par del Δ).
#           Los precios se descargan en cada ejecución (diaria, 18:00) y se embeben; la página estática no consulta Yahoo: otros símbolos se agregan en
#           activos.txt del repositorio (o en el parámetro Otro_activo de Colab). El selector y la comparativa guardan su estado con "Establecer".
# Interfaz: arriba solo lo esencial (selector + 3 gráficos); Metodología, Tabla completa y Negocios privados de BRK van abajo, colapsados. Gráficos sin
#           zoom ni arrastre de ejes (eje fijo, nunca valores negativos de ponderación).
# =====================================================================================================

import asyncio, glob, importlib.util, io, json, os, re, subprocess, sys, time, warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import StringIO
import numpy as np, pandas as pd, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
try: from IPython.display import HTML, display, clear_output
except ImportError: HTML = display = clear_output = None   # fuera de Jupyter no se usan
warnings.filterwarnings("ignore")

# ---------- constantes y utilidades ----------
UNIF = {"GOOGL": "GOOG", "GOOG": "GOOG", "FOXA": "FOX", "FOX": "FOX", "NWSA": "NWS", "NWS": "NWS", "BRKB": "BRK", "BRKA": "BRK"}
EFEC = {"CASH_USD", "CASH", "USD", "CASH_GLOBAL"}
TECNICOS = {"Index Future", "Currency Collateral", "Synthetic Cash", "Currency"}
KT = ["ticker", "symbol", "securityticker", "securitysymbol"]
KP = ["percentageoftotalnetassets", "weight", "weightpct", "percentoffund", "percentage", "percent"]
KN = ["issuername", "securityname", "companyname", "name", "company"]
KY = ["securitytypename", "securitytype", "assettype", "type"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
BLOQ = ["doubleclick", "googlesyndication", "google-analytics", "googletagmanager", "adsafeprotected", "moatads", "scorecardresearch", "facebook.net", "adnxs", "amazon-adsystem", "criteo", "taboola", "outbrain", "chartbeat", "permutive"]
AHORA = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
FMT_ASOF = r"(\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})"

def canon(x):
    t = str(x).upper().strip().split("/")[0].split(".")[0]
    return "EFECTIVO" if (t in EFEC or t in ("", "NAN", "NONE")) else UNIF.get(t, t)

def iso(x):
    t = pd.to_datetime(str(x).strip()[:30], errors="coerce")
    return None if pd.isna(t) else t.strftime("%Y-%m-%d")

def dmy(s): return "s/d" if not s else datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
def nk(x): return re.sub(r"[^a-z0-9]", "", str(x).lower())

def col(df, claves):
    m = {nk(c): c for c in df.columns}
    for k in claves:
        if k in m: return m[k]
    for c in df.columns:
        if any(k in nk(c) for k in claves): return c
    return None

def buscar(o):  # busca recursivamente la lista de posiciones (ticker + peso) dentro de un JSON
    c = []
    if isinstance(o, list):
        if len(o) >= 5 and all(isinstance(x, dict) for x in o[:10]):
            for m in o[:10]:
                k = {nk(a) for a in m}
                if k & set(KT) and k & set(KP): c.append(o); break
        for i in o:
            r = buscar(i)
            if r: c.append(r)
    elif isinstance(o, dict):
        for v in o.values():
            r = buscar(v)
            if r: c.append(r)
    return max(c, key=len) if c else None

def fjson(o):
    if isinstance(o, dict):
        for k, v in o.items():
            n = nk(k)
            if v and not isinstance(v, (dict, list)) and (("effective" in n and "date" in n) or "asofdate" in n or n in ("date", "holdingsdate", "valuationdate")): return str(v)
        for v in o.values():
            r = fjson(v)
            if r: return r
    elif isinstance(o, list):
        for v in o:
            r = fjson(v)
            if r: return r

def fasof(txt):  # fechas precedidas por 'as of' en un texto
    return [d for d in (iso(m) for m in re.findall(r"as of[:\s]+" + FMT_ASOF, txt or "", re.I)) if d]

# ---------- descargas (única parte con red) ----------
def spy_bytes():
    H = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.ssga.com/us/en/intermediary/etfs/spdr-sp-500-etf-trust-spy"}
    s = requests.Session(); s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
    pre = "https://www.ssga.com/us/en/"; fin = "library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
    for u in (pre + "intermediary/" + fin, pre + "individual/" + fin, pre + "institutional/etfs/" + fin, "https://www.ssga.com/" + fin):
        try:
            r = s.get(u, headers=H, timeout=30)
            if r.status_code == 200 and len(r.content) > 10000 and r.content[:2] == b"PK": return r.content
        except requests.RequestException: pass
    raise RuntimeError("SSGA no entregó un .xlsx válido (posible bloqueo de IP o cambio de ruta).")

def pw_listo():
    if importlib.util.find_spec("playwright") is None:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
    if not glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*")):
        subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True, capture_output=True)

async def contexto(nav):
    c = await nav.new_context(user_agent=UA)
    async def bloquear(route):
        r = route.request
        if r.resource_type in ("image", "media", "font") or any(d in r.url for d in BLOQ): return await route.abort()
        await route.continue_()
    await c.route("**/*", bloquear)
    return c

def tabla_dom(html):  # respaldo: tabla de posiciones renderizada en la página de Invesco
    for t in pd.read_html(StringIO(html)):
        cp, ct, cn = col(t, KP), col(t, KT), col(t, KN)
        if cp and (ct or cn) and len(t) >= 50:
            d = pd.DataFrame({"Ticker": t[ct].astype(str) if ct else t[cn].astype(str).str.extract(r"\(([A-Z.]{1,6})\)")[0].fillna(""),
                              "Empresa": t[cn].astype(str) if cn else "", "Tipo": "", "Weight": pd.to_numeric(t[cp].astype(str).str.replace(r"[%,]", "", regex=True), errors="coerce")})
            return d
    return None

async def qqq_web(nav):
    ctx = await contexto(nav); hits = []; pg = await ctx.new_page()
    async def on_resp(r):
        try:
            if "json" in r.headers.get("content-type", "").lower():
                d = await r.json(); h = buscar(d)
                if h and len(h) >= 50: hits.append((len(h), h, fjson(d)))
        except Exception: pass
    pg.on("response", on_resp)
    try:
        for url in ("https://www.invesco.com/qqq-etf/en/about.html", "https://www.invesco.com/qqq-etf/en/home.html", "https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html"):
            try:
                await pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                await pg.wait_for_timeout(2500)
                for rx in (r"accept|agree|allow", r"all (qqq )?holdings|view all"):
                    for rol in ("button", "link"):
                        try: await pg.get_by_role(rol, name=re.compile(rx, re.I)).first.click(timeout=1500); await pg.wait_for_timeout(1500)
                        except Exception: pass
                for _ in range(5): await pg.mouse.wheel(0, 900); await pg.wait_for_timeout(500)
                for _ in range(40):
                    if hits: break
                    await pg.wait_for_timeout(500)
                texto = await pg.locator("body").inner_text()
                fd = (fasof(texto) or [None])[0]
                if hits:
                    n, h, f = max(hits, key=lambda x: x[0])
                    return hold_df(h), iso(f) or fd
                d = tabla_dom(await pg.content())
                if d is not None: return d, fd
            except Exception: pass
        raise RuntimeError("no se pudieron obtener las posiciones de QQQ desde invesco.com")
    finally: await ctx.close()

async def brk_web(nav):
    err, parcial = None, None
    espera = "() => { const t = document.body.innerText; return /Berkshire Cash/i.test(t) && /Market Capitali[sz]ation/i.test(t) && document.querySelectorAll('table tr').length > 25; }"
    for i in range(4):                                   # cada intento reabre la página en un contexto nuevo
        ctx = await contexto(nav); pg = await ctx.new_page()
        try:
            await pg.goto("https://www.cnbc.com/berkshire-hathaway-portfolio/", wait_until="domcontentloaded", timeout=45000)
            try: await pg.locator("#onetrust-accept-btn-handler").click(timeout=3000)
            except Exception: pass
            await pg.wait_for_selector("table", timeout=25000, state="attached")
            for _ in range(4): await pg.mouse.wheel(0, 1200); await pg.wait_for_timeout(600)
            async def leer(): return await pg.locator("table").evaluate_all("t => t.map(x => x.outerHTML)"), await pg.locator("body").inner_text() + "\n" + (await pg.evaluate("document.body.textContent") or "")
            parcial = await leer()
            await pg.wait_for_function(espera, timeout=30000)   # tabla completa y líneas de balance cargadas
            return await leer()
        except Exception as e: err = e
        finally: await ctx.close()
        await asyncio.sleep(2 * (i + 1))
    if parcial: return parcial                           # último recurso: proc_brk valida y explica qué falta
    raise RuntimeError(f"CNBC no entregó la tabla de Berkshire: {err}")

async def subs_web(nav):
    ctx = await contexto(nav); pg = await ctx.new_page()
    try:
        await pg.goto("https://berkshirehathaway.com/subs/sublinks.html", wait_until="networkidle", timeout=45000)
        await pg.wait_for_selector("a[href^='http']", timeout=25000, state="attached")
        return await pg.locator("a[href^='http']").evaluate_all("els => els.map(e => ({texto: e.innerText.trim(), href: e.href}))")
    finally: await ctx.close()

LANDINGS = ("https://www.invesco.com/qqq-etf/en/about.html", "https://www.invesco.com/qqq-etf/en/home.html", "https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html")

def hold_df(h):  # lista JSON de posiciones -> tabla estándar
    df = pd.json_normalize(h); ct, cp, cn, cy = col(df, KT), col(df, KP), col(df, KN), col(df, KY)
    if not (ct and cp): raise RuntimeError(f"JSON sin columnas de símbolo/peso: {list(df.columns)}")
    return pd.DataFrame({"Ticker": df[ct], "Empresa": df[cn] if cn else "", "Tipo": df[cy] if cy else "", "Weight": df[cp]})

def qqq_csv():  # intento 1: descarga directa del CSV oficial de posiciones
    u = "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ"
    r = requests.get(u, headers={"User-Agent": UA, "Referer": LANDINGS[0]}, timeout=20)
    if r.status_code != 200 or len(r.content) < 2000: raise RuntimeError(f"HTTP {r.status_code}")
    df = pd.read_csv(io.StringIO(r.text)); ct, cp, cn, cf = col(df, ["holdingticker"] + KT), col(df, KP), col(df, ["name"] + KN), col(df, ["date", "asofdate"])
    if not (ct and cp) or len(df) < 50: raise RuntimeError("CSV sin la estructura esperada")
    tk = df[ct].fillna("").astype(str).str.strip()
    out = pd.DataFrame({"Ticker": tk, "Empresa": df[cn] if cn else "", "Tipo": np.where(tk.isin(["", "-", "nan"]), "Currency", ""), "Weight": df[cp]})
    return out, iso(df[cf].iloc[0]) if cf else None

def chrome_listo():
    if importlib.util.find_spec("selenium") is None: subprocess.run([sys.executable, "-m", "pip", "install", "-q", "selenium"], check=True)
    if not os.path.exists("/usr/bin/google-chrome"):
        subprocess.run(["bash", "-c", "wget -q -O /tmp/gc.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && apt-get update -qq && apt-get install -y -qq /tmp/gc.deb"], check=True, capture_output=True)

def qqq_selenium():  # intento 2: Chrome real + lectura de las respuestas JSON de red (método que ya funcionó)
    chrome_listo()
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    o = Options(); o.binary_location = "/usr/bin/google-chrome"
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-extensions", "--window-size=1920,1080", "--lang=en-US", "--user-data-dir=/tmp/selenium-qqq-profile"): o.add_argument(a)
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    d = webdriver.Chrome(service=Service(), options=o); errs = []
    def clic(textos):
        for t in textos:
            try:
                for e in d.find_elements(By.XPATH, f"//*[self::button or self::a][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{t}')]"):
                    try:
                        if e.is_displayed():
                            d.execute_script("arguments[0].scrollIntoView({block:'center'});", e); time.sleep(1)
                            d.execute_script("arguments[0].click();", e); time.sleep(3); return True
                    except Exception: pass
            except Exception: pass
        return False
    try:
        try: d.execute_cdp_cmd("Network.enable", {})
        except Exception: pass
        for url in LANDINGS:
            try:
                try: d.get_log("performance")
                except Exception: pass
                d.get(url); time.sleep(8)
                clic(("accept all", "accept", "i agree", "allow all")); clic(("view all holdings", "all qqq holdings", "all holdings", "holdings"))
                for _ in range(5): d.execute_script("window.scrollBy(0, Math.floor(window.innerHeight*0.8));"); time.sleep(1)
                time.sleep(8); hits = []
                for e in d.get_log("performance"):
                    try: m = json.loads(e["message"])["message"]
                    except Exception: continue
                    if m.get("method") != "Network.responseReceived": continue
                    p = m["params"]; r = p.get("response", {}); u = r.get("url", "").lower()
                    if not ("json" in r.get("mimeType", "").lower() or "api" in u or "graphql" in u or "hold" in u): continue
                    try:
                        dj = json.loads(d.execute_cdp_cmd("Network.getResponseBody", {"requestId": p["requestId"]}).get("body", ""))
                        h = buscar(dj)
                        if h: hits.append((len(h), h, fjson(dj)))
                    except Exception: continue
                txt = d.find_element(By.TAG_NAME, "body").text; fd = (fasof(txt) or [None])[0]
                if hits:
                    n, h, f = max(hits, key=lambda x: x[0]); return hold_df(h), iso(f) or fd
                dom = tabla_dom(d.page_source)
                if dom is not None: return dom, fd
                errs.append(f"{url}: sin JSON ni tabla")
            except Exception as e: errs.append(f"{url}: {type(e).__name__}")
        raise RuntimeError("; ".join(errs))
    finally: d.quit()

async def qqq_total(nav, loop):
    errs = []
    for nombre, fn in (("descarga directa", qqq_csv), ("Chrome", qqq_selenium)):
        try: return await loop.run_in_executor(None, fn)
        except Exception as e: errs.append(f"{nombre}: {e}")
    try: return await qqq_web(nav)
    except Exception as e: errs.append(f"Playwright: {e}")
    raise RuntimeError(" | ".join(errs))

async def traer():
    pw_listo()
    from playwright.async_api import async_playwright
    loop = asyncio.get_running_loop()
    async with async_playwright() as p:
        nav = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try: r = await asyncio.gather(loop.run_in_executor(None, spy_bytes), qqq_total(nav, loop), brk_web(nav), subs_web(nav), return_exceptions=True)
        finally: await nav.close()
    for n, x in zip(("SPY (State Street)", "QQQ (Invesco)", "BRK (CNBC)"), r[:3]):
        if isinstance(x, Exception): raise RuntimeError(f"{n}: {x}")
    return dict(spy=r[0], qqq=r[1], brk=r[2], subs=None if isinstance(r[3], Exception) else r[3], subs_err=str(r[3]) if isinstance(r[3], Exception) else "")

# ---------- procesamiento puro (sin red) ----------
def proc_spy(b):
    raw = pd.read_excel(io.BytesIO(b), header=None)
    fecha = next((iso(m.group(1)) for v in raw.head(12).to_numpy().ravel() for m in [re.search(r"As\s+of\s+(\d{1,2}-[A-Za-z]{3}-\d{2,4})", str(v), re.I)] if m), None)
    h = next(i for i in range(min(20, len(raw))) if "Ticker" in set(raw.iloc[i].astype(str).str.strip()))
    df = raw.iloc[h + 1:].copy(); df.columns = raw.iloc[h].astype(str).str.strip()
    df = df[df["Ticker"].notna()].copy(); df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Name"] = df["Name"].fillna("").astype(str).str.strip(); df["Weight"] = pd.to_numeric(df["Weight"], errors="coerce"); df = df.dropna(subset=["Weight"])
    cash = df["Name"].str.upper().eq("US DOLLAR"); raro = df["Ticker"].str.match(r"^(\d|-)")  # CVR/instrumentos no accionarios
    emp = df[~cash & ~raro].copy(); emp["T"] = emp["Ticker"].map(canon)
    return dict(w=emp.groupby("T")["Weight"].sum(), n=emp.groupby("T")["Name"].first(), ef=df.loc[cash, "Weight"].sum(), raro=df.loc[raro, "Weight"].sum(),
                bruto=df["Weight"].sum(), fecha=fecha, lineas=len(emp))

def proc_qqq(df, fecha):
    df = df.copy(); df["Weight"] = pd.to_numeric(df["Weight"].astype(str).str.replace(r"[%,]", "", regex=True), errors="coerce"); df = df.dropna(subset=["Weight"])
    for c in ("Ticker", "Empresa", "Tipo"): df[c] = df[c].fillna("").astype(str).str.strip()
    df["Ticker"] = df["Ticker"].str.upper()
    # efectivo: instrumentos técnicos o líneas cuyo nombre ES dólar/efectivo (anclado: no confundir con empresas que contienen "Dollar")
    ef = df["Tipo"].isin(TECNICOS) | df["Ticker"].isin(EFEC) | df["Empresa"].str.upper().str.match(r"^(U\.?S\.?\s+)?(DOLLAR|CASH)|^USD\b")
    emp = df[~ef].copy(); emp["T"] = emp["Ticker"].map(canon)
    return dict(w=emp.groupby("T")["Weight"].sum(), n=emp.groupby("T")["Empresa"].first(), ef=df.loc[ef, "Weight"].sum(), bruto=df["Weight"].sum(), fecha=fecha, lineas=len(emp))

def proc_brk(htmls, cuerpo):
    dfs = []
    for h in htmls:
        try: dfs.extend(pd.read_html(StringIO(h)))
        except Exception: pass
    if not dfs: raise RuntimeError("tablas de CNBC ilegibles")
    dfs.sort(key=len, reverse=True); df = dfs[0]; df.columns = [str(c).strip() for c in df.columns]
    if not {"Company", "Symbol", "Value"} <= set(df.columns): raise RuntimeError(f"columnas inesperadas en CNBC: {list(df.columns)}")
    for c in df.columns:
        if c not in ("Company", "Symbol"): df[c] = pd.to_numeric(df[c].astype(str).str.replace(r"[$,%]", "", regex=True), errors="coerce")
    df = df.dropna(subset=["Company"]); df["Symbol"] = df["Symbol"].astype(str).str.strip(); df.loc[df["Symbol"].isin(["nan", "None"]), "Symbol"] = ""
    tr = df[df["Company"].astype(str).str.strip().str.upper().eq("TOTAL")]; total_cnbc = float(tr["Value"].iloc[0]) if len(tr) else None
    emp = df[df["Symbol"].str.match(r"^[A-Z0-9][A-Z0-9.:\-]{0,11}$") & (df["Symbol"] != "TOTAL") & df["Value"].notna()].copy(); pub = emp["Value"].sum()   # solo filas con símbolo válido
    UN = r"(trillion|billion|million)"; esc = {"trillion": 1e12, "billion": 1e9, "million": 1e6}
    def diag():
        ls = [l.strip()[:140] for l in cuerpo.splitlines() if re.search(r"cash|capitali", l, re.I) and l.strip()][:8]
        return " Líneas halladas en la página: " + (" || ".join(ls) if ls else "ninguna con 'cash' o 'capitalization'") + "."
    mc = re.search(r"Berkshire Cash[^\$]*\$\s*([\d,]+(?:\.\d+)?)\s*" + UN, cuerpo, re.I)          # efectivo bruto (balance trimestral)
    if not mc: raise RuntimeError("no se pudo leer el efectivo de Berkshire en CNBC." + diag())
    cash = float(mc.group(1).replace(",", "")) * esc[mc.group(2).lower()]
    f = re.search(r"as of\s+" + FMT_ASOF, mc.group(0), re.I); fc = iso(f.group(1)) if f else None
    mn = re.search(r"Excluding Rail Cash[^\$]*\$\s*([\d,]+(?:\.\d+)?)\s*" + UN, cuerpo, re.I)   # efectivo neto (sin BNSF, menos letras a pagar)
    cash_neto = float(mn.group(1).replace(",", "")) * esc[mn.group(2).lower()] if mn else None
    m2 = re.search(r"Berkshire Market Capitali[sz]ation:?[^\$]{0,40}\$\s*([\d,]+(?:\.\d+)?)", cuerpo, re.I)
    if not m2: raise RuntimeError("no se pudo leer la capitalización de mercado de Berkshire en CNBC." + diag())
    cap = float(m2.group(1).replace(",", ""))
    if cap <= pub + cash: raise RuntimeError(f"inconsistencia: capitalización {cap:,.0f} <= acciones {pub:,.0f} + efectivo {cash:,.0f}")
    # fechas de las posiciones: 13F base y excepciones con fecha propia, tal como las informa CNBC
    mh = re.search(r"Holdings are as of\s+([A-Za-z]+ \d{1,2}, \d{4}).{0,200}?13F filing on\s+([A-Za-z]+ \d{1,2}, \d{4})", cuerpo, re.I | re.S)
    f13, f13p = (iso(mh.group(1)), iso(mh.group(2))) if mh else (None, None)
    seg = re.search(r"except for:(.*?)For more on", cuerpo, re.I | re.S); seg = seg.group(1) if seg else cuerpo
    exc = [(n.strip(), iso(d)) for n, d in re.findall(r"([A-Z][\w’'&.\- ]{1,30}?)\s*(?:and [^,\n]+?)?\s*,\s*which (?:is|are)(?: [^,]*?)? as of\s+([A-Za-z]+ \d{1,2}, \d{4})", seg)]
    emp["P"] = emp["Value"] / cap * 100; emp["T"] = emp["Symbol"].map(canon)
    return dict(w=emp.groupby("T")["P"].sum(), n=emp.groupby("T")["Company"].first(), ef=cash / cap * 100, pv=(cap - pub - cash) / cap * 100,
                fecha_efectivo=fc, f13=f13, f13p=f13p, exc=exc, cap=cap, pub=pub, cash=cash, cash_neto=cash_neto, total_cnbc=total_cnbc, lineas=len(emp))

def armar(S, Q, B, subs, subs_err):
    kS, kQ = 100 / (S["w"].sum() + S["ef"]), 100 / (Q["w"].sum() + Q["ef"])   # cada fuente se reescala a 100% (brecha de origen mínima)
    sw, sef = S["w"] * kS, S["ef"] * kS; qw, qef = Q["w"] * kQ, Q["ef"] * kQ
    bs = float(sw.get("BRK", 0.0)); sw = sw.drop("BRK", errors="ignore")                      # BRK dentro de SPY se reemplaza por su composición
    qw = qw.drop("BRK", errors="ignore"); bw = B["w"].drop("BRK", errors="ignore")
    T = sorted(set(sw.index) | set(qw.index) | set(bw.index))
    nom = {}
    for n in (S["n"], B["n"], Q["n"]): nom.update(n.to_dict())
    r6 = lambda x: round(float(x), 7)
    D = dict(t=T, n=[str(nom.get(t, t)) for t in T], s=[r6(sw.get(t, 0)) for t in T], q=[r6(qw.get(t, 0)) for t in T], b=[r6(bw.get(t, 0)) for t in T],
             bs=r6(bs), cs=r6(sef), cq=r6(qef), cb=r6(B["ef"]), bp=r6(B["pv"]))
    vistos, lst = set(), []
    for e in subs or []:
        n, h = (e["texto"] or "").strip(), e["href"]; dom = re.sub(r"^https?://(www\.)?", "", h).split("/")[0].lower()
        if n and "berkshirehathaway.com" not in dom and (n.lower(), dom) not in vistos: vistos.add((n.lower(), dom)); lst.append([n, h])
    gap = dict(S=100 - S["bruto"], Q=100 - Q["bruto"], raro=S.get("raro", 0.0))
    return D, lst, gap

GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH, GITHUB_FILE = "maurosimeonoff", "Finanzas", "main", "docs/index.html"
URL_WEB = f"https://{GITHUB_OWNER}.github.io/{GITHUB_REPO}/"

def ult_cierre():  # último día hábil (sin considerar feriados de EE.UU.): hoy si es lunes a viernes, si no el viernes anterior
    d = AHORA.date()
    while d.weekday() >= 5: d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def ant(dato, umbral=None):
    if not dato: return ""
    n = (AHORA.date() - datetime.strptime(dato, "%Y-%m-%d").date()).days
    return f' <span class="w">· {n} d: verificar</span>' if umbral and n > umbral else f" · {n} d"

def enteros(v):  # reparte 100 en enteros (método del mayor resto)
    v = np.array(v, float); v = v / v.sum() * 100; f = np.floor(v)
    for i in np.argsort(-(v - f))[:int(round(100 - f.sum()))]: f[i] += 1
    return [int(x) for x in f]

def pagina(frag):  # envoltorio para publicar como página web independiente
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Cartera global: SPY + QQQ + BRK</title><style>body{margin:0;background:#1f1e1d;padding:18px 10px}</style></head><body>' + frag + '</body></html>')

def publicar_github(html):  # opcional en Colab: sube la página al repositorio con el secreto GH_TOKEN
    from google.colab import userdata
    import base64
    tk = userdata.get("GH_TOKEN")
    u = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    H = {"Authorization": f"Bearer {tk}", "Accept": "application/vnd.github+json"}
    r = requests.get(u, headers=H, params={"ref": GITHUB_BRANCH}, timeout=30)
    cuerpo = {"message": "Actualización desde Colab", "branch": GITHUB_BRANCH, "content": base64.b64encode(html.encode("utf-8")).decode("ascii")}
    if r.status_code == 200: cuerpo["sha"] = r.json()["sha"]
    requests.put(u, headers=H, json=cuerpo, timeout=60).raise_for_status()
    return True

BASE = ["SPY", "QQQ", "BRK-B"]
ETFS_EXTRA = ["IWM", "EFA", "EEM", "TLT", "GLD", "VNQ"]
NOMBRES_ETF = {"SPY": "State Street SPDR S&P 500 ETF Trust", "QQQ": "Invesco QQQ Trust, Series 1", "BRK-B": "Berkshire Hathaway Inc. (Clase B)",
               "IWM": "iShares Russell 2000 ETF", "EFA": "iShares MSCI EAFE ETF", "EEM": "iShares MSCI Emerging Markets ETF",
               "TLT": "iShares 20+ Year Treasury Bond ETF", "GLD": "SPDR Gold Shares", "VNQ": "Vanguard Real Estate ETF"}

def leer_extras():  # símbolos adicionales: activos.txt (uno por línea, # comenta) y el parámetro Otro_activo de Colab
    ex = []
    if os.path.exists("activos.txt"):
        for l in open("activos.txt", encoding="utf-8"):
            l = l.split("#")[0].strip().upper()
            if l: ex.append(l)
    if (Otro_activo or "").strip(): ex.append(Otro_activo.strip().upper())
    return list(dict.fromkeys(ex))

def bajar_precios(tks, nombres, extras):  # precios ajustados diarios desde Yahoo Finance, alineados al calendario de SPY
    yf = _yf()
    df = yf.download(tks, period="max", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
    cols = set(df.columns.get_level_values(0))
    if "SPY" not in cols: raise RuntimeError("Yahoo Finance no entregó datos de SPY")
    def serie(t):
        x = df[t]; p = (x["Adj Close"] if "Adj Close" in x else x["Close"]).dropna()
        p.index = pd.to_datetime(p.index).tz_localize(None).normalize(); p = p[~p.index.duplicated(keep="last")]
        return x, p[p > 0]
    cal = serie("SPY")[1].index; A, M = {}, {}
    for t in tks:
        if t not in cols: continue
        x, p = serie(t)
        if len(p) < 30: continue
        s = p.reindex(p.index.union(cal)).ffill().reindex(cal)
        i0 = int(np.argmax(s.notna().to_numpy()))
        if t not in BASE: i0 = max(i0, len(cal) - 3000)           # extras: hasta ~12 años para acotar el tamaño
        v = s.iloc[i0:].dropna(); i0 = len(cal) - len(v)
        dv = (x["Close"] * x["Volume"]).dropna().tail(60).mean() / 1e6 if "Volume" in x else np.nan
        nom, mon = nombres.get(t), "USD"
        if t in extras:                                           # símbolos agregados por el usuario: mejor esfuerzo para nombre y moneda
            try:
                tk = yf.Ticker(t); mon = tk.fast_info["currency"] or "s/d"; nom = nom or tk.info.get("longName") or tk.info.get("shortName")
            except Exception: mon = "s/d"
        A[t] = {"s": i0, "v": np.round(v.to_numpy(), 3).tolist()}
        M[t] = {"n": nom or t, "c": mon, "v": None if not np.isfinite(dv) else round(float(dv), 0), "w": "índice de precios: no incluye dividendos" if t.startswith("^") else ""}
    return {"f": [d.strftime("%Y-%m-%d") for d in cal], "a": A, "m": M}

# ---------- salida ----------
HTML_T = r'''
<style>
#w{--bg:#262624;--sf:#30302e;--bd:#3d3d3a;--tx:#faf9f5;--t2:#c2c0b6;--t3:#9a988f;--ac:#d97757;color-scheme:dark;font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--tx);background:var(--bg);padding:18px 22px 14px;box-sizing:border-box;width:100%;max-width:1500px;margin:0 auto;border-radius:14px}
#w *{box-sizing:border-box}
#w h1{font:500 27px/1.15 "Iowan Old Style","Palatino Linotype",Georgia,"Times New Roman",serif;margin:0 0 4px;letter-spacing:-.3px;color:var(--tx)!important}
#w h2{font-size:12px;margin:22px 0 8px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--t3)!important}
#w .sub{font-size:12.5px;color:var(--t3);margin-bottom:12px}
.ctl{display:flex;gap:22px;align-items:center;flex-wrap:wrap;background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:10px 16px}
.ctl .it{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:650}
.ctl input[type=range]{width:160px;accent-color:var(--ac)}
.ctl input[type=number]{width:58px;padding:4px 6px;border:1px solid var(--bd);border-radius:7px;font-size:13px;background:#1f1e1d!important;color:var(--tx)!important}
.ctl button{font-size:12px;border:1px solid var(--bd);background:var(--bg)!important;color:var(--t2)!important;border-radius:7px;padding:5px 12px;cursor:pointer}
.ctl button:hover{border-color:var(--ac);color:var(--tx)!important}
.gr{display:grid;grid-template-columns:minmax(200px,23%) minmax(0,1fr) minmax(280px,31%);gap:10px;margin-top:14px;background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:14px 10px 8px}
.gr h3{font:500 16px/1.2 "Iowan Old Style","Palatino Linotype",Georgia,serif;margin:0;text-align:center;color:var(--tx)!important}
.gr p{font-size:12px;color:var(--t3);margin:2px 0 0;text-align:center}
@media(max-width:980px){.gr{grid-template-columns:1fr}}
.g2{display:grid;grid-template-columns:1fr 1.4fr;gap:26px}@media(max-width:980px){.g2{grid-template-columns:1fr}}
#w table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums;background:transparent;color:var(--tx)}
#w th{text-align:right;padding:6px 8px;border-bottom:1px solid var(--ac);background:var(--bg);position:sticky;top:0;font-weight:650;color:var(--tx)}
#w td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--bd);color:var(--t2)}
#w .tf th:nth-child(-n+3),#w .tf td:nth-child(-n+3),#w .kp td:first-child,#w .kp th:first-child{text-align:left}
#w .kp td:first-child{white-space:nowrap;color:var(--tx)}#w .kp td:nth-child(2),#w .kp td:nth-child(3){text-align:left}#w .kp.n td:nth-child(2){text-align:right}
#w .tf td b{color:var(--tx)}
.sc{max-height:440px;overflow:auto;border:1px solid var(--bd);border-radius:10px}
.sb{columns:3 230px;column-gap:26px;font-size:12px;line-height:1.6;color:var(--t2)}.sb div{break-inside:avoid}.sb a{color:var(--ac);text-decoration:none}.sb a:hover{text-decoration:underline}
.w{color:#f0867a}.nt{font-size:11px;color:var(--t3);line-height:1.55;margin-top:18px;border-top:1px solid var(--bd);padding-top:10px}
.S{color:#6FA3DB}.Q{color:#F5973A}.B{color:#6CBF6A}.S,.Q,.B{font-weight:650}
details>summary{cursor:pointer;font-size:12px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;margin:22px 0 8px;color:var(--t3)}details>summary:hover{color:var(--tx)}

.tabs{display:flex;gap:8px;margin:0 0 16px}
.tabs button{font:600 13px Inter,system-ui,sans-serif;padding:7px 18px;border-radius:999px;border:1px solid var(--bd);background:transparent!important;color:var(--t2)!important;cursor:pointer}
.tabs button.on{background:var(--ac)!important;border-color:var(--ac);color:#1f1e1d!important}
.ctl select{background:#1f1e1d!important;color:var(--tx)!important;border:1px solid var(--bd);border-radius:7px;padding:4px 6px;font-size:12.5px;max-width:190px}
.ctl label.it{font-weight:600;color:var(--t2)}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:650;padding:4px 11px;border:1px solid var(--bd);border-radius:999px;cursor:pointer;margin-right:6px}
.chip input{accent-color:var(--ac)}
.cmp{display:grid;grid-template-columns:fit-content(58%) minmax(0,1fr);gap:14px;margin-top:14px}@media(max-width:1100px){.cmp{grid-template-columns:1fr}}
.cmp>div{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:10px 12px;overflow:auto}
#w .cmp th,#w .cmp td{white-space:nowrap}#w .cmp td:first-child,#w .cmp th:first-child{text-align:left}
.mt{border:1px solid var(--bd);border-radius:12px;padding:6px 18px 14px;background:var(--sf);font-size:12.5px;line-height:1.6;color:var(--t2)}
.mt h4{margin:18px 0 6px;padding-top:12px;border-top:1px solid var(--bd);font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ac);font-weight:650}.mt h4:first-child{border-top:0;padding-top:4px}
.mt ol,.mt ul{margin:4px 0 0;padding-left:20px}.mt li{margin:3px 0}.mt b{color:var(--tx)}
#w details>div.sb{margin-top:6px}
</style>
<div id="w">
<div class="tabs"><button id="tb1" class="on">Cartera global</button><button id="tb2">Comparativa cuantitativa</button></div>
<section id="p1">
<h1 id="tt"></h1><div class="sub" id="st"></div>
<div class="ctl">
 <div class="it S">SPY <input id="rS" type="range" min="0" max="100" step="1"><input id="nS" type="number" min="0" max="100" step="1">%</div>
 <div class="it Q">QQQ <input id="rQ" type="range" min="0" max="100" step="1"><input id="nQ" type="number" min="0" max="100" step="1">%</div>
 <div class="it B">BRK <input id="rB" type="range" min="0" max="100" step="1"><input id="nB" type="number" min="0" max="100" step="1">%</div>
 <button id="es" title="Guarda esta ponderación como base para las próximas consultas en este navegador">Establecer</button><button id="eq">Equiponderar</button>
</div>
<div class="gr">
 <div><h3>Cartera global</h3><p id="s1"></p><div id="g1"></div></div>
 <div><h3>Ponderación en la cartera</h3><p id="s2"></p><div id="g2"></div></div>
 <div><h3>Composición final consolidada</h3><p id="s3"></p><div id="g3"></div></div>
</div>
<details id="dt"><summary>Tabla completa de la cartera global</summary><div class="sc"><table class="tf" id="tf"></table></div></details>
<details id="dm"><summary>Metodología</summary><div class="mt">
 <h4>1 · Reconciliación de la cartera</h4><table class="kp" id="kp"></table>
 <h4>2 · Fuentes y fechas de los datos</h4><table class="kp">__FECHAS__</table>
 <h4>3 · Criterios de cálculo</h4>__CRITERIOS__
 <h4>4 · Controles y salvedades</h4>__SALVEDADES__
 <h4>5 · Comparativa cuantitativa</h4>__COMPARATIVA__
</div></details>
<details><summary>Negocios privados de Berkshire Hathaway: __NSUBS__</summary><div class="sb">__SUBS__</div></details>
</section>
<section id="p2" style="display:none">
<h1>Comparativa cuantitativa</h1><div class="sub" id="cs"></div>
<div class="ctl" id="cc">
 <span id="chips"></span>
 <label class="it">Otro <select id="cx"></select></label>
 <label class="it">Δ <select id="da"></select> menos <select id="db"></select></label>
 <label class="it"><input type="checkbox" id="lg" style="accent-color:#d97757"> Escala log</label>
 <button id="ce" title="Guarda esta comparativa como base para las próximas consultas en este navegador">Establecer</button><button id="cp">Portafolio</button><button id="cv">Vacío</button>
</div>
<div class="cmp" id="cmp"><div><h2 style="margin-top:2px">Estadísticos</h2><table id="ct"></table><div class="sub" id="cd" style="margin-top:8px"></div></div><div><div id="cch"></div></div></div>
<div class="nt" id="cf"></div>
</section>
</div>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
(function(){
const D=__DATA__,M=__META__,PX=__PX__,$=id=>document.getElementById(id);
if(typeof Plotly==='undefined'){$('g2').innerHTML='<p class="w">No se pudo cargar Plotly (requiere acceso a cdn.plot.ly).</p>';return;}
const LS={get:k=>{try{return JSON.parse(localStorage.getItem(k))}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));return true}catch(e){return false}}};
const CS={S:'#6FA3DB',Q:'#F5973A',B:'#6CBF6A'},BG='#30302e',PAL=['#6FA3DB','#F5973A','#6CBF6A','#E8706A','#6CC4BE','#C08BC4','#F2A7B8','#B08968','#E6C84F','#9C86D0','#8FD18F','#5CCBD8'],COL={'Efectivo':'#3FA372','Privados de BRK':'#8b8a85','Resto':'#4f4e49'};
let w=(()=>{const s=LS.get('cg_pesos_v1');return s&&[s.S,s.Q,s.B].every(x=>Number.isInteger(x)&&x>=0)&&s.S+s.Q+s.B===100?{S:s.S,Q:s.Q,B:s.B}:{S:M.w[0],Q:M.w[1],B:M.w[2]};})(),cn=0;
const col=l=>COL[l]||(COL[l]=PAL[cn++%PAL.length]);
const p1=v=>(Math.abs(v)<5e-10?0:v).toFixed(1)+'%',p2=v=>v>1e-10?v.toFixed(2)+'%':'—';
const H=Math.max(340,Math.min(560,Math.round($('w').clientWidth*.34)));
['g1','g2','g3'].forEach(i=>$(i).style.height=H+'px');
function calc(){
  const pb=w.B+w.S*D.bs/100,R=[];
  for(let i=0;i<D.t.length;i++){const S=w.S*D.s[i]/100,Q=w.Q*D.q[i]/100,B=pb*D.b[i]/100,T=S+Q+B;if(T>1e-10)R.push({t:D.t[i],l:D.t[i],n:D.n[i],S:S,Q:Q,B:B,T:T});}
  const E={t:'Efectivo',l:'Efectivo',n:'Efectivo y equivalentes',S:w.S*D.cs/100,Q:w.Q*D.cq/100,B:pb*D.cb/100},P={t:'Privados de BRK',l:'Privados de BRK',n:'Negocios privados de Berkshire (residual de valor de mercado)',S:0,Q:0,B:pb*D.bp/100};
  const acc=R.slice().sort((a,b)=>b.T-a.T),sp=[E,P];sp.forEach(x=>x.T=x.S+x.Q+x.B);
  const all=R.concat(sp.filter(x=>x.T>1e-10));all.sort((a,b)=>b.T-a.T||a.l.localeCompare(b.l));
  all.forEach(r=>r.k=(r.S>1e-10)+(r.Q>1e-10)+(r.B>1e-10));
  const on=sp.filter(x=>x.T>1e-10),sel=acc.slice(0,10-on.length).concat(on).sort((a,b)=>b.T-a.T);
  const tot=all.reduce((s,r)=>s+r.T,0),rest=tot-sel.reduce((s,r)=>s+r.T,0);
  return {pb,all,sel,tot,rest,nres:all.length-sel.length};
}
const cfg={displayModeBar:false,responsive:true,scrollZoom:false,doubleClick:false,showAxisDragHandles:false},L0={margin:{l:8,r:8,t:8,b:8},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',showlegend:false,dragmode:false,font:{size:12,color:'#c2c0b6'},hoverlabel:{bgcolor:'#1f1e1d',bordercolor:'#4a4944',font:{color:'#faf9f5',size:12}}};
const pie=(lb,vl,cl,t,rot,dom)=>({type:'pie',hole:.58,rotation:rot||0,domain:dom||{x:[0,1],y:[0,1]},labels:lb,values:vl,marker:{colors:cl,line:{color:BG,width:2}},sort:false,direction:'clockwise',automargin:true,
  texttemplate:'%{label}<br>%{value:.'+t+'f}%',textposition:'outside',hovertemplate:'%{label}: %{value:.1f}%<extra></extra>'});
function render(){
  const c=calc(),ov=c.all.filter(r=>r.k>1).length,n=[w.S,w.Q,w.B].filter(x=>x>0).length;
  $('tt').innerHTML='Cartera global: <span class="S">SPY '+w.S+'%</span> + <span class="Q">QQQ '+w.Q+'%</span> + <span class="B">BRK '+w.B+'%</span>';
  $('st').textContent=c.all.length+' activos · '+ov+' con solapamiento · consulta: '+M.consulta;
  $('s1').textContent=n+(n>1?' asignaciones':' asignación');
  $('s2').textContent=c.sel.length+' primeros activos';
  $('s3').textContent=c.nres?c.sel.length+' primeros y '+c.nres+' en resto':'todos los activos';
  const ks=['S','Q','B'].filter(k=>w[k]>0);
  Plotly.react('g1',[pie(ks.map(k=>({S:'SPY',Q:'QQQ',B:'BRK'}[k])),ks.map(k=>w[k]),ks.map(k=>CS[k]),0,0,{x:[.04,.96],y:[.04,.96]})],L0,cfg);
  const ys=c.sel.map(r=>r.l),mx=Math.max(...c.sel.map(r=>r.T)),tr=[];
  for(const k of ['S','Q','B'])tr.push({type:'bar',orientation:'h',name:{S:'SPY',Q:'QQQ',B:'BRK'}[k],x:c.sel.map(r=>r[k]),y:ys,marker:{color:CS[k]},customdata:c.sel.map(r=>r.n),
    hovertemplate:'%{customdata}<br>'+{S:'Vía SPY',Q:'Vía QQQ',B:'Vía BRK'}[k]+': %{x:.1f}%<extra></extra>'});
  tr.push({type:'scatter',mode:'text',x:c.sel.map(r=>r.T+mx*.015),y:ys,text:c.sel.map(r=>p1(r.T)),textposition:'middle right',textfont:{color:'#c2c0b6'},showlegend:false,hoverinfo:'skip',cliponaxis:false});
  Plotly.react('g2',tr,Object.assign({},L0,{barmode:'stack',margin:{l:8,r:36,t:8,b:28},
    xaxis:{ticksuffix:'%',gridcolor:'#3d3d3a',linecolor:'#3d3d3a',zeroline:false,range:[0,mx*1.16],fixedrange:true},
    yaxis:{autorange:'reversed',automargin:true,type:'category',ticks:'outside',ticklen:8,tickcolor:'rgba(0,0,0,0)',fixedrange:true}}),cfg);
  const lb=c.sel.map(r=>r.l).concat(c.rest>1e-9?['Resto']:[]),vl=c.sel.map(r=>r.T).concat(c.rest>1e-9?[c.rest]:[]);
  Plotly.react('g3',[pie(lb,vl,lb.map(col),1,75,{x:[.16,.84],y:[.1,.9]})],L0,cfg);
  const sum=k=>c.all.reduce((s,r)=>s+r[k],0),eff=c.all.find(r=>r.l==='Efectivo'),prv=c.all.find(r=>r.l==='Privados de BRK');
  $('kp').innerHTML='<tr><td>Asignación SPY / QQQ / BRK</td><td>'+w.S+'% / '+w.Q+'% / '+w.B+'%</td></tr><tr><td>BRK recibido vía SPY</td><td>'+p1(w.S*D.bs/100)+'</td></tr><tr><td>BRK descompuesto (directo + vía SPY)</td><td>'+p1(c.pb)+'</td></tr>'+
   '<tr><td>Aporte final de SPY / QQQ / BRK</td><td>'+p1(sum('S'))+' / '+p1(sum('Q'))+' / '+p1(sum('B'))+'</td></tr>'+
   '<tr><td>Efectivo / Privados de BRK</td><td>'+p1(eff?eff.T:0)+' / '+p1(prv?prv.T:0)+'</td></tr><tr><td><b>Total</b></td><td><b>'+p1(c.tot)+'</b></td></tr>';
  if($('dt').open)$('tf').innerHTML='<tr><th>N.º</th><th>Símbolo</th><th>Empresa</th><th>SPY</th><th>QQQ</th><th>BRK</th><th>Final</th><th>Fuentes</th></tr>'+
   c.all.map((r,i)=>'<tr><td>'+(i+1)+'</td><td>'+r.t+'</td><td>'+r.n+'</td><td>'+p2(r.S)+'</td><td>'+p2(r.Q)+'</td><td>'+p2(r.B)+'</td><td><b>'+p2(r.T)+'</b></td><td>'+
   [r.S>1e-10?'SPY':'',r.Q>1e-10?'QQQ':'',r.B>1e-10?'BRK':''].filter(Boolean).join(' + ')+'</td></tr>').join('');
  delete cache.CG; if(tab==2&&cmpOK)drawC();
}
let q=0;const go=()=>{cancelAnimationFrame(q);q=requestAnimationFrame(render);};
function sync(){for(const k of ['S','Q','B']){$('r'+k).value=w[k];$('n'+k).value=w[k];}}
function set(k,v){  // enteros que siempre suman 100: SPY reparte entre QQQ y BRK; QQQ solo mueve a BRK; BRK reparte entre SPY y QQQ
  v=Math.max(0,Math.min(100,Math.round(+v||0)));
  if(k==='Q'){v=Math.min(v,100-w.S);w.Q=v;w.B=100-w.S-v;}
  else{const o=k==='S'?['Q','B']:['S','Q'],r=100-v,so=w[o[0]]+w[o[1]],a=so<1?Math.round(r/2):Math.round(r*w[o[0]]/so);w[o[0]]=a;w[o[1]]=r-a;w[k]=v;}
  sync();go();
}
for(const k of ['S','Q','B']){$('r'+k).oninput=e=>set(k,e.target.value);$('n'+k).onchange=e=>set(k,e.target.value);}
const aviso=(b,ok)=>{const t=b.dataset.t||(b.dataset.t=b.textContent);b.textContent=ok?'Guardado ✓':'No se pudo guardar';setTimeout(()=>b.textContent=t,1600);};
$('es').onclick=function(){aviso(this,LS.set('cg_pesos_v1',w));};
$('eq').onclick=()=>{w={S:34,Q:33,B:33};sync();go();};
$('dt').ontoggle=render;

// ---------------- comparativa cuantitativa ----------------
const CP={CG:'#D97757',SPY:'#6FA3DB',QQQ:'#F5973A','BRK-B':'#6CBF6A'},LB={CG:'Cartera global',SPY:'SPY',QQQ:'QQQ','BRK-B':'BRK'},OB=['CG','SPY','QQQ','BRK-B'];
let tab=1,cmpOK=false,C={chk:{CG:1,SPY:1,QQQ:1,'BRK-B':1},x:M.otro||'',dA:'CG',dB:'SPY'},lgx=false,ca=0,cb=0,busy=false,bound=false,N=0,TS=[],MO=[];const cache={};
const colK=k=>CP[k]||'#B79CED',nmK=k=>LB[k]||k;
function fin(o){const dd=new Float64Array(N).fill(NaN);let m=-Infinity;for(let i=o.s;i<N;i++){const v=o.p[i];if(v>m)m=v;dd[i]=(v/m-1)*100;}o.dd=dd;return o;}
function ser(k){
  if(cache[k])return cache[k];const o=PX.a[k];if(!o)return null;
  const p=new Float64Array(N).fill(NaN);for(let i=0;i<o.v.length;i++)p[o.s+i]=o.v[i];
  return cache[k]=fin({s:o.s,p:p});
}
function cart(){  // cartera con rebalanceo trimestral sin fricciones hacia los pesos del selector
  const A=['SPY','QQQ','BRK-B'].map(ser);if(A.some(x=>!x))return null;
  const s=Math.max(...A.map(x=>x.s)),W=[w.S,w.Q,w.B].map(x=>x/100),p=new Float64Array(N).fill(NaN),v=W.slice();p[s]=100;
  for(let i=s+1;i<N;i++){let t=0;for(let k=0;k<3;k++){v[k]*=A[k].p[i]/A[k].p[i-1];t+=v[k];}
    if(MO[i]!==MO[i-1]&&(MO[i]===1||MO[i]===4||MO[i]===7||MO[i]===10))for(let k=0;k<3;k++)v[k]=t*W[k];
    p[i]=100*t;}
  return fin({s:s,p:p});
}
const get=k=>k==='CG'?(cache.CG||(cache.CG=cart())):ser(k);
const mean=x=>x.reduce((s,v)=>s+v,0)/x.length,sd=x=>{const m=mean(x);return Math.sqrt(x.reduce((s,v)=>s+(v-m)*(v-m),0)/(x.length-1));};
const fd=i=>{const z=PX.f[i].split('-');return z[2]+'/'+z[1]+'/'+z[0];};
function fm(v,d,u,sg){if(v===null||v===undefined||!isFinite(v))return 'n/d';let n=Number(v.toFixed(d));if(n===0)n=0;const s=Math.abs(n).toFixed(d);return (n<0?'-':(sg&&n>0?'+':''))+s+(u||'');}
function selK(){
  const s=new Set();OB.forEach(k=>C.chk[k]&&s.add(k));if(C.x)s.add(C.x);s.add(C.dA);s.add(C.dB);
  const o=OB.concat(C.x?[C.x]:[]);
  const a=[...s].filter(k=>get(k)).sort((x,y)=>{const i=o.indexOf(x),j=o.indexOf(y);return (i<0?99:i)-(j<0?99:j);});
  OB.forEach(k=>{if(a.includes(k))C.chk[k]=1;});return a;
}
function stats(keys,a,b,ref){
  const S=keys.map(get),a2=Math.max(a,...S.map(x=>x.s));if(b-a2<5)return null;
  const R=k=>{const p=get(k).p,r=[];for(let i=a2+1;i<=b;i++)r.push(p[i]/p[i-1]-1);return r;};
  const dias=(TS[b]-TS[a2])/864e5,rr=R(ref),mR=mean(rr),res={};let vR=0;rr.forEach(x=>vR+=(x-mR)*(x-mR));
  keys.forEach(k=>{
    const o=get(k),p=o.p,r=R(k),F=r.length/(dias/365.25),tot=p[b]/p[a2]-1,ann=dias>=30?Math.pow(1+tot,365.25/dias)-1:NaN,vol=sd(r)*Math.sqrt(F);
    const dsd=Math.sqrt(r.reduce((s,x)=>s+(x<0?x*x:0),0)/r.length)*Math.sqrt(F);let mdd=0;for(let i=a2;i<=b;i++)if(o.dd[i]<mdd)mdd=o.dd[i];
    const mk=mean(r);let cv=0,vk=0;for(let i=0;i<r.length;i++){cv+=(r[i]-mk)*(rr[i]-mR);vk+=(r[i]-mk)*(r[i]-mk);}
    res[k]={tot:tot*100,ann:ann*100,vol:vol*100,dsd:dsd*100,mdd:mdd,dist:o.dd[b],rr:ann/vol,cor:cv/Math.sqrt(vk*vR),beta:cv/vR,vm:(PX.m[k]||{}).v};
  });
  return {a2:a2,res:res,dias:dias,n:b-a2};
}
function initC(){
  cmpOK=true;
  if(!PX||!PX.f){$('cs').innerHTML='<span class="w">Datos de precios no disponibles'+(PX&&PX.err?': '+PX.err:'')+'.</span>';$('cc').style.display='none';$('cmp').style.display='none';return;}
  N=PX.f.length;TS=PX.f.map(s=>Date.parse(s+'T00:00:00Z'));MO=PX.f.map(s=>+s.slice(5,7));
  const sv=LS.get('cg_comp_v1');if(sv&&sv.chk&&sv.dA&&sv.dB)C=Object.assign(C,sv);
  if(C.x&&!PX.a[C.x])C.x='';
  const ex=Object.keys(PX.a).filter(k=>!OB.includes(k)).sort(),opts=OB.concat(ex).map(k=>'<option value="'+k+'">'+nmK(k)+'</option>').join('');
  $('chips').innerHTML=OB.map(k=>'<label class="chip" style="color:'+colK(k)+'"><input type="checkbox" data-k="'+k+'">'+nmK(k)+'</label>').join('');
  $('cx').innerHTML='<option value="">ninguno</option>'+ex.map(k=>'<option value="'+k+'">'+k+(PX.m[k]?' · '+PX.m[k].n.slice(0,26):'')+'</option>').join('');
  $('da').innerHTML=opts;$('db').innerHTML=opts;
  document.querySelectorAll('#chips input').forEach(e=>e.onchange=()=>{C.chk[e.dataset.k]=e.checked?1:0;drawC();});
  $('cx').onchange=e=>{C.x=e.target.value;drawC();};$('da').onchange=e=>{C.dA=e.target.value;drawC();};$('db').onchange=e=>{C.dB=e.target.value;drawC();};
  $('lg').onchange=e=>{lgx=e.target.checked;drawC();};
  $('ce').onclick=function(){aviso(this,LS.set('cg_comp_v1',C));};
  $('cp').onclick=()=>{C={chk:{CG:1,SPY:1,QQQ:1,'BRK-B':1},x:'',dA:'CG',dB:'SPY'};drawC();};
  $('cv').onclick=()=>{C={chk:{CG:0,SPY:0,QQQ:0,'BRK-B':0},x:'',dA:'CG',dB:'SPY'};drawC();};
  const hc=Math.max(460,Math.min(700,Math.round($('w').clientWidth*.4)));$('cch').style.height=hc+'px';
  const k0=selK();ca=Math.max(0,...k0.map(k=>get(k).s));cb=N-1;
  drawC();
}
function idx(x0,x1){const t0=Date.parse(String(x0).slice(0,19).replace(' ','T')+'Z'),t1=Date.parse(String(x1).slice(0,19).replace(' ','T')+'Z');let a=0,b=N-1;while(a<N-1&&TS[a]<t0)a++;while(b>0&&TS[b]>t1)b--;return [a,b];}
function drawC(){
  if(!cmpOK||!PX||!PX.f)return;
  const keys=selK(),ref=C.dB;
  $('da').value=C.dA;$('db').value=C.dB;$('cx').value=C.x;$('lg').checked=lgx;
  document.querySelectorAll('#chips input').forEach(e=>e.checked=!!C.chk[e.dataset.k]);
  if(keys.length<2||!get(ref)||!get(C.dA)){$('cs').innerHTML='<span class="w">Faltan datos de precios para los activos elegidos.</span>';return;}
  const st=stats(keys,ca,cb,ref);if(!st){$('cs').innerHTML='<span class="w">Rango sin datos comunes suficientes: ampliarlo.</span>';return;}
  const a2=st.a2,res=st.res;
  $('cs').textContent='Rango analizado: '+fd(a2)+' a '+fd(cb)+' · '+(st.dias/365.25).toFixed(1)+' años · '+st.n+' ruedas';
  const R=[['Retorno total (punta a punta)','tot',0,'%',1],['Rendimiento anual','ann',1,'%',1],['Volatilidad anual','vol',1,'%',1],['Volatilidad negativa anual','dsd',1,'%',1],
    ['Máxima caída histórica','mdd',0,'%',1],['Distancia al máximo histórico','dist',1,'%',1],['Rendimiento anual / volatilidad','rr',2,'',1],
    ['Correlación diaria frente a '+nmK(ref),'cor',2,'',0],['Beta frente a '+nmK(ref),'beta',2,'',0],['Volumen diario promedio, 3 meses (millones)','vm',0,'',0]];
  let h='<tr><th></th>'+keys.map(k=>'<th style="color:'+colK(k)+'">'+nmK(k)+'</th>').join('')+'<th>Δ</th></tr>';
  for(const [l,k,d,u,dl] of R){
    h+='<tr><td>'+l+'</td>'+keys.map(x=>{const v=res[x][k];return '<td>'+(k==='vm'&&(v===null||v===undefined)?'—':(k==='vm'?String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g,'\u202f'):fm(v,d,u)))+'</td>';}).join('')+
      '<td><b>'+(dl?fm(res[C.dA][k]-res[C.dB][k],d,u,true):'')+'</b></td></tr>';}
  $('ct').innerHTML=h;$('cd').textContent='Δ = '+nmK(C.dA)+' menos '+nmK(C.dB);
  $('cf').innerHTML='<div>'+keys.map(k=>'<b style="color:'+colK(k)+'">'+nmK(k)+'</b>: '+(k==='CG'?'SPY '+w.S+'% · QQQ '+w.Q+'% · BRK '+w.B+'%, rebalanceo trimestral sin fricciones':((PX.m[k]||{}).n||k)+' · '+((PX.m[k]||{}).c||'s/d'))).join(' &nbsp;|&nbsp; ')+'</div>'+
    '<div>Precios ajustados por dividendos y splits (retorno total). Fuente: Yahoo Finance, actualizada todos los días a las 18:00. Volumen: promedio de las últimas 60 ruedas en moneda de cotización.</div>'+
    keys.filter(k=>(PX.m[k]||{}).w).map(k=>'<div class="w">Aviso: '+nmK(k)+' es un '+PX.m[k].w+'</div>').join('')+
    (new Set(keys.filter(k=>k!=='CG').map(k=>(PX.m[k]||{}).c)).size>1?'<div class="w">Aviso: monedas distintas entre los activos elegidos; la comparación mezcla efecto cambiario.</div>':'');
  const ys=[],ds=[];let lo=Infinity,hi=-Infinity,mn=0;
  keys.forEach(k=>{const o=get(k),y=new Array(N).fill(null),dd=new Array(N).fill(null),b0=o.p[a2];
    for(let i=a2;i<N;i++){const v=lgx?100*o.p[i]/b0:(o.p[i]/b0-1)*100;y[i]=v;if(i>=a2&&i<=cb){if(v<lo)lo=v;if(v>hi)hi=v;if(o.dd[i]<mn)mn=o.dd[i];}}
    for(let i=o.s;i<N;i++)dd[i]=o.dd[i];ys.push(y);ds.push(dd);});
  const pad=(hi-lo)*.06||1,rg=lgx?[Math.log10(lo/1.04),Math.log10(hi*1.04)]:[lo-pad,hi+pad];
  const tr=[];keys.forEach((k,i)=>tr.push({x:PX.f,y:ys[i],name:nmK(k),type:'scatter',mode:'lines',connectgaps:false,xaxis:'x',yaxis:'y',line:{color:colK(k),width:k==='CG'?2.6:1.6},hovertemplate:'%{fullData.name}: %{y:.1f}'+(lgx?'':'%')+'<extra></extra>'}));
  keys.forEach((k,i)=>tr.push({x:PX.f,y:ds[i],name:nmK(k)+' · caída',type:'scatter',mode:'lines',connectgaps:false,xaxis:'x2',yaxis:'y2',line:{color:colK(k),width:1},hovertemplate:'%{fullData.name}: %{y:.1f}%<extra></extra>'}));
  const ax={gridcolor:'#3d3d3a',linecolor:'#3d3d3a',zeroline:false,showspikes:true,spikemode:'across',spikethickness:1,spikecolor:'#9a988f',spikedash:'dot',hoverformat:'%d/%m/%Y',type:'date',minallowed:PX.f[0],maxallowed:PX.f[N-1]};
  const lay=Object.assign({},L0,{dragmode:'pan',margin:{l:60,r:14,t:40,b:8},hovermode:'x unified',
    xaxis:Object.assign({},ax,{domain:[0,1],anchor:'y',matches:'x2',showticklabels:false}),
    xaxis2:Object.assign({},ax,{domain:[0,1],anchor:'y2',range:[PX.f[ca],PX.f[cb]],rangeslider:{visible:true,thickness:.08,bgcolor:'#262624',bordercolor:'#3d3d3a'},
      rangeselector:{x:0,y:1.0,yanchor:'bottom',bgcolor:'#262624',activecolor:'#4a4944',bordercolor:'#3d3d3a',font:{size:11,color:'#c2c0b6'},buttons:[
        {count:1,label:'1 mes',step:'month',stepmode:'backward'},{count:6,label:'6 meses',step:'month',stepmode:'backward'},{count:1,label:'En el año',step:'year',stepmode:'todate'},
        {count:1,label:'1 año',step:'year',stepmode:'backward'},{count:3,label:'3 años',step:'year',stepmode:'backward'},{count:5,label:'5 años',step:'year',stepmode:'backward'},
        {count:10,label:'10 años',step:'year',stepmode:'backward'},{step:'all',label:'Todo'}]}}),
    yaxis:{domain:[.34,1],anchor:'x',type:lgx?'log':'linear',range:rg,ticksuffix:lgx?'':'%',title:{text:lgx?'Valor de 100 invertidos':'Retorno total acumulado (%)',font:{size:11}},gridcolor:'#3d3d3a',zeroline:!lgx,zerolinecolor:'#5a5954',fixedrange:true},
    yaxis2:{domain:[0,.28],anchor:'x2',range:[mn*1.1-.5,.8],ticksuffix:'%',title:{text:'Caída desde el máximo histórico (%)',font:{size:11}},gridcolor:'#3d3d3a',zeroline:false,fixedrange:true}});
  busy=true;Plotly.react('cch',tr,lay,{displayModeBar:false,responsive:true,scrollZoom:true,doubleClick:false}).then(()=>{busy=false;
    if(!bound){bound=true;$('cch').on('plotly_relayout',e=>{
      if(busy)return;let x0,x1,full=false;
      for(const k of ['xaxis2','xaxis']){if(e[k+'.range[0]']!==undefined){x0=e[k+'.range[0]'];x1=e[k+'.range[1]'];break;}if(e[k+'.range']){x0=e[k+'.range'][0];x1=e[k+'.range'][1];break;}if(e[k+'.autorange']){full=true;break;}}
      if(x0===undefined&&!full)return;
      const r=full?[0,N-1]:idx(x0,x1);if(r[1]-r[0]<5)return;ca=r[0];cb=r[1];drawC();});}});
}
function show(n){
  tab=n;$('p1').style.display=n===1?'':'none';$('p2').style.display=n===2?'':'none';$('tb1').className=n===1?'on':'';$('tb2').className=n===2?'on':'';
  if(n===2){if(!cmpOK)initC();else drawC();setTimeout(()=>{try{Plotly.Plots.resize('cch')}catch(e){}},30);}
  else{render();setTimeout(()=>['g1','g2','g3'].forEach(i=>{try{Plotly.Plots.resize(i)}catch(e){}}),30);}
}
$('tb1').onclick=()=>show(1);$('tb2').onclick=()=>show(2);
sync();render();
})();
</script>
'''

async def construir():
    raw = await traer()
    S, Q, B = proc_spy(raw["spy"]), proc_qqq(*raw["qqq"]), proc_brk(*raw["brk"])
    D, subs, gap = armar(S, Q, B, raw["subs"], raw["subs_err"])
    w0 = np.array([Peso_SPY, Peso_QQQ, Peso_BRK], float)
    if w0.sum() <= 0: raise ValueError("La asignación original suma 0%.")
    w = enteros(w0); aviso = "" if abs(w0.sum() - 100) < 1e-9 else f"La asignación ingresada sumaba {w0.sum():.0f}% y se reescaló a 100%. "
    pb = w[2] + w[0] * D["bs"] / 100                                    # control de cierre con la asignación inicial
    tot = w[0] * (sum(D["s"]) + D["cs"]) / 100 + w[1] * (sum(D["q"]) + D["cq"]) / 100 + pb * (sum(D["b"]) + D["cb"] + D["bp"]) / 100
    assert abs(tot - 100) < 1e-4, f"la cartera no cierra en 100% ({tot:.6f}%)"
    # --- precios para la comparativa (si fallan, la cartera igual se publica y la pestaña lo informa) ---
    contrib = np.array(D["s"]) * w[0] / 100 + np.array(D["q"]) * w[1] / 100 + pb * np.array(D["b"]) / 100
    top = [D["t"][i] for i in np.argsort(-contrib) if ":" not in D["t"][i]][:20]
    nombres = dict(zip(D["t"], D["n"])); nombres.update(NOMBRES_ETF); extras = leer_extras()
    tks = list(dict.fromkeys(BASE + top + ETFS_EXTRA + extras))
    try: PX = await asyncio.get_running_loop().run_in_executor(None, bajar_precios, tks, nombres, extras)
    except Exception as e: PX = {"err": str(e)[:160]}
    cierre = ult_cierre(); fila = lambda a, b, c: f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>"
    exc = ", ".join(f"{n} {dmy(d)}" for n, d in B["exc"])
    fechas = (fila("SPY · State Street", dmy(S["fecha"]) + ant(S["fecha"], 4), "Posiciones diarias oficiales") +
              fila("QQQ · Invesco", dmy(Q["fecha"]) + ant(Q["fecha"], 4), "Fecha efectiva informada por la fuente") +
              fila("BRK · acciones", f'cantidades al {dmy(B["f13"])} (13F presentado el {dmy(B["f13p"])}), valuadas al cierre del {dmy(cierre)}', ("Excepciones de fecha: " + exc) if exc else "Valor de mercado vigente según CNBC") +
              fila("BRK · efectivo", dmy(B["fecha_efectivo"]) + ant(B["fecha_efectivo"]), "Efectivo y letras del Tesoro del último balance trimestral") +
              fila("BRK · capitalización", f'{dmy(cierre)} (último cierre hábil)', f'US$ {B["cap"]/1e9:.0f} mil millones') +
              fila("Precios de la comparativa", "Yahoo Finance · ajustados", "Descarga diaria completa; la fecha de consulta figura arriba"))
    subs_h = "".join(f'<div>{i+1}. <a href="{u}" target="_blank">{n}</a></div>' for i, (n, u) in enumerate(subs)) or f'<div class="w">No se pudo leer el listado ({raw["subs_err"] or "vacío"}).</div>'
    dif = abs(B["pub"] / B["total_cnbc"] - 1) * 100 if B["total_cnbc"] else None
    ctrl = "" if dif is None else (f"<li><b>Control contra CNBC:</b> las posiciones suman US$ {B['pub']/1e9:.1f} mil millones, igual al TOTAL informado por CNBC.</li>" if dif < 1 else f'<li class="w"><b>Control contra CNBC:</b> las posiciones suman US$ {B["pub"]/1e9:.1f} mil millones y el TOTAL de CNBC es US$ {B["total_cnbc"]/1e9:.1f} mil millones: revisar.</li>')
    neto = f" El neto (sin el efectivo de BNSF y descontando letras del Tesoro a pagar) es US$ {B['cash_neto']/1e9:.1f} mil millones." if B["cash_neto"] else ""
    criterios = ("<ol><li><b>Fuentes.</b> Tres consultas independientes: SPY (archivo diario de State Street), QQQ (posiciones de Invesco) y BRK (CNBC).</li>"
        "<li><b>Aporte.</b> Ponderación del activo dentro de su fuente × asignación de esa fuente.</li>"
        "<li><b>BRK dentro de SPY.</b> Esa posición se reemplaza por la composición de BRK y se suma a la asignación directa de BRK, sin doble conteo.</li>"
        "<li><b>Doble clase.</b> Las acciones con más de una clase (Alphabet, Lennar, Fox, News Corp) se consolidan por símbolo.</li>"
        f"<li><b>Reescalado.</b> Cada fuente se reescala a 100% (brecha de origen menor a {max(abs(gap['S']), abs(gap['Q']), 0.01):.2f}%).</li>"
        "<li><b>Efectivo.</b> El de SPY, QQQ y BRK se agrupa. En QQQ incluye futuros y colaterales de divisa del fondo.</li>"
        "<li><b>Privados de BRK.</b> Capitalización − acciones − efectivo: un residual de valor de mercado, no una valuación contable.</li>"
        "<li><b>Gráficos.</b> Los 10 primeros incluyen siempre Efectivo y Privados de BRK; el resto se agrupa.</li>"
        "<li><b>Selector.</b> Enteros que suman 100: SPY reparte entre QQQ y BRK; QQQ solo mueve a BRK; BRK reparte entre SPY y QQQ.</li></ol>")
    salvedades = (f"<ul><li><b>Efectivo de BRK:</b> US$ {B['cash']/1e9:.1f} mil millones según CNBC (bruto, incluye el efectivo de BNSF).{neto}</li>"
        "<li><b>Desfasaje temporal:</b> el efectivo corresponde al último balance trimestral y las acciones se valúan a precio de mercado del último cierre hábil, por lo que Privados de BRK absorbe esa diferencia.</li>"
        "<li><b>Cierre hábil:</b> si se consulta en fin de semana se toma el viernes; no se consideran feriados de EE.UU.</li>"
        "<li><b>Posiciones aproximadas:</b> Bending Spoons es una aproximación según CNBC y las acciones japonesas figuran con su propia fecha.</li>"
        f"{ctrl}<li><b>Sin respaldo estático:</b> si una fuente falla, el programa informa cuál; nunca completa con datos inventados.</li></ul>{aviso}")
    comparativa = ("<ul><li><b>Precios:</b> siempre ajustados por dividendos y splits, de modo que el rendimiento es retorno total.</li>"
        "<li><b>Cartera global:</b> SPY, QQQ y BRK con los pesos del selector, rebalanceados el primer día hábil de enero, abril, julio y octubre, sin costos ni impuestos.</li>"
        "<li><b>Retorno total:</b> variación punta a punta del rango. <b>Rendimiento anual:</b> compuesto, con días corridos / 365.25.</li>"
        "<li><b>Volatilidad:</b> desvío de los retornos diarios × raíz de las ruedas por año del rango. <b>Negativa:</b> solo retornos bajo cero.</li>"
        "<li><b>Máxima caída y distancia:</b> contra el máximo histórico de cada serie. <b>Rendimiento / volatilidad:</b> sin tasa libre de riesgo.</li>"
        "<li><b>Correlación y beta:</b> frente al segundo activo del Δ. <b>Volumen:</b> promedio de 60 ruedas en moneda de cotización.</li>"
        "<li><b>Δ:</b> primer activo menos segundo, con el mismo formato de cada fila.</li>"
        "<li><b>Otros símbolos:</b> la página es estática y no consulta Yahoo; se agregan en el archivo activos.txt del repositorio o en el parámetro Otro_activo de Colab.</li></ul>")
    meta = dict(w=w, consulta=AHORA.strftime("%d/%m/%Y %H:%M") + " (hora de Buenos Aires)", otro=(Otro_activo or "").strip().upper())
    j = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return (HTML_T.replace("__DATA__", j(D)).replace("__META__", j(meta)).replace("__PX__", j(PX)).replace("__FECHAS__", fechas).replace("__CRITERIOS__", criterios)
            .replace("__SALVEDADES__", salvedades).replace("__COMPARATIVA__", comparativa).replace("__SUBS__", subs_h).replace("__NSUBS__", str(len(subs))))

# ---------- EJECUCIÓN AUTOMÁTICA (GitHub Actions) ----------
async def captura():  # imagen de vista previa para el README (no es crítica: si falla, se sigue)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            nav = await p.chromium.launch(args=["--no-sandbox"]); pg = await nav.new_page(viewport={"width": 1500, "height": 980})
            await pg.goto("file://" + os.path.abspath("docs/index.html")); await pg.wait_for_selector("#g1 .main-svg", timeout=30000); await pg.wait_for_timeout(1500)
            await pg.screenshot(path="docs/vista.png", clip={"x": 0, "y": 0, "width": 1500, "height": 780}); await nav.close()
    except Exception as e: print("sin captura de vista previa:", e)

async def principal():
    frag = await construir()
    os.makedirs("docs", exist_ok=True)
    open("docs/index.html", "w", encoding="utf-8").write(pagina(frag))
    print("docs/index.html actualizado", AHORA.strftime("%d/%m/%Y %H:%M"))
    await captura()

asyncio.run(principal())
