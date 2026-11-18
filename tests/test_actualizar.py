import json
import asyncio
import shutil
import subprocess
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import actualizar as app


class PreciosTests(unittest.TestCase):
    def test_volumen_brk_suma_el_valor_negociado_de_las_clases_a_y_b(self):
        fechas = pd.date_range("2026-01-01", periods=60)
        activos = {
            "SPY": (500, 1_000_000),
            "QQQ": (500, 1_000_000),
            "BRK-A": (750_000, 10),
            "BRK-B": (500, 15_000),
        }
        df = pd.concat(
            {
                ticker: pd.DataFrame(
                    {
                        "Adj Close": np.full(60, precio),
                        "Close": np.full(60, precio),
                        "Volume": np.full(60, volumen),
                    },
                    index=fechas,
                )
                for ticker, (precio, volumen) in activos.items()
            },
            axis=1,
        )

        class FakeYFinance:
            def download(self, *args, **kwargs):
                return df

        with patch.object(app, "_yf", return_value=FakeYFinance()):
            precios = app.bajar_precios(app.BASE, app.NOMBRES_ETF, [])

        self.assertEqual(precios["m"]["BRK-A"]["v"], 15)
        self.assertNotEqual(precios["m"]["BRK-A"]["v"], 10 + 15_000)
        self.assertNotIn("BRK-B", precios["a"])


class ProcesamientoSpyTests(unittest.TestCase):
    def workbook(self, rows):
        return pd.DataFrame(
            [
                ["As of 18-Nov-2026", "", ""],
                ["Ticker", "Name", "Weight"],
                *rows,
            ]
        )

    def parse(self, rows):
        with patch.object(app.pd, "read_excel", return_value=self.workbook(rows)):
            return app.proc_spy(b"fixture")

    def test_conserva_posiciones_especiales_y_efectivo(self):
        out = self.parse(
            [
                ["AAPL", "Apple Inc.", 98.8],
                ["12345", "Acquisition right", 0.2],
                ["", "Unidentified instrument", 0.3],
                ["USD", "US Dollar", 0.7],
            ]
        )

        self.assertAlmostEqual(out["w"]["AAPL"], 98.8)
        self.assertAlmostEqual(out["ef"], 0.7)
        self.assertAlmostEqual(out["raro"], 0.5)
        self.assertAlmostEqual(sum(out["w"]) + out["ef"], 100)
        self.assertEqual(len([k for k in out["w"].index if k.startswith("__SPY_ESPECIAL_")]), 2)

    def test_conserva_contra_posicion_con_ticker_alfanumerico_como_especial(self):
        out = self.parse(
            [
                ["AAPL", "Apple Inc.", 99.999997],
                ["2602335D", "CONTRA HOLOGIC INCORPO", 0.000003],
            ]
        )

        self.assertAlmostEqual(out["raro"], 0.000003)
        self.assertTrue(any("2602335D" in k for k in out["w"].index if k.startswith("__SPY_ESPECIAL_")))

    def test_rechaza_fuente_incompleta_y_pesos_negativos(self):
        with self.assertRaisesRegex(RuntimeError, "fecha"):
            raw = self.workbook([["AAPL", "Apple Inc.", 100]])
            raw.iloc[0, 0] = ""
            with patch.object(app.pd, "read_excel", return_value=raw):
                app.proc_spy(b"fixture")

        with self.assertRaisesRegex(RuntimeError, "negativos"):
            self.parse([["AAPL", "Apple Inc.", 101], ["MSFT", "Microsoft", -1]])

    def test_corta_pies_de_pagina_tras_fila_vacia_pero_no_omite_posiciones_sin_peso(self):
        out = self.parse(
            [
                ["AAPL", "Apple Inc.", 100],
                ["", "", ""],
                ["", "State Street legal disclaimer", ""],
            ]
        )
        self.assertEqual(out["lineas"], 1)

        with self.assertRaisesRegex(RuntimeError, "no están identificadas"):
            self.parse([["AAPL", "Apple Inc.", 99], ["", "Unknown instrument", None]])

    def test_rechaza_duplicado_crudo_y_especial_material(self):
        with self.assertRaisesRegex(RuntimeError, "repetidos"):
            self.parse([["AAPL", "Apple Inc.", 50], ["AAPL", "Apple Inc.", 50]])
        with self.assertRaisesRegex(RuntimeError, "especiales"):
            self.parse([["AAPL", "Apple Inc.", 98], ["12345", "Acquisition right", 2]])

    def test_consolida_clases_conocidas_sin_perder_tickers_extranjeros(self):
        out = self.parse(
            [
                ["GOOG", "Alphabet Class C", 30],
                ["GOOGL", "Alphabet Class A", 30],
                ["BABA.SW", "Alibaba", 20],
                ["7203.T", "Toyota", 20],
            ]
        )
        self.assertEqual(out["w"]["GOOG"], 60)
        self.assertIn("BABA.SW", out["w"].index)
        self.assertIn("7203.T", out["w"].index)

    def test_deriva_y_separa_dividendos_pendientes_sin_porcentaje(self):
        raw = pd.DataFrame(
            [
                ["As of 18-Nov-2026", "", "", ""],
                ["Ticker", "Name", "Weight", "Market Value"],
                ["AAPL", "Apple Inc.", 100, 100],
                ["", "USD Pending Dividends", None, 1],
            ]
        )
        with patch.object(app.pd, "read_excel", return_value=raw):
            out = app.proc_spy(b"fixture")

        self.assertAlmostEqual(out["w"]["AAPL"], 100 / 101 * 100)
        self.assertAlmostEqual(out["w"]["__SPY_DIVIDENDOS_PENDIENTES"], 1 / 101 * 100)
        self.assertEqual(out["ef"], 0)
        self.assertAlmostEqual(out["bruto"], 100)
        self.assertAlmostEqual(out["peso_sin_tna_derivado"], 1 / 101 * 100)


