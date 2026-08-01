# Guía para publicar el SAT Guardia

Esta guía está pensada para una primera experiencia con GitHub. No necesita
usar comandos de Git ni ejecutar nuevamente el túnel de Cloudflare.

## 1. Qué hará el sistema

El flujo completo será:

```text
GEE (CHIRPS y ERA5-Land)
          ↓
GitHub Actions revisa los datos todos los días
          ↓
Actualiza los CSV climáticos dentro del repositorio
          ↓
Streamlit usa esos CSV y mantiene GEE para el geoportal
```

La primera ejecución genera el histórico desde 1981. Las siguientes revisan
una superposición de siete días y agregan únicamente las fechas nuevas.

## 2. Archivos que deben quedar en TEMPISQUE

Al finalizar, la raíz del repositorio debe verse así:

```text
TEMPISQUE/
├── .github/
│   └── workflows/
│       └── update_climate.yml
├── .streamlit/
│   └── config.toml
├── data/
│   ├── nivel_guardia_diario_reconstruido.csv
│   ├── cauce_tempisque.geojson
│   ├── subcuencas_guardia.geojson
│   └── README.md
├── scripts/
│   └── update_climate.py
├── .gitignore
├── requirements.txt
├── requirements-update.txt
└── streamlit_app.py
```

Los tres primeros archivos de `data/` ya existen en su repositorio y deben
conservarse. No suba todavía archivos de clima vacíos.

## 3. Copiar el proyecto usando GitHub Desktop

GitHub Desktop es la opción más sencilla para evitar la línea de comandos.

1. Instale GitHub Desktop desde <https://desktop.github.com/>.
2. Abra GitHub Desktop e inicie sesión con su cuenta de GitHub.
3. Seleccione **File > Clone repository**.
4. Abra la pestaña **URL**.
5. En Repository URL escriba:
   `josefranciscosibaja-source/TEMPISQUE`.
6. Elija una carpeta fácil de encontrar y presione **Clone**.
7. En el Explorador de Windows, abra la carpeta clonada `TEMPISQUE`.
8. Copie dentro de ella **el contenido** de esta carpeta de entrega. No copie
   la carpeta exterior como una subcarpeta.
9. Si Windows pregunta si desea combinar la carpeta `data`, acepte. No elimine
   sus tres archivos existentes.
10. Regrese a GitHub Desktop. Debe aparecer una lista de archivos modificados.
11. En **Summary** escriba:
    `Preparar Streamlit y actualización automática GEE`.
12. Presione **Commit to main**.
13. Presione **Push origin**.

Después del `Push`, abra en el navegador:
<https://github.com/josefranciscosibaja-source/TEMPISQUE>.

Compruebe que `streamlit_app.py`, `requirements.txt`, `scripts/` y
`.github/workflows/` estén visibles.

## 4. Crear el secreto de Earth Engine en GitHub

Este secreto será usado únicamente por la actualización automática.

1. Abra el repositorio TEMPISQUE en GitHub.
2. Presione **Settings**.
3. En el menú izquierdo seleccione **Secrets and variables > Actions**.
4. Presione **New repository secret**.
5. En **Name** escriba exactamente:

   ```text
   GEE_SERVICE_ACCOUNT_JSON
   ```

6. En **Secret** pegue el contenido completo de su llave JSON, desde `{`
   hasta `}`.
7. Presione **Add secret**.

Pegue solamente el JSON. No agregue comillas triples ni el nombre del secreto.
GitHub no permite volver a visualizar su contenido; eso es normal.

## 5. Permitir que GitHub Actions actualice los CSV

1. Dentro de **Settings**, seleccione **Actions > General**.
2. Confirme que las acciones estén permitidas.
3. Baje hasta **Workflow permissions**.
4. Seleccione **Read and write permissions**.
5. Presione **Save**.

El workflow también declara `contents: write`, pero esta configuración evita
que una política de solo lectura impida guardar los CSV.

## 6. Ejecutar por primera vez

La primera ejecución debe construir los 44 años históricos.

1. Abra la pestaña **Actions** del repositorio.
2. En la izquierda elija **Actualizar clima desde GEE**.
3. Presione **Run workflow**.
4. Active **Recalcular todo el histórico desde 1981**.
5. Presione el botón verde **Run workflow**.
6. Espere a que aparezca la ejecución y ábrala.

La ejecución pasa por seis etapas. La primera vez puede tardar varios minutos.
Debe terminar con un círculo verde.

Después, vuelva a la pestaña **Code** y abra `data/`. Deben aparecer:

