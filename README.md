# SAT de Estiaje Hidrométrico — Estación Guardia

## Componentes

- `streamlit_app.py`: dashboard.
- `scripts/update_climate.py`: actualización incremental desde GEE.
- `.github/workflows/update_climate.yml`: ejecución automática diaria.
- `requirements.txt`: dependencias de Streamlit.
- `requirements-update.txt`: dependencias del actualizador.

## Flujo de datos

- Nivel, cauce principal y subcuencas: archivos versionados en `data/`.
- Precipitación diaria: CHIRPS mediante Google Earth Engine.
- ETo equivalente diaria: ERA5-Land mediante Google Earth Engine.
- SPI-1, SPI-3 y SPI-6: ajuste gamma sobre CHIRPS.
- Pronóstico: GeoTIFF ICON descargado automáticamente por la aplicación.
- Geoportal: rasters consultados directamente desde GEE.