class ProcesamientoQqqTests(unittest.TestCase):
    FECHA = "2026-11-18"

    def procesar(self, rows):
        return app.proc_qqq(
            pd.DataFrame(rows, columns=["Ticker", "Empresa", "Tipo", "Weight"]),
            self.FECHA,
        )

    def test_separa_efectivo_de_futuros_garantias_colaterales_y_sin_ticker(self):
        out = self.procesar(
            [
                ["AAPL", "Apple Inc.", "Equity", 92.5],
                ["", "Index future", "Index Future", 1],
                ["", "Guarantee", "Guarantee", 1],
                ["", "Currency collateral", "Currency Collateral", 1],
                ["", "Synthetic cash", "Synthetic Cash", 1],
                ["", "Foreign currency", "Currency", 1],
                ["USD", "CASH &amp; EQUIVALENTS", "Currency", 1],
                ["USDPDV", "USD Pending Dividends", "Currency", 0.5],
                ["JPY", "Dollar future", "Currency", 0.5],
                ["", "Unidentified", "Other", 0.5],
            ]
        )

        self.assertEqual(out["ef"], 1)
        self.assertEqual(out["w"]["__QQQ_FUTUROS"], 1)
        self.assertEqual(out["w"]["__QQQ_GARANTIAS"], 1)
        self.assertEqual(out["w"]["__QQQ_COLATERALES"], 1)
        self.assertEqual(out["w"]["__QQQ_EFECTIVO_SINTETICO"], 1)
        self.assertEqual(out["w"]["__QQQ_DIVISA"], 1.5)
        self.assertEqual(out["w"]["__QQQ_DIVIDENDOS_PENDIENTES"], 0.5)
        sin_clasificar = [k for k in out["w"].index if k.startswith("__QQQ_SIN_CLASIFICAR_")]
        self.assertEqual(sum(out["w"][k] for k in sin_clasificar), 0.5)
        self.assertAlmostEqual(out["bruto"], 100)

    def test_rechaza_fecha_faltante_pesos_negativos_duplicados_y_suma_discrepante(self):
        good = pd.DataFrame(
            [[f"T{i:02}", f"Company {i}", "Equity", 2] for i in range(50)],
            columns=["Ticker", "Empresa", "Tipo", "Weight"],
        )
        with self.assertRaisesRegex(RuntimeError, "fecha"):
            app.proc_qqq(good, None)
        with self.assertRaisesRegex(RuntimeError, "negativos"):
            self.procesar([["AAPL", "Apple", "Equity", -1]])
        with self.assertRaisesRegex(RuntimeError, "repetidos"):
            self.procesar([["AAPL", "Apple", "Equity", 50], ["AAPL", "Apple", "Equity", 50]])
        with self.assertRaisesRegex(RuntimeError, "tolerancia"):
            app._validar_tabla_qqq(good.assign(Weight=1.5), "fixture")
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app._validar_tabla_qqq(good.iloc[:49], "fixture")
        with self.assertRaisesRegex(RuntimeError, "sin clasificar"):
            self.procesar([["", "Unknown instrument", "Other", 2], ["AAPL", "Apple", "Equity", 98]])
        with self.assertRaisesRegex(RuntimeError, "sin clasificar"):
            self.procesar([["UNKN", "Unverified instrument", "", 2], ["AAPL", "Apple", "Equity", 98]])

    def test_derivados_solo_netea_contra_futuro_oficial_del_mismo_vencimiento(self):
        filas = [
            ["AAPL", "Apple Inc.", "Common Stock", 99.6],
            ["NQZ6", "CME E-Mini NASDAQ 100 Index Future", "Index Future", 0.2],
            ["", "CONTRA FUTURE FUTURE DEC 18 26", "Synthetic Cash", -0.2],
            ["USD", "CASH &amp; EQUIVALENTS", "Currency", 0.4],
        ]
        df = pd.DataFrame(filas, columns=["Ticker", "Empresa", "Tipo", "Weight"])
        df["Vencimiento"] = [None, "2026-12-18", "2026-12-18", None]
        out = app.proc_qqq(df, self.FECHA)

        self.assertAlmostEqual(out["w"]["__QQQ_FUTUROS"], 0)
        self.assertAlmostEqual(out["ef"], 0.4)
        self.assertAlmostEqual(out["bruto"], 100)

        df.loc[2, "Weight"] = -0.1
        with self.assertRaisesRegex(RuntimeError, "no coincide"):
            app.proc_qqq(df, self.FECHA)

    def test_json_selecciona_tabla_completa_por_suma_no_por_longitud(self):
        correcta = [{"ticker": f"T{i:02}", "name": f"Company {i}", "weight": 100 / 50} for i in range(50)]
        distractora = [{"ticker": f"D{i:02}", "name": f"Decoy {i}", "weight": 1} for i in range(70)]
        encontrada = app.buscar({"long": distractora, "holdings": correcta})

        self.assertEqual(encontrada, correcta)
        self.assertIsNone(app.buscar({"holdings": correcta[:49]}))

    def test_api_oficial_reconcilia_recuento_y_dividendos_sin_peso(self):
        holdings = [
            {
                "ticker": f"T{i:02}",
                "issuerName": f"Company {i}",
                "percentageOfTotalNetAssets": 1.992,
                "securityTypeName": "American Depository Receipt - NY" if i == 0 else "Common Stock",
                "marketValueBase": 1.992,
                "contractExpiryDate": None,
            }
            for i in range(50)
        ]
        holdings.extend(
            [
                {
                    "ticker": "NQZ6",
                    "issuerName": "CME E-Mini NASDAQ 100 Index Future",
                    "percentageOfTotalNetAssets": 0.2,
                    "securityTypeName": "Index Future",
                    "marketValueBase": 0.2,
                    "contractExpiryDate": "2026-12-18",
                },
                {
                    "ticker": None,
                    "issuerName": "CONTRA FUTURE FUTURE DEC 18 26",
                    "percentageOfTotalNetAssets": -0.2,
                    "securityTypeName": "Synthetic Cash",
                    "marketValueBase": -0.2,
                    "contractExpiryDate": "2026-12-18",
                },
                {
                    "ticker": "USD",
                    "issuerName": "CASH &amp; EQUIVALENTS",
                    "percentageOfTotalNetAssets": 0.2,
                    "securityTypeName": "Currency",
                    "marketValueBase": 0.2,
                    "contractExpiryDate": None,
                },
                {
                    "ticker": None,
                    "issuerName": "CASH COLLATERAL",
                    "percentageOfTotalNetAssets": 0.1,
                    "securityTypeName": "Currency Collateral",
                    "marketValueBase": 0.1,
                    "contractExpiryDate": None,
                },
                {
                    "ticker": None,
                    "issuerName": "Guarantee",
                    "percentageOfTotalNetAssets": 0.1,
                    "securityTypeName": "Guarantee",
                    "marketValueBase": 0.1,
                    "contractExpiryDate": None,
                },
            ]
        )
        holdings.append(
            {
                "ticker": "USDPDV",
                "issuerName": "USD Pending Dividends",
                "percentageOfTotalNetAssets": None,
                "securityTypeName": "Currency",
                "marketValueBase": 2,
                "contractExpiryDate": None,
            }
        )
        data = {
            "effectiveDate": self.FECHA,
            "totalNumberOfHoldings": len(holdings),
            "holdings": holdings,
        }
        tabla, fecha = app._tabla_qqq_oficial(data)
        procesado = app.proc_qqq(tabla, fecha)

        self.assertEqual(fecha, self.FECHA)
        self.assertEqual(len(tabla), 56)
        self.assertAlmostEqual(tabla["Weight"].sum(), 100)
        self.assertAlmostEqual(tabla.attrs["peso_sin_tna_derivado"], 2 / 102 * 100)
        self.assertAlmostEqual(procesado["w"]["__QQQ_DIVIDENDOS_PENDIENTES"], 2 / 102 * 100)
        self.assertAlmostEqual(procesado["ef"], 0.2 * 100 / 102)
        self.assertAlmostEqual(procesado["w"]["__QQQ_FUTUROS"], 0)
        self.assertAlmostEqual(procesado["w"]["__QQQ_COLATERALES"], 0.1 * 100 / 102)
        self.assertAlmostEqual(procesado["w"]["__QQQ_GARANTIAS"], 0.1 * 100 / 102)
        self.assertEqual(procesado["desconocido"], 0)
        self.assertAlmostEqual(procesado["bruto"], 100)

        data["totalNumberOfHoldings"] += 1
        with self.assertRaisesRegex(RuntimeError, "recuento incompleto"):
            app._tabla_qqq_oficial(data)

    def test_api_usa_el_endpoint_oficial_de_holdings_y_no_otra_tabla(self):
        url = (
            "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/"
            "46090E103/holdings/fund?idType=cusip&productType=ETF"
        )
        self.assertTrue(app._es_api_qqq(url))
        self.assertFalse(app._es_api_qqq(url.replace("holdings/fund", "weightedHoldings/fund")))
        self.assertFalse(app._es_api_qqq(url.replace("46090E103", "QQQ")))

    def test_api_descarga_la_tabla_completa_sin_parametro_de_paginacion(self):
        holdings = [
            {
                "ticker": f"T{i:02}",
                "issuerName": f"Company {i}",
                "percentageOfTotalNetAssets": 2,
                "securityTypeName": "Common Stock",
            }
            for i in range(50)
        ]
        data = {
            "effectiveDate": self.FECHA,
            "totalNumberOfHoldings": len(holdings),
            "holdings": holdings,
        }
        url = (
            "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/"
            "46090E103/holdings/fund?idType=cusip&productType=ETF"
        )
        response = type(
            "Response",
            (),
            {"status_code": 200, "url": url, "json": lambda self: data},
        )()
        with patch.object(app.requests, "get", return_value=response) as get:
            tabla, fecha = app.qqq_api()

        self.assertEqual(len(tabla), 50)
        self.assertEqual(fecha, self.FECHA)
        self.assertNotIn("loadType", get.call_args.args[0])
        with self.assertRaisesRegex(RuntimeError, "recuento incompleto"):
            app._tabla_qqq_oficial(
                {"effectiveDate": self.FECHA, "totalNumberOfHoldings": 106, "holdings": holdings[:10]}
            )

    def test_api_oficial_no_acepta_posicion_sin_tipo_o_ticker_como_efectivo(self):
        holdings = [
            {
                "ticker": f"T{i:02}",
                "issuerName": f"Company {i}",
                "percentageOfTotalNetAssets": 2,
                "securityTypeName": "Common Stock",
                "marketValueBase": 2,
            }
            for i in range(50)
        ]
        holdings.append(
            {
                "ticker": "",
                "issuerName": "Unidentified instrument",
                "percentageOfTotalNetAssets": None,
                "securityTypeName": "Other",
                "marketValueBase": 1,
            }
        )
        with self.assertRaisesRegex(RuntimeError, "no están identificadas"):
            app._tabla_qqq_oficial(
                {"effectiveDate": self.FECHA, "totalNumberOfHoldings": 51, "holdings": holdings}
            )

    def test_descarga_usa_el_csv_oficial_y_exige_tabla_completa(self):
        csv = "Holding Ticker,Name,Security Type,Weight,Date\n" + "".join(
            f"T{i:02},Company {i},Equity,2,2026-11-18\n" for i in range(50)
        )
        response = type(
            "Response",
            (),
            {
                "status_code": 200,
                "content": csv.encode().ljust(2100),
                "text": csv,
                "url": "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0",
            },
        )()
        with patch.object(app.requests, "get", return_value=response) as get, patch.object(app.time, "sleep"):
            tabla, fecha = app.qqq_csv()

        self.assertEqual(len(tabla), 50)
        self.assertEqual(fecha, self.FECHA)
        self.assertIn("www.invesco.com", get.call_args.args[0])
        self.assertEqual(get.call_count, 1)

        response.url = "https://www.invesco.com/us/en/financial-products/etfs.html"
        with patch.object(app.requests, "get", return_value=response) as get, patch.object(app.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "redirigió"):
                app.qqq_csv()
        self.assertEqual(get.call_count, 3)

    def test_csv_reintenta_un_error_transitorio_y_acepta_la_tabla_completa(self):
        csv = "Holding Ticker,Name,Security Type,Weight,Date\n" + "".join(
            f"T{i:02},Company {i},Equity,2,2026-11-18\n" for i in range(50)
        )
        no_disponible = type(
            "Response",
            (),
            {
                "status_code": 406,
                "content": b"",
                "text": "",
                "url": "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0",
            },
        )()
        disponible = type(
            "Response",
            (),
            {
                "status_code": 200,
                "content": csv.encode().ljust(2100),
                "text": csv,
                "url": no_disponible.url,
            },
        )()
        with patch.object(app.requests, "get", side_effect=[no_disponible, disponible]) as get, patch.object(app.time, "sleep") as sleep:
            tabla, fecha = app.qqq_csv()

        self.assertEqual(len(tabla), 50)
        self.assertEqual(fecha, self.FECHA)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2)