- `clima_guardia_gee.csv`
- `spi_guardia_gee.csv`
- `cuenca_aportante_guardia_gee.geojson`
- `actualizacion_climatica.json`

Abra `actualizacion_climatica.json` y verifique
`ultima_fecha_comun`. Esa es la fecha más reciente compartida por CHIRPS y
ERA5-Land.

## 7. Qué ocurrirá diariamente

El workflow se ejecutará todos los días a las 6:30 a. m., hora de Costa Rica.

- Si hay días nuevos, actualizará y guardará los CSV.
- Si GEE todavía no publicó datos nuevos, finalizará correctamente sin crear
  un commit.
- No volverá a procesar los 44 años.
- El SPI se recalcula sobre la serie mensual completa, que es un cálculo
  pequeño, y solo incorpora meses completos. El ajuste utiliza años calendario
  completos, igual que el SPI raster del geoportal.

La opción **Recalcular todo el histórico** debe usarse solamente si cambia la
metodología, la geometría o se necesita reconstruir archivos dañados.

## 8. Publicar en Streamlit Community Cloud

1. Ingrese a <https://share.streamlit.io/>.
2. Inicie sesión usando GitHub.
3. Presione **Create app**.
4. Seleccione:

   - Repository: `josefranciscosibaja-source/TEMPISQUE`
   - Branch: `main`
   - Main file path: `streamlit_app.py`

5. Abra **Advanced settings**.
6. Si puede elegir versión de Python, seleccione **Python 3.11**.
7. En **Secrets** pegue la estructura siguiente, sustituyendo
   `PEGAR_AQUI_EL_JSON_COMPLETO` por el contenido real:

   ```toml
   GEE_SERVICE_ACCOUNT_JSON = '''
   PEGAR_AQUI_EL_JSON_COMPLETO
   '''
   ```

   Debe quedar, por ejemplo:

   ```toml
   GEE_SERVICE_ACCOUNT_JSON = '''
   {"type":"service_account","project_id":"...","private_key":"..."}
   '''
   ```

8. Presione **Deploy**.

Streamlit instalará `requirements.txt` y ejecutará `streamlit_app.py`. No debe
subir `.streamlit/secrets.toml` ni la llave JSON al repositorio.

## 9. Diferencia entre los dos secretos

La misma llave se guarda en dos plataformas, pero no en GitHub como archivo:

| Lugar | Formato | Uso |
|---|---|---|
| GitHub Actions Secret | JSON puro | Actualizar clima y SPI |
| Streamlit Secrets | Variable TOML con JSON | Geoportal y consultas GEE |

Ambas copias están cifradas y no forman parte del código público.

## 10. Cómo comprobar que todo funciona

Revise estas cuatro señales:

1. En GitHub, **Actions** muestra una ejecución verde.
2. `data/actualizacion_climatica.json` muestra una fecha común válida.
3. La ventana climática de Streamlit muestra esa misma fecha final.
4. El geoportal carga DEM, precipitación, ETo equivalente y SPI.

## 11. Errores frecuentes

### `Falta el secreto GEE_SERVICE_ACCOUNT_JSON`

El secreto no existe o el nombre no coincide exactamente. Revise el paso 4.

### `Permission denied` al hacer `git push`

Revise **Settings > Actions > General > Workflow permissions** y seleccione
permisos de lectura y escritura.

### Earth Engine indica que el proyecto no está autorizado

Confirme que el `project_id` de la llave corresponde a un proyecto registrado
para Earth Engine, con la API habilitada y la cuenta de servicio autorizada.

### El dashboard dice que faltan los CSV climáticos

Todavía no se ejecutó con éxito la primera actualización completa. Ejecute el
paso 6 antes de desplegar Streamlit.

### La actualización terminó bien, pero no creó commit

No es un error. Significa que GEE aún no publicó una nueva fecha común o que
los datos revisados no cambiaron.

### El workflow programado dejó de ejecutarse

GitHub puede desactivar workflows programados de repositorios públicos sin
actividad durante 60 días. Abra **Actions**, seleccione el workflow y vuelva a
habilitarlo. Las actualizaciones normales del clima suelen mantener activo el
repositorio.

## 12. Seguridad

- Nunca suba el JSON a `data/`, `.streamlit/` ni otra carpeta pública.
- Nunca lo copie dentro de `streamlit_app.py`.
- No publique capturas donde aparezca `private_key`.
- Si la llave se expone, elimínela en Google Cloud y genere una nueva.
