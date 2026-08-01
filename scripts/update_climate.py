"""Actualización incremental de CHIRPS, ERA5-Land y SPI para el SAT Guardia.

El script está diseñado para GitHub Actions:

* Si no existe el histórico, consulta desde 1981 en bloques de cinco años.
* Si ya existe, vuelve a consultar siete días de superposición y agrega
  únicamente las fechas nuevas.
* Usa la última fecha común disponible entre CHIRPS y ERA5-Land.
* Escribe los CSV solamente después de validar continuidad y valores.

La credencial se recibe exclusivamente mediante la variable de entorno
GEE_SERVICE_ACCOUNT_JSON. Nunca debe almacenarse dentro del repositorio.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Iterator

import ee
import numpy as np
import pandas as pd
from google.oauth2 import service_account
from scipy.stats import gamma as scipy_gamma
from scipy.stats import norm


CLIMATE_START = pd.Timestamp("1981-01-01")
OVERLAP_DAYS = 7
FULL_BLOCK_YEARS = 5

CHIRPS_ASSET = "UCSB-CHG/CHIRPS/DAILY"
ERA5_ASSET = "ECMWF/ERA5_LAND/DAILY_AGGR"

CLIMATE_FILENAME = "clima_guardia_gee.csv"
SPI_FILENAME = "spi_guardia_gee.csv"
SUBBASINS_FILENAME = "subcuencas_guardia.geojson"
BASIN_FILENAME = "cuenca_aportante_guardia_gee.geojson"
STATUS_FILENAME = "actualizacion_climatica.json"

EE_SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/cloud-platform",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Actualiza clima y SPI del SAT Guardia desde GEE."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directorio que contiene los datos del repositorio.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recalcula todo el período desde 1981.",
    )
    return parser.parse_args()


def initialize_earth_engine() -> str:
    raw_secret = os.environ.get("GEE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_secret:
        raise RuntimeError(
            "Falta el secreto GEE_SERVICE_ACCOUNT_JSON. "
            "Créelo en Settings > Secrets and variables > Actions."
        )

    try:
        account_info = json.loads(raw_secret)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GEE_SERVICE_ACCOUNT_JSON no contiene un JSON válido."
        ) from exc

    private_key = account_info.get("private_key")
    if isinstance(private_key, str):
        account_info["private_key"] = private_key.replace("\\n", "\n")

    project = (
        os.environ.get("EE_PROJECT")
        or account_info.get("project_id")
    )
    email = account_info.get("client_email")
    if not project or not email:
        raise RuntimeError(
            "La credencial debe contener project_id y client_email."
        )

    credentials = service_account.Credentials.from_service_account_info(
        account_info,
        scopes=EE_SCOPES,
    )
    ee.Initialize(credentials=credentials, project=project)
    # Una consulta pequeña confirma que autenticación, permisos y proyecto
    # funcionan antes de iniciar cálculos de mayor duración.
    ee.Number(1).getInfo()
    return project


def load_analysis_geometry(
    subbasins_path: Path,
) -> tuple[ee.Geometry, dict]:
    if not subbasins_path.is_file():
        raise FileNotFoundError(
            f"No existe {subbasins_path}. El archivo ya debe estar en data/."
        )

    geojson = json.loads(subbasins_path.read_text(encoding="utf-8-sig"))
    features = [
        feature
        for feature in geojson.get("features", [])
        if feature.get("geometry")
    ]
    if geojson.get("type") != "FeatureCollection" or not features:
        raise ValueError(
            "subcuencas_guardia.geojson no es un FeatureCollection válido."
        )

    feature_collection = ee.FeatureCollection(
        [
            ee.Feature(
                ee.Geometry(feature["geometry"]),
                feature.get("properties", {}),
            )
            for feature in features
        ]
    )
    geometry = feature_collection.geometry(maxError=100)
    return geometry, geojson


def write_basin_geometry(
    analysis_geometry: ee.Geometry,
    output_path: Path,
) -> None:
    basin = {
        "type": "Feature",
        "properties": {
            "nombre": "Área aportante aguas arriba de la estación Guardia",
            "estacion": "Guardia 190302",
            "fuente_geometria": SUBBASINS_FILENAME,
            "metodo": "Unión de las subcuencas aportantes",
        },
        "geometry": analysis_geometry.getInfo(),
    }
    atomic_write_text(
        output_path,
        json.dumps(basin, ensure_ascii=False, separators=(",", ":")),
    )


def latest_source_dates() -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    sources = {
        "chirps": ee.ImageCollection(CHIRPS_ASSET),
        "era5": ee.ImageCollection(ERA5_ASSET),
    }
    latest = ee.Dictionary(
        {
            name: ee.Image(
                collection.sort("system:time_start", False).first()
            ).date().format("YYYY-MM-dd")
            for name, collection in sources.items()
        }
    ).getInfo()

    chirps_last = pd.Timestamp(latest["chirps"]).normalize()
    era5_last = pd.Timestamp(latest["era5"]).normalize()
    common_last = min(chirps_last, era5_last)
    if common_last < CLIMATE_START:
        raise RuntimeError(
            "Las colecciones no presentan un período común desde 1981."
        )
    return chirps_last, era5_last, common_last


def iter_blocks(
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    *,
    full_refresh: bool,
) -> Iterator[tuple[pd.Timestamp, pd.Timestamp]]:
    block_start = pd.Timestamp(start).normalize()
    while block_start < end_exclusive:
        if full_refresh:
            candidate = block_start + pd.DateOffset(years=FULL_BLOCK_YEARS)
        else:
            candidate = end_exclusive
        block_end = min(pd.Timestamp(candidate), end_exclusive)
        yield block_start, block_end
        block_start = block_end


def chirps_to_feature(
    image: ee.Image,
    geometry: ee.Geometry,
) -> ee.Feature:
    image = ee.Image(image)
    mean_value = image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=5566,
        bestEffort=True,
        maxPixels=1_000_000_000,
    ).get("precipitation")
    return ee.Feature(
        None,
        {
            "fecha": image.date().format("YYYY-MM-dd"),
            "lluvia_mm": mean_value,
        },
    )


def era5_to_feature(
    image: ee.Image,
    geometry: ee.Geometry,
) -> ee.Feature:
    image = ee.Image(image)
    eto_image = (
        image.select("potential_evaporation_sum")
        .multiply(-1000)
        .max(0)
        .rename("eto_media_cuenca_mm")
    )
    mean_value = eto_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=11132,
        bestEffort=True,
        maxPixels=1_000_000_000,
    ).get("eto_media_cuenca_mm")
    return ee.Feature(
        None,
        {
            "fecha": image.date().format("YYYY-MM-dd"),
            "eto_media_cuenca_mm": mean_value,
        },
    )


def extract_daily_series(
    collection: ee.ImageCollection,
    mapper: Callable[[ee.Image, ee.Geometry], ee.Feature],
    geometry: ee.Geometry,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    value_column: str,
    *,
    full_refresh: bool,
    label: str,
) -> pd.DataFrame:
    records: list[dict] = []

    for block_start, block_end in iter_blocks(
        start,
        end_exclusive,
        full_refresh=full_refresh,
    ):
        block = collection.filterDate(
            block_start.strftime("%Y-%m-%d"),
            block_end.strftime("%Y-%m-%d"),
        )
        mapped = block.map(lambda image: mapper(image, geometry))
        information = ee.FeatureCollection(mapped).getInfo()
        records.extend(
            feature.get("properties", {})
            for feature in information.get("features", [])
        )
        print(
            f"{label}: {block_start:%Y-%m-%d} a "
            f"{block_end - pd.Timedelta(days=1):%Y-%m-%d}"
        )

    frame = pd.DataFrame(records)
    if frame.empty or not {"fecha", value_column}.issubset(frame.columns):
        raise RuntimeError(
            f"{label} no devolvió observaciones para el período solicitado."
        )

    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    frame[value_column] = pd.to_numeric(
        frame[value_column],
        errors="coerce",
    )
    frame = (
        frame.dropna(subset=["fecha"])
        .drop_duplicates(subset=["fecha"], keep="last")
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    return frame


def read_existing_climate(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()

    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"fecha", "lluvia_mm", "eto_media_cuenca_mm"}
    if not required.issubset(frame.columns):
        raise ValueError(
            f"{path.name} no contiene las columnas {sorted(required)}."
        )
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    for column in ["lluvia_mm", "eto_media_cuenca_mm"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["fecha"])
        .drop_duplicates(subset=["fecha"], keep="last")
        .sort_values("fecha")
        .reset_index(drop=True)
    )
    return frame


def validate_new_period(
    rain: pd.DataFrame,
    eto: pd.DataFrame,
    start: pd.Timestamp,
    common_last: pd.Timestamp,
) -> pd.DataFrame:
    merged = rain.merge(
        eto,
        on="fecha",
        how="outer",
        validate="one_to_one",
        indicator=True,
    ).sort_values("fecha")

    expected_dates = pd.date_range(start, common_last, freq="D")
    actual_dates = pd.DatetimeIndex(merged["fecha"])
    missing_dates = expected_dates.difference(actual_dates)
    unexpected_dates = actual_dates.difference(expected_dates)
    invalid = merged.loc[
        merged["_merge"].ne("both")
        | merged["lluvia_mm"].isna()
        | merged["eto_media_cuenca_mm"].isna()
    ]

    if len(missing_dates) or len(unexpected_dates) or not invalid.empty:
        details = []
        if len(missing_dates):
            details.append(
                "faltantes: "
                + ", ".join(missing_dates.strftime("%Y-%m-%d")[:10])
            )
        if len(unexpected_dates):
            details.append(
                "inesperadas: "
                + ", ".join(unexpected_dates.strftime("%Y-%m-%d")[:10])
            )
        if not invalid.empty:
            details.append(
                "nulas/no alineadas: "
                + ", ".join(
                    invalid["fecha"].dt.strftime("%Y-%m-%d").head(10)
                )
            )
        raise RuntimeError(
            "La actualización no es continua; no se escribirán archivos. "
            + " | ".join(details)
        )

    merged = merged.drop(columns="_merge").reset_index(drop=True)
    if (
        (merged["lluvia_mm"] < 0).any()
        or (merged["eto_media_cuenca_mm"] < 0).any()
    ):
        raise RuntimeError(
            "Se detectaron valores negativos no válidos en lluvia o ETo."
        )
    return merged


def build_climate_table(
    existing: pd.DataFrame,
    new_values: pd.DataFrame,
    update_start: pd.Timestamp,
    common_last: pd.Timestamp,
) -> pd.DataFrame:
    if existing.empty:
        combined = new_values.copy()
    else:
        preserved = existing.loc[existing["fecha"] < update_start, [
            "fecha",
            "lluvia_mm",
            "eto_media_cuenca_mm",
        ]]
        combined = pd.concat(
            [preserved, new_values],
            ignore_index=True,
        )

    combined = (
        combined.drop_duplicates(subset=["fecha"], keep="last")
        .sort_values("fecha")
        .reset_index(drop=True)
    )

    if combined.empty or combined["fecha"].min() != CLIMATE_START:
        raise RuntimeError(
            "El histórico debe iniciar exactamente el 1981-01-01."
        )
    if combined["fecha"].max() != common_last:
        raise RuntimeError(
            "El histórico no termina en la última fecha común calculada."
        )

    expected = pd.date_range(CLIMATE_START, common_last, freq="D")
    missing = expected.difference(pd.DatetimeIndex(combined["fecha"]))
    if len(missing):
        raise RuntimeError(
            "El histórico contiene fechas faltantes: "
            + ", ".join(missing.strftime("%Y-%m-%d")[:12])
        )

    if combined[["lluvia_mm", "eto_media_cuenca_mm"]].isna().any().any():
        raise RuntimeError(
            "El histórico final contiene valores climáticos nulos."
        )

    combined["balance_diario_mm"] = (
        combined["lluvia_mm"] - combined["eto_media_cuenca_mm"]
    )
    for window in [7, 30, 90]:
        combined[f"lluvia_acum_{window}d"] = (
            combined["lluvia_mm"].rolling(window).sum()
        )
        combined[f"eto_acum_{window}d"] = (
            combined["eto_media_cuenca_mm"].rolling(window).sum()
        )
        combined[f"balance_{window}d"] = (
            combined["balance_diario_mm"].rolling(window).sum()
        )

    combined["fuente_precipitacion"] = CHIRPS_ASSET
    combined["fuente_eto"] = (
        f"{ERA5_ASSET}:potential_evaporation_sum"
    )
    combined["metodo_eto_diaria"] = (
        "ETo equivalente = max(-potential_evaporation_sum × 1000, 0)"
    )
    combined["eto_origen"] = "ERA5-Land diario"
    combined["periodo_comun_inicio"] = CLIMATE_START.strftime("%Y-%m-%d")
    combined["periodo_comun_fin"] = common_last.strftime("%Y-%m-%d")
    return combined


def calculate_spi_gamma(
    monthly_values: pd.Series,
    scale_months: int,
    calibration_end_year: int,
) -> pd.Series:
    accumulated = monthly_values.rolling(
        scale_months,
        min_periods=scale_months,
    ).sum()
    result = pd.Series(np.nan, index=accumulated.index, dtype=float)

    for month in range(1, 13):
        mask = accumulated.index.month == month
        targets = accumulated.loc[mask].dropna()
        calibration = targets.loc[
            targets.index.year <= calibration_end_year
        ]
        if len(calibration) < 20:
            continue
        positive = calibration.loc[calibration > 0]
        if len(positive) < 15:
            continue

        probability_zero = float((calibration <= 0).mean())
        shape, _, scale_parameter = scipy_gamma.fit(
            positive.to_numpy(dtype=float),
            floc=0,
        )
        gamma_cdf = scipy_gamma.cdf(
            targets.clip(lower=0).to_numpy(dtype=float),
            a=shape,
            loc=0,
            scale=scale_parameter,
        )
        probability = (
            probability_zero
            + (1 - probability_zero) * gamma_cdf
        )
        probability = np.clip(probability, 1e-6, 1 - 1e-6)
        result.loc[targets.index] = norm.ppf(probability)
    return result


def build_spi_table(climate: pd.DataFrame) -> pd.DataFrame:
    daily_rain = climate.set_index("fecha")["lluvia_mm"]
    monthly_rain = daily_rain.resample("MS").sum()
    monthly_counts = daily_rain.resample("MS").count()
    expected_days = pd.Series(
        monthly_rain.index.days_in_month,
        index=monthly_rain.index,
    )
    # El mes en curso se excluye hasta estar completo.
    monthly_rain = monthly_rain.loc[monthly_counts.eq(expected_days)]
    last_daily_date = climate["fecha"].max()
    calibration_end_year = (
        last_daily_date.year
        if (
            last_daily_date.month == 12
            and last_daily_date.day == 31
        )
        else last_daily_date.year - 1
    )

    spi = pd.DataFrame({"fecha": monthly_rain.index})
    for months in [1, 3, 6]:
        spi[f"spi_{months}"] = calculate_spi_gamma(
            monthly_rain,
            months,
            calibration_end_year,
        ).to_numpy()
    spi["fuente"] = f"{CHIRPS_ASSET} mediante GEE"
    spi["metodo"] = (
        "Ajuste gamma por mes y transformación normal estándar"
    )
    spi["periodo_calibracion"] = (
        f"{CLIMATE_START.year}-{calibration_end_year}"
    )
    return spi


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(
        temporary,
        index=False,
        encoding="utf-8-sig",
        float_format="%.6f",
        date_format="%Y-%m-%d",
    )
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_status(
    path: Path,
    *,
    project: str,
    chirps_last: pd.Timestamp,
    era5_last: pd.Timestamp,
    common_last: pd.Timestamp,
) -> None:
    status = {
        "estado": "actualizado",
        "proyecto_gee": project,
        "ultima_fecha_chirps": chirps_last.strftime("%Y-%m-%d"),
        "ultima_fecha_era5_land": era5_last.strftime("%Y-%m-%d"),
        "ultima_fecha_comun": common_last.strftime("%Y-%m-%d"),
        "periodo_inicio": CLIMATE_START.strftime("%Y-%m-%d"),
        "metodo_actualizacion": (
            "Incremental con siete días de superposición"
        ),
    }
    atomic_write_text(
        path,
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
    )


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    print("1/6 · Inicializando Earth Engine…")
    project = initialize_earth_engine()
    print(f"      Proyecto: {project}")

    print("2/6 · Cargando el área aportante aguas arriba de Guardia…")
    geometry, subbasins_geojson = load_analysis_geometry(
        data_dir / SUBBASINS_FILENAME
    )
    print(
        f"      Subcuencas: {len(subbasins_geojson['features'])}"
    )
    write_basin_geometry(geometry, data_dir / BASIN_FILENAME)

    print("3/6 · Consultando las fechas disponibles en GEE…")
    chirps_last, era5_last, common_last = latest_source_dates()
    print(
        f"      CHIRPS: {chirps_last:%Y-%m-%d} · "
        f"ERA5-Land: {era5_last:%Y-%m-%d} · "
        f"corte común: {common_last:%Y-%m-%d}"
    )

    climate_path = data_dir / CLIMATE_FILENAME
    existing = (
        pd.DataFrame()
        if args.full_refresh
        else read_existing_climate(climate_path)
    )

    if existing.empty:
        update_start = CLIMATE_START
        full_query = True
        print("      No existe histórico: se generará desde 1981.")
    else:
        existing_last = existing["fecha"].max().normalize()
        if common_last < existing_last:
            raise RuntimeError(
                "La última fecha común de GEE es anterior al histórico "
                "existente. No se modificaron archivos por seguridad."
            )
        update_start = max(
            CLIMATE_START,
            existing_last - pd.Timedelta(days=OVERLAP_DAYS - 1),
        )
        full_query = False
        print(
            f"      Histórico hasta {existing_last:%Y-%m-%d}; "
            f"se revisará desde {update_start:%Y-%m-%d}."
        )

    end_exclusive = common_last + pd.Timedelta(days=1)

    print("4/6 · Extrayendo precipitación CHIRPS…")
    rain = extract_daily_series(
        ee.ImageCollection(CHIRPS_ASSET).select("precipitation"),
        chirps_to_feature,
        geometry,
        update_start,
        end_exclusive,
        "lluvia_mm",
        full_refresh=full_query,
        label="CHIRPS",
    )

    print("5/6 · Extrayendo ETo equivalente ERA5-Land…")
    eto = extract_daily_series(
        ee.ImageCollection(ERA5_ASSET).select(
            "potential_evaporation_sum"
        ),
        era5_to_feature,
        geometry,
        update_start,
        end_exclusive,
        "eto_media_cuenca_mm",
        full_refresh=full_query,
        label="ERA5-Land",
    )

    new_values = validate_new_period(
        rain,
        eto,
        update_start,
        common_last,
    )
    climate = build_climate_table(
        existing,
        new_values,
        update_start,
        common_last,
    )
    spi = build_spi_table(climate)

    print("6/6 · Validando y escribiendo productos…")
    atomic_write_csv(climate, climate_path)
    atomic_write_csv(spi, data_dir / SPI_FILENAME)
    write_status(
        data_dir / STATUS_FILENAME,
        project=project,
        chirps_last=chirps_last,
        era5_last=era5_last,
        common_last=common_last,
    )

    print("")
    print(
        f"Actualización completada: {len(climate):,} días "
        f"({climate['fecha'].min():%Y-%m-%d} a "
        f"{climate['fecha'].max():%Y-%m-%d})."
    )
    print(
        f"SPI: {len(spi):,} meses completos hasta "
        f"{spi['fecha'].max():%Y-%m}."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