class CNBCWebTests(unittest.TestCase):
    def test_recarga_hasta_capturar_la_tabla_completa_en_el_mismo_contexto(self):
        class Locator:
            async def click(self, **kwargs):
                return None

            async def evaluate_all(self, _script):
                return ["<table><tr><td>TOTAL</td></tr></table>"]

            async def inner_text(self):
                return "Berkshire Cash and Market Capitalization"

        class Mouse:
            async def wheel(self, *_args):
                return None

        class Page:
            def __init__(self):
                self.reloads = 0
                self.waits = 0
                self.mouse = Mouse()

            async def goto(self, *_args, **_kwargs):
                return None

            async def reload(self, **_kwargs):
                self.reloads += 1

            async def wait_for_selector(self, *_args, **_kwargs):
                return None

            async def wait_for_timeout(self, _timeout):
                return None

            async def wait_for_function(self, *_args, **_kwargs):
                self.waits += 1
                if self.waits == 1:
                    raise RuntimeError("tabla todavía incompleta")

            async def evaluate(self, _script):
                return "Berkshire Cash and Market Capitalization"

            def locator(self, _selector):
                return Locator()

        class Context:
            def __init__(self):
                self.page = Page()
                self.closed = False

            async def new_page(self):
                return self.page

            async def close(self):
                self.closed = True

        context = Context()

        async def abrir_contexto(_nav):
            return context

        with patch.object(app, "contexto", side_effect=abrir_contexto), patch.object(
            app, "proc_brk", return_value={"valid": True}
        ) as validar:
            tablas, cuerpo = asyncio.run(app.brk_web(object()))

        self.assertEqual(context.page.reloads, 1)
        self.assertTrue(context.closed)
        validar.assert_called_once()
        self.assertIn("TOTAL", tablas[0])
        self.assertIn("Market Capitalization", cuerpo)


