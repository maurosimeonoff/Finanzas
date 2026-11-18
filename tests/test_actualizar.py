import unittest
from unittest.mock import patch

import pandas as pd

import actualizar as app


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

    def test_rechaza_fuente_incompleta_y_pesos_negativos(self):
        with self.assertRaisesRegex(RuntimeError, "fecha"):
            raw = self.workbook([["AAPL", "Apple Inc.", 100]])
            raw.iloc[0, 0] = ""
            with patch.object(app.pd, "read_excel", return_value=raw):
                app.proc_spy(b"fixture")

        with self.assertRaisesRegex(RuntimeError, "negativos"):
            self.parse([["AAPL", "Apple Inc.", 101], ["MSFT", "Microsoft", -1]])

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

    def test_rechaza_tabla_parcial_total_ausente_y_diferencia_material(self):
        incompleta = self.tabla().replace("<td>TOTAL</td>", "<td>SUMMARY</td>")
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app.proc_brk([incompleta], self.cuerpo())

        parcial = self.tabla(posiciones=[["Apple Inc.", "AAPL", 98_000_000_000]])
        with self.assertRaisesRegex(RuntimeError, "incompleta"):
            app.proc_brk([parcial], self.cuerpo())

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
        self.assertIn("Enlaces a negocios privados", app.HTML_T)


if __name__ == "__main__":
    unittest.main()
