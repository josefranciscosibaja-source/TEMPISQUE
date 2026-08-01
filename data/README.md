# Archivos requeridos

Esta carpeta debe conservar los tres archivos que ya existen en el
repositorio TEMPISQUE:

- `nivel_guardia_diario_reconstruido.csv`
- `cauce_tempisque.geojson`
- `subcuencas_guardia.geojson`

GitHub Actions creará y actualizará automáticamente:

- `clima_guardia_gee.csv`
- `spi_guardia_gee.csv`
- `cuenca_aportante_guardia_gee.geojson`
- `actualizacion_climatica.json`

No elimine los archivos climáticos después de la primera ejecución:
constituyen el histórico base para las actualizaciones incrementales.