@unittest.skipUnless(shutil.which("node"), "Node.js is required to exercise the embedded optimizer")
class FronteraTests(unittest.TestCase):
    def test_frontier_is_refined_and_excludes_cartera_even_for_short_ranges(self):
        js = r"""
let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => source += chunk);
process.stdin.on('end', () => {
  const html = JSON.parse(source);
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const start = script.indexOf('const OPT_BASE=');
  const end = script.indexOf('function drawMarkowitz(', start);
  const C = {x: ''};
  const prices = {
    SPY: [100, 102, 101, 104],
    QQQ: [100, 103, 105, 107],
    'BRK-A': [100, 101, 100.5, 102],
    IWM: [100, 99, 102, 104]
  };
  const TS = prices.SPY.map((_, i) => Date.UTC(2026, 0, i + 1));
  const get = key => ({s: 0, p: prices[key]});
  const markowitz = new Function('C', 'TS', 'get', script.slice(start, end) + '; return markowitz;')(C, TS, get);
  const result = markowitz(0, 3);
  if (result.keys.includes('CG') || result.keys.length !== 3) throw new Error('Cartera entró en la optimización');
  if (result.points.length <= result.basePoints.length) throw new Error('La frontera no agregó refinamiento');
  for (const p of result.frontier) for (const q of result.points) {
    const dominates = q.vol <= p.vol + 1e-10 && q.cagr >= p.cagr - 1e-10 &&
      (q.vol < p.vol - 1e-10 || q.cagr > p.cagr + 1e-10);
    if (dominates) throw new Error('La frontera contiene una cartera dominada');
  }
  C.x = 'IWM';
  const short = markowitz(0, 1);
  if (!short.keys.includes('IWM') || short.n !== 1) throw new Error('Falló el caso corto o el activo Otro');
});
"""
        subprocess.run(
            ["node", "-e", js],
            input=json.dumps(app.HTML_T),
            check=True,
            capture_output=True,
            text=True,
        )


