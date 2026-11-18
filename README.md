# Cartera global: SPY + QQQ + BRK

Tablero interactivo que descompone una cartera repartida entre SPY, QQQ y Berkshire Hathaway en las empresas que contiene (sin doble conteo, con el efectivo y el residual de mercado de BRK identificados) y la compara con SPY, QQQ y BRK-A.

**Tablero actualizado:** https://maurosimeonoff.github.io/Finanzas/ &nbsp;·&nbsp; [Abrir en Colab](https://colab.research.google.com/github/maurosimeonoff/Finanzas/blob/main/Finanzas-GitHub.ipynb)

## Cómo funciona
GitHub Actions ejecuta `actualizar.py` todos los días a las 18:00 (Buenos Aires) y publica `docs/index.html` en GitHub Pages. El cuaderno de Colab descarga ese mismo `actualizar.py` y lo ejecuta: no hay dos copias del código.

## Archivos
| Archivo | Uso |
|---|---|
| `actualizar.py` | Único programa (se edita solo acá) |
| `.github/workflows/actualizar.yml` | Programación diaria 18:00 |
| `Finanzas-GitHub.ipynb` | Acceso desde Colab (1 celda) |
| `docs/index.html` | Página publicada (se genera sola) |

## Puesta en marcha (una sola vez)
Settings → Pages → *Deploy from a branch* → `main`, carpeta `/docs`. Settings → Actions → General → *Read and write permissions*. Luego Actions → *Actualizar cartera global* → **Run workflow**.
