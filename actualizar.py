# actualizar.py — genera docs/index.html (y docs/vista.png) con la cartera global del día. Lo ejecuta GitHub Actions todos los días a las 18:00 (Buenos Aires).
# Es el mismo programa del cuaderno de Colab, sin la parte interactiva de Colab. Los pesos iniciales se editan abajo.
Peso_SPY = 60
Peso_QQQ = 25
Peso_BRK = 15

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
</style>
<div id="w">
<h1 id="tt"></h1><div class="sub" id="st"></div>
<div class="ctl">
 <div class="it S">SPY <input id="rS" type="range" min="0" max="100" step="1"><input id="nS" type="number" min="0" max="100" step="1">%</div>
 <div class="it Q">QQQ <input id="rQ" type="range" min="0" max="100" step="1"><input id="nQ" type="number" min="0" max="100" step="1">%</div>
 <div class="it B">BRK <input id="rB" type="range" min="0" max="100" step="1"><input id="nB" type="number" min="0" max="100" step="1">%</div>
 <button id="rs">Restablecer</button>
</div>
<div class="gr">
 <div><h3>Cartera global</h3><p id="s1"></p><div id="g1"></div></div>
 <div><h3>Ponderación en la cartera</h3><p id="s2"></p><div id="g2"></div></div>
 <div><h3>Composición final consolidada</h3><p id="s3"></p><div id="g3"></div></div>
</div>
<div class="g2">
 <div><h2>Reconciliación</h2><table class="kp" id="kp"></table><h2>Activos según cantidad de fuentes</h2><table class="kp n" id="ns" style="max-width:320px"></table></div>
 <div><h2>Fuentes y fechas de los datos</h2><table class="kp">__FECHAS__</table></div>