class ProcesamientoBrkTests(unittest.TestCase):
    def cuerpo(self):
        return (
            "Berkshire Cash as of November 1, 2026: $10 billion\n"
            "Excluding Rail Cash: $8 billion\n"
            "Berkshire Market Capitalization: $200 billion\n"
            "Holdings are as of November 1, 2026 and 13F filing on November 14, 2026\n"
            "except for: none. For more on Berkshire"
        )

    def tabla(self, total=100_000_000_000, posiciones=None):
        if posiciones is None:
            posiciones = [
                ["Apple Inc.", "AAPL", 60_000_000_000],
                ["Microsoft Corp.", "MSFT", 39_400_000_000],
                ["Preferred investment", "", 100_000_000],
            ]
        filas = [*posiciones, ["TOTAL", "", total]]
        return pd.DataFrame(filas, columns=["Company", "Symbol", "Value"]).to_html(index=False)

    def test_reconcilia_total_con_diferencia_aceptable_y_conserva_residual_bruto(self):
        out = app.proc_brk([self.tabla()], self.cuerpo())

        self.assertAlmostEqual(out["dif_total"], 0.5)
        self.assertAlmostEqual(out["pub"], 99_500_000_000)
        self.assertEqual(out["cash"], 10_000_000_000)
        self.assertAlmostEqual(out["pv"], (200_000_000_000 - 99_500_000_000 - 10_000_000_000) / 200_000_000_000 * 100)
        self.assertTrue(any(k.startswith("__BRK_SIN_TICKER_") for k in out["w"].index))

    def test_capitalizacion_sin_unidad_no_toma_la_b_de_berkshire_como_billones(self):
        cuerpo = self.cuerpo().replace(
            "Berkshire Market Capitalization: $200 billion",
            "Berkshire Market Capitalization: $200,000,000,000\n"
            "Berkshire Cash as of November 1, 2026: $10 billion",
        )
        out = app.proc_brk([self.tabla()], cuerpo)

        self.assertEqual(out["cap"], 200_000_000_000)
        self.assertAlmostEqual(out["ef"], 5)
        self.assertAlmostEqual(out["pv"], 45.25)

    def test_formatea_capitalizacion_en_mil_millones_legibles(self):
        self.assertEqual(
            app.fmt_mil_millones(1_245_800_902_047),
            "US$ 1,245.8 mil millones",
        )

    def test_extrae_variacion_trimestral_del_efectivo_bruto_y_neto(self):
        cuerpo = self.cuerpo().replace(
            "Berkshire Cash as of November 1, 2026: $10 billion",
            "Berkshire Cash as of Sep 30, 2026: $10 billion "
            "(Up 3.3% from Jun 30, 2026)",
        ).replace(
            "Excluding Rail Cash: $8 billion",
            "Excluding Rail Cash and Subtracting T-Bills Payable: $9 billion "
            "(Down 1.9% from Jun 30, 2026)",
        )
        out = app.proc_brk([self.tabla()], cuerpo)

        self.assertEqual(out["fecha_efectivo"], "2026-09-30")
        self.assertEqual(out["cash_neto"], 9_000_000_000)
        self.assertEqual(out["cash_cambio"], 3.3)
        self.assertEqual(out["cash_cambio_desde"], "2026-06-30")
        self.assertEqual(out["cash_neto_cambio"], -1.9)
        self.assertEqual(out["cash_neto_cambio_desde"], "2026-06-30")
        self.assertEqual(
            app.fmt_variacion(3.3, "2026-06-30"),
            " · +3.3% vs. 30/06/2026",
        )

    def test_rechaza_tabla_parcial_total_ausente_y_diferencia_material(self):
        incompleta = self.tabla().replace("<td>TOTAL</td>", "<td>SUMMARY</td>")
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app.proc_brk([incompleta], self.cuerpo())

        parcial = self.tabla(posiciones=[["Apple Inc.", "AAPL", 98_000_000_000]])
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app.proc_brk([parcial], self.cuerpo())

        sin_nombre = self.tabla(posiciones=[["", "AAPL", 99_500_000_000]])
        with self.assertRaisesRegex(RuntimeError, "sin nombre de posición"):
            app.proc_brk([sin_nombre], self.cuerpo())

    def test_excluye_metadatos_que_cnbc_agrega_despues_de_total(self):
        tabla = self.tabla().replace(
            "</table>",
            '<tr><td></td><td>Berkshire Market Capitalization:</td><td>$200 billion</td></tr>'
            '<tr><td>Berkshire Cash as of November 1, 2026:</td><td></td><td></td></tr>'
            '<tr><td>$10 billion (Up 3% from prior quarter)</td><td></td><td></td></tr>'
            '<tr><td>Excluding Rail Cash:</td><td></td><td></td></tr>'
            '<tr><td>$8 billion</td><td></td><td></td></tr></table>',
        )
        out = app.proc_brk([tabla], self.cuerpo())

        self.assertAlmostEqual(out["dif_total"], 0.5)
        self.assertEqual(out["pub"], 99_500_000_000)
        self.assertEqual(out["lineas"], 3)

    def test_rechaza_tickers_duplicados_y_valores_negativos(self):
        duplicada = self.tabla(
            total=100,
            posiciones=[["Apple Inc.", "AAPL", 50], ["Other Apple", "AAPL", 49.5]],
        )
        with self.assertRaisesRegex(RuntimeError, "repetidos"):
            app.proc_brk([duplicada], self.cuerpo())

        negativa = self.tabla(
            total=100,
            posiciones=[["Apple Inc.", "AAPL", 101], ["Other Inc.", "MSFT", -1]],
        )
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app.proc_brk([negativa], self.cuerpo())


