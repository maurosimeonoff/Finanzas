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
                ["AAPL", "Apple Inc.", "Equity", 93],
                ["", "Index future", "Index Future", 1],
                ["", "Guarantee", "Guarantee", 1],
                ["", "Currency collateral", "Currency Collateral", 1],
                ["", "Synthetic cash", "Synthetic Cash", 1],
                ["", "Foreign currency", "Currency", 1],
                ["USD", "US Dollar", "Cash", 1],
                ["USD", "Dollar future", "Currency", 0.5],
                ["", "Unidentified", "Other", 0.5],
            ]
        )

        self.assertEqual(out["ef"], 1)
        self.assertEqual(out["w"]["__QQQ_FUTUROS"], 1)
        self.assertEqual(out["w"]["__QQQ_GARANTIAS"], 1)
        self.assertEqual(out["w"]["__QQQ_COLATERALES"], 1)
        self.assertEqual(out["w"]["__QQQ_EFECTIVO_SINTETICO"], 1)
        self.assertEqual(out["w"]["__QQQ_DIVISA"], 1.5)
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

    def test_json_selecciona_tabla_completa_por_suma_no_por_longitud(self):
        correcta = [{"ticker": f"T{i:02}", "name": f"Company {i}", "weight": 100 / 50} for i in range(50)]
        distractora = [{"ticker": f"D{i:02}", "name": f"Decoy {i}", "weight": 1} for i in range(70)]
        encontrada = app.buscar({"long": distractora, "holdings": correcta})

        self.assertEqual(encontrada, correcta)
        self.assertIsNone(app.buscar({"holdings": correcta[:49]}))

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
        with patch.object(app.requests, "get", return_value=response) as get:
            tabla, fecha = app.qqq_csv()

        self.assertEqual(len(tabla), 50)
        self.assertEqual(fecha, self.FECHA)
        self.assertIn("www.invesco.com", get.call_args.args[0])

        response.url = "https://www.invesco.com/us/en/financial-products/etfs.html"
        with patch.object(app.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "redirigió"):
                app.qqq_csv()


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