</div>
<details id="dt"><summary>Tabla completa de la cartera global</summary><div class="sc"><table class="tf" id="tf"></table></div></details>
<h2>Negocios operativos de Berkshire Hathaway (__NSUBS__)</h2><div class="sb">__SUBS__</div>
<div class="nt">__NOTAS__</div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
(function(){
const D=__DATA__,M=__META__,$=id=>document.getElementById(id);
if(typeof Plotly==='undefined'){$('g2').innerHTML='<p class="w">No se pudo cargar Plotly (requiere acceso a cdn.plot.ly).</p>';return;}
const CS={S:'#6FA3DB',Q:'#F5973A',B:'#6CBF6A'},BG='#30302e',PAL=['#6FA3DB','#F5973A','#6CBF6A','#E8706A','#6CC4BE','#C08BC4','#F2A7B8','#B08968','#E6C84F','#9C86D0','#8FD18F','#5CCBD8'],COL={'Efectivo':'#3FA372','Privados de BRK':'#8b8a85','Resto':'#4f4e49'};
let w={S:M.w[0],Q:M.w[1],B:M.w[2]},cn=0;
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
const cfg={displayModeBar:false,responsive:true},L0={margin:{l:8,r:8,t:8,b:8},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',showlegend:false,font:{size:12,color:'#c2c0b6'},hoverlabel:{bgcolor:'#1f1e1d',bordercolor:'#4a4944',font:{color:'#faf9f5',size:12}}};
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
  Plotly.react('g2',tr,Object.assign({},L0,{barmode:'stack',margin:{l:8,r:36,t:8,b:28},xaxis:{ticksuffix:'%',gridcolor:'#3d3d3a',linecolor:'#3d3d3a',zeroline:false,range:[0,mx*1.16]},
    yaxis:{autorange:'reversed',automargin:true,type:'category',ticks:'outside',ticklen:8,tickcolor:'rgba(0,0,0,0)'}}),cfg);
  const lb=c.sel.map(r=>r.l).concat(c.rest>1e-9?['Resto']:[]),vl=c.sel.map(r=>r.T).concat(c.rest>1e-9?[c.rest]:[]);
  Plotly.react('g3',[pie(lb,vl,lb.map(col),1,75,{x:[.16,.84],y:[.1,.9]})],L0,cfg);
  const sum=k=>c.all.reduce((s,r)=>s+r[k],0),eff=c.all.find(r=>r.l==='Efectivo'),prv=c.all.find(r=>r.l==='Privados de BRK');
  $('kp').innerHTML='<tr><td>BRK recibido vía SPY</td><td>'+p1(w.S*D.bs/100)+'</td></tr><tr><td>BRK descompuesto (directo + vía SPY)</td><td>'+p1(c.pb)+'</td></tr>'+
   '<tr><td>Aporte final de SPY / QQQ / BRK</td><td>'+p1(sum('S'))+' / '+p1(sum('Q'))+' / '+p1(sum('B'))+'</td></tr>'+
   '<tr><td>Efectivo / Privados de BRK</td><td>'+p1(eff?eff.T:0)+' / '+p1(prv?prv.T:0)+'</td></tr><tr><td><b>Total</b></td><td><b>'+p1(c.tot)+'</b></td></tr>';
  const cnt={};c.all.forEach(r=>cnt[r.k]=(cnt[r.k]||0)+1);
  $('ns').innerHTML='<tr><th>Cantidad de fuentes</th><th>Cantidad de activos</th></tr>'+Object.keys(cnt).sort().map(k=>'<tr><td>'+k+'</td><td>'+cnt[k]+'</td></tr>').join('');
  if($('dt').open)$('tf').innerHTML='<tr><th>N.º</th><th>Símbolo</th><th>Empresa</th><th>SPY</th><th>QQQ</th><th>BRK</th><th>Final</th><th>Fuentes</th></tr>'+
   c.all.map((r,i)=>'<tr><td>'+(i+1)+'</td><td>'+r.t+'</td><td>'+r.n+'</td><td>'+p2(r.S)+'</td><td>'+p2(r.Q)+'</td><td>'+p2(r.B)+'</td><td><b>'+p2(r.T)+'</b></td><td>'+
   [r.S>1e-10?'SPY':'',r.Q>1e-10?'QQQ':'',r.B>1e-10?'BRK':''].filter(Boolean).join(' + ')+'</td></tr>').join('');
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
$('rs').onclick=()=>{w={S:M.w[0],Q:M.w[1],B:M.w[2]};sync();go();};
$('dt').ontoggle=render;sync();render();
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
    cierre = ult_cierre(); fila = lambda a, b, c: f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>"
    exc = ", ".join(f"{n} {dmy(d)}" for n, d in B["exc"])
    fechas = (fila("SPY · State Street", dmy(S["fecha"]) + ant(S["fecha"], 4), "Posiciones diarias oficiales") +
              fila("QQQ · Invesco", dmy(Q["fecha"]) + ant(Q["fecha"], 4), "Fecha efectiva informada por la fuente") +
              fila("BRK · acciones", f'cantidades al {dmy(B["f13"])} (13F presentado el {dmy(B["f13p"])})<br>valuadas al cierre del {dmy(cierre)}', ("Excepciones de fecha: " + exc) if exc else "Valor de mercado vigente según CNBC") +
              fila("BRK · efectivo", dmy(B["fecha_efectivo"]) + ant(B["fecha_efectivo"]), "Efectivo y letras del Tesoro del último balance trimestral") +
              fila("BRK · capitalización", f'{dmy(cierre)} (último cierre hábil)', f'US$ {B["cap"]/1e9:.0f} mil millones'))
    subs_h = "".join(f'<div>{i+1}. <a href="{u}" target="_blank">{n}</a></div>' for i, (n, u) in enumerate(subs)) or f'<div class="w">No se pudo leer el listado ({raw["subs_err"] or "vacío"}).</div>'
    dif = abs(B["pub"] / B["total_cnbc"] - 1) * 100 if B["total_cnbc"] else None
    ctrl = "" if dif is None else (f" Control: las posiciones suman US$ {B['pub']/1e9:.1f} mil millones, igual al TOTAL de CNBC." if dif < 1 else f' <span class="w">Control: las posiciones suman US$ {B["pub"]/1e9:.1f} mil millones y el TOTAL de CNBC es US$ {B["total_cnbc"]/1e9:.1f} mil millones: revisar.</span>')
    neto = f"; neto sin BNSF y descontando letras a pagar: US$ {B['cash_neto']/1e9:.1f} mil millones" if B["cash_neto"] else ""
    notas = (aviso + "Metodología: aporte = ponderación dentro de la fuente × asignación de esa fuente. La posición de BRK dentro de SPY se reemplaza por la composición de BRK y se suma a la asignación directa (sin doble conteo); "
             f"las acciones de doble clase se consolidan por símbolo y cada fuente se reescala a 100% (brecha de origen menor a {max(abs(gap['S']), abs(gap['Q']), 0.01):.2f}%). «Privados de BRK» es un residual de valor de mercado "
             f"(capitalización − acciones − efectivo): absorbe el desfasaje entre el efectivo del último balance y la capitalización vigente, y no es una valuación contable. Efectivo según CNBC: US$ {B['cash']/1e9:.1f} mil millones{neto}. "
             "El efectivo de QQQ incluye futuros y colaterales de divisa del fondo." + ctrl)
    meta = dict(w=w, consulta=AHORA.strftime("%d/%m/%Y %H:%M") + " (hora de Buenos Aires)")
    j = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return HTML_T.replace("__DATA__", j(D)).replace("__META__", j(meta)).replace("__FECHAS__", fechas).replace("__SUBS__", subs_h).replace("__NSUBS__", f"N = {len(subs)}").replace("__NOTAS__", notas)

# ---------- EJECUCIÓN AUTOMÁTICA (GitHub Actions) ----------
async def captura():  # imagen de vista previa para el README (no es crítica: si falla, se sigue)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            nav = await p.chromium.launch(args=["--no-sandbox"]); pg = await nav.new_page(viewport={"width": 1500, "height": 980})
            await pg.goto("file://" + os.path.abspath("docs/index.html")); await pg.wait_for_selector("#g1 .main-svg", timeout=30000); await pg.wait_for_timeout(1500)
            await pg.screenshot(path="docs/vista.png", clip={"x": 0, "y": 0, "width": 1500, "height": 760}); await nav.close()
    except Exception as e: print("sin captura de vista previa:", e)

async def principal():
    frag = await construir()
    os.makedirs("docs", exist_ok=True)
    open("docs/index.html", "w", encoding="utf-8").write(pagina(frag))
    print("docs/index.html actualizado", AHORA.strftime("%d/%m/%Y %H:%M"))
    await captura()

asyncio.run(principal())