class ConsolidacionTests(unittest.TestCase):
    def fuentes(self, spy=None, qqq=None):
        spy = spy or {
            "w": pd.Series({"AAPL": 95.0, "BRK": 4.0}),
            "n": pd.Series({"AAPL": "Apple", "BRK": "Berkshire"}),
            "ef": 1.0,
            "raro": 0.0,
            "bruto": 100.0,
        }
        qqq = qqq or {
            "w": pd.Series({"MSFT": 99.0}),
            "n": pd.Series({"MSFT": "Microsoft"}),
            "ef": 1.0,
            "desconocido": 0.0,
            "bruto": 100.0,
        }
        brk = {
            "w": pd.Series({"KO": 70.0}),
            "n": pd.Series({"KO": "Coca-Cola"}),
            "ef": 10.0,
            "pv": 20.0,
        }
        return spy, qqq, brk

    def test_brecha_pequena_se_expone_sin_reescalar_y_brecha_material_falla(self):
        spy, qqq, brk = self.fuentes()
        spy["w"] = pd.Series({"AAPL": 99.6})
        spy["n"] = pd.Series({"AAPL": "Apple"})
        spy["ef"] = 0.0
        spy["bruto"] = 99.6

        data, _, gap = app.armar(spy, qqq, brk, [], "")
        self.assertEqual(data["s"][data["t"].index("AAPL")], 99.6)
        residual = data["t"].index("__SPY_NO_ASIGNADO")
        self.assertEqual(data["s"][residual], 0.4)
        self.assertAlmostEqual(gap["S"], 0.4)

        spy["w"] = pd.Series({"AAPL": 98.9})
        with self.assertRaisesRegex(RuntimeError, "faltan"):
            app.armar(spy, qqq, brk, [], "")

        spy["w"] = pd.Series({"AAPL": 101.0})
        with self.assertRaisesRegex(RuntimeError, "más de 100"):
            app.armar(spy, qqq, brk, [], "")

    def test_reemplaza_brk_en_spy_sin_doble_conteo(self):
        spy, qqq, brk = self.fuentes()
        data, _, _ = app.armar(spy, qqq, brk, [], "")
        self.assertEqual(data["bs"], 4.0)
        self.assertNotIn("BRK", data["t"])

        asignacion_spy, asignacion_qqq, asignacion_brk = 60, 25, 15
        brk_total = asignacion_brk + asignacion_spy * data["bs"] / 100
        cierre = (
            asignacion_spy * (sum(data["s"]) + data["cs"]) / 100
            + asignacion_qqq * (sum(data["q"]) + data["cq"]) / 100
            + brk_total * (sum(data["b"]) + data["cb"] + data["bp"]) / 100
        )
        self.assertAlmostEqual(cierre, 100)

    def test_conserva_sufijos_de_tickers_y_cuenta_enlaces_no_empresas(self):
        self.assertEqual(app.canon("BABA.SW"), "BABA.SW")
        self.assertEqual(app.canon("7203.T"), "7203.T")
        self.assertEqual(app.canon("RDS/A"), "RDS/A")
        self.assertEqual(app.canon("BRK.B"), "BRK")
        spy, qqq, brk = self.fuentes()
        enlaces = [
            {"texto": "Negocio A", "href": "https://example.com/a"},
            {"texto": "Negocio A", "href": "https://example.com/a#about"},
            {"texto": "Negocio A", "href": "https://example.com/another"},
        ]
        _, listados, _ = app.armar(spy, qqq, brk, enlaces, "")
        self.assertEqual(len(listados), 2)
        self.assertEqual(app.contar_negocios(listados), 1)
        self.assertIn("nombre enlazado único, no por entidad legal", app.HTML_T)
        self.assertIn("__TITULO_PRIVADOS__", app.HTML_T)


class ResultadosBrkTests(unittest.TestCase):
    def texto(self, ganancias="10", antes_equity="30", antes_impuestos="32",
              impuestos="8", neto="24", atribuible="23", ingresos="100"):
        segmentos_actuales = ["10", "15", "20", "25", "5", "8", "17", ingresos]
        return "\n".join(
            [
                "CONSOLIDATED STATEMENTS OF EARNINGS",
                f"Total revenues {ingresos} 90 300 270",
                f"Investment gains {ganancias} 5 30 20",
                "Total costs and expenses 80 70 240 210",
                f"Earnings before income taxes and equity method earnings {antes_equity} 25 90 80",
                "Equity method earnings (losses) 2 1 4 2",
                f"Earnings before income taxes {antes_impuestos} 26 94 82",
                f"Income tax expense {impuestos} 6 24 20",
                f"Net earnings {neto} 20 70 62",
                "Earnings attributable to noncontrolling interests 1 1 3 2",
                f"Net earnings attributable to Berkshire shareholders {atribuible} 19 67 60",
                "CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME",
                "Note 23. Revenues from contracts with customers",
                "Three months ended September 30, 2026",
                " ".join("$ " + value for value in segmentos_actuales),
                "Nine months ended September 30, 2026",
                "Three months ended September 30, 2025",
                "$ 9 $ 13 $ 18 $ 24 $ 4 $ 7 $ 15 $ 90",
                "Nine months ended September 30, 2025",
                "Note 24. Business segment data",
            ]
        )

    def test_parsea_y_reconcilia_el_trimestre_con_el_mismo_trimestre_anterior(self):
        resultado = app.procesar_resultados_brk(
            self.texto(), 3, 2026, "https://www.berkshirehathaway.com/qtrly/3rdqtr26.pdf"
        )

        self.assertEqual(resultado["periodo"], "Q3 2026")
        self.assertEqual(resultado["comparacion"], "Q3 2025")
        self.assertEqual(resultado["corte"], "2026-09-30")
        self.assertEqual([s["actual"] for s in resultado["segmentos"]], [10, 15, 20, 25, 5, 8, 17])
        self.assertEqual([s["anterior"] for s in resultado["segmentos"]], [9, 13, 18, 24, 4, 7, 15])
        self.assertEqual(resultado["actual"]["atribuible"], 23)
        self.assertEqual(resultado["operativo"], 20)
        self.assertTrue(resultado["puente_completo"])

    def test_limita_el_bloque_de_ingresos_aun_sin_tabla_acumulada_de_nueve_meses(self):
        texto = self.texto().replace("September 30", "March 31")
        texto = texto.replace("Nine months ended March 31, 2026\n", "")
        texto = texto.replace("Nine months ended March 31, 2025\n", "")
        resultado = app.procesar_resultados_brk(texto, 1, 2026, "fixture")

        self.assertEqual(resultado["periodo"], "Q1 2026")
        self.assertEqual(resultado["corte"], "2026-03-31")
        self.assertEqual(sum(s["actual"] for s in resultado["segmentos"]), 100)

    def test_rechaza_informe_incompleto_o_ingresos_por_segmento_no_reconciliados(self):
        texto = self.texto()
        with self.assertRaisesRegex(RuntimeError, "fila"):
            app.procesar_resultados_brk(
                texto.replace("Income tax expense 8 6 24 20\n", ""),
                3,
                2026,
                "fixture",
            )
        with self.assertRaisesRegex(RuntimeError, "segmentos contra ingresos"):
            app.procesar_resultados_brk(
                texto.replace("$ 17 $ 100", "$ 19 $ 100"),
                3,
                2026,
                "fixture",
            )
        with self.assertRaisesRegex(RuntimeError, "nota 23"):
            app.procesar_resultados_brk(
                texto.replace("Note 23. Revenues from contracts with customers", "Note 23 missing"),
                3,
                2026,
                "fixture",
            )

    def test_no_presenta_como_flujo_positivo_una_perdida_de_inversion(self):
        resultado = app.procesar_resultados_brk(
            self.texto(ganancias="(5)", antes_equity="15", antes_impuestos="17",
                       impuestos="8", neto="9", atribuible="8"),
            3,
            2026,
            "fixture",
        )

        self.assertFalse(resultado["puente_completo"])
        self.assertEqual(resultado["actual"]["ganancias_inversion"], -5)
        self.assertEqual(resultado["actual"]["neto"], 9)

    def test_no_admite_ingresos_negativos_de_segmentos_como_flujos(self):
        texto = self.texto(
            ingresos="80", antes_equity="10", antes_impuestos="12", impuestos="8",
            neto="4", atribuible="3",
        ).replace("$ 10 $ 15", "$ (10) $ 15")
        resultado = app.procesar_resultados_brk(texto, 3, 2026, "fixture")

        self.assertFalse(resultado["segmentos_no_negativos"])
        self.assertFalse(resultado["puente_completo"])
        self.assertEqual(resultado["segmentos"][0]["actual"], -10)

    def test_descubre_el_informe_mas_reciente_sin_ordenar_mal_anios_de_dos_digitos(self):
        respuestas = [
            type("Response", (), {"text": (
                '<a href="/qtrly/links3rdqtr99.html">1999</a>'
                '<a href="/qtrly/links3rdqtr25.html">2025</a>'
                '<a href="/qtrly/links2ndqtr26.html">Q2 2026</a>'
                '<a href="/qtrly/links3rdqtr26.html">Q3 2026</a>'
            ), "content": b"", "url": "https://www.berkshirehathaway.com/reports.html",
                                  "raise_for_status": lambda self: None})(),
            type("Response", (), {"text": '<a href="3rdqtr26.pdf">PDF</a>',
                                  "content": b"", "url": "https://www.berkshirehathaway.com/qtrly/links3rdqtr26.html",
                                  "raise_for_status": lambda self: None})(),
            type("Response", (), {"text": "", "content": b"%PDF fixture",
                                  "url": "https://www.berkshirehathaway.com/qtrly/3rdqtr26.pdf",
                                  "raise_for_status": lambda self: None})(),
        ]
        fake_reader = type("Reader", (), {"pages": []})()
        with patch.object(app.requests.Session, "get", side_effect=respuestas), \
                patch("pypdf.PdfReader", return_value=fake_reader), \
                patch.object(app, "procesar_resultados_brk", return_value={"periodo": "Q3 2026"}) as parsear:
            resultado = app.bajar_resultados_brk()

        self.assertEqual(resultado["periodo"], "Q3 2026")
        self.assertEqual(parsear.call_args.args[1:3], (3, 2026))
        self.assertEqual(parsear.call_args.args[3], "https://www.berkshirehathaway.com/qtrly/3rdqtr26.pdf")

    def test_busca_pdf_oficial_directo_si_el_indice_responde_403(self):
        solicitudes = []

        class Response:
            def __init__(self, url, status, content=b"", text=""):
                self.url, self.status_code = url, status
                self.content, self.text = content, text

            def raise_for_status(self):
                if self.status_code >= 400:
                    error = app.requests.HTTPError(f"HTTP {self.status_code}")
                    error.response = self
                    raise error

        def get(url, **kwargs):
            solicitudes.append(url)
            if url.endswith("/reports.html"):
                return Response(url, 403)
            if url.endswith("/3rdqtr26.pdf"):
                return Response(url, 200, b"%PDF synthetic")
            return Response(url, 404)

        fake_reader = type("Reader", (), {"pages": []})()
        with patch.object(app.requests.Session, "get", side_effect=get), \
                patch.object(app, "AHORA", app.AHORA.replace(year=2026, month=11, day=18)), \
                patch("pypdf.PdfReader", return_value=fake_reader), \
                patch.object(app, "procesar_resultados_brk", return_value={"periodo": "Q3 2026"}) as parsear:
            resultado = app.bajar_resultados_brk()

        self.assertEqual(resultado["periodo"], "Q3 2026")
        self.assertEqual(solicitudes, [
            "https://www.berkshirehathaway.com/reports.html",
            "https://www.berkshirehathaway.com/qtrly/3rdqtr26.pdf",
        ])
        self.assertEqual(parsear.call_args.args[1:3], (3, 2026))
        self.assertEqual(parsear.call_args.args[3], solicitudes[-1])


class SubsidiariasTests(unittest.TestCase):
    def test_descarga_reintenta_403_y_usa_el_host_oficial_con_www(self):
        enlaces = "".join(
            f'<a href="https://example.com/{i}">Negocio {i}</a>'
            for i in range(app.SUBS_MIN_ENLACES)
        )
        html = (
            "<html><head><title>LINKS TO BERKSHIRE HATHAWAY SUB. COMPANIES</title></head>"
            f"<body>{enlaces}</body></html>"
        )

        class Response:
            def __init__(self, status_code):
                self.status_code = status_code
                self.url = app.URL_SUBS
                self.text = html

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise app.requests.HTTPError(f"HTTP {self.status_code}")

        with patch.object(app.requests, "get", side_effect=[Response(403), Response(200)]) as get, \
                patch.object(app.time, "sleep") as sleep:
            resultado = app.descargar_subsidiarias()

        self.assertEqual(len(resultado), app.SUBS_MIN_ENLACES)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.args[0], "https://www.berkshirehathaway.com/subs/sublinks.html")
        sleep.assert_called_once_with(2)

    def test_acepta_el_directorio_oficial_y_cuenta_nombres_unicos(self):
        enlaces = "".join(
            f'<a href="https://example.com/{i}">Negocio {i // 2}</a>'
            for i in range(21)
        )
        html = (
            "<html><head><title>LINKS TO BERKSHIRE HATHAWAY SUB. COMPANIES</title></head>"
            f"<body>{enlaces}<a href='https://example.com/privacy'>Privacy Policy</a></body></html>"
        )

        resultado = app.extraer_subsidiarias(html)

        self.assertEqual(len(resultado), 21)
        self.assertEqual(app.contar_negocios([(x["texto"], x["href"]) for x in resultado]), 11)

    def test_rechaza_pagina_de_error_y_directorio_incompleto(self):
        error = '<title>GoDaddy</title><a href="https://godaddy.com">GoDaddy</a>'
        parcial = (
            "<title>LINKS TO BERKSHIRE HATHAWAY SUB. COMPANIES</title>"
            '<a href="https://supportx.sucuri.net/">open a support ticket</a>'
            '<a href="https://example.com/1">Negocio</a>'
            '<a href="https://godaddy.com/agreements/privacy">Privacy Policy</a></body></html>'
        )
        truncado = (
            "<title>LINKS TO BERKSHIRE HATHAWAY SUB. COMPANIES</title>"
            + "".join(f'<a href="https://example.com/{i}">Negocio {i}</a>' for i in range(21))
        )

        for html in (error, parcial, truncado):
            with self.subTest(html=html), self.assertRaisesRegex(RuntimeError, "directorio"):
                app.extraer_subsidiarias(html)


if __name__ == "__main__":
    unittest.main()
