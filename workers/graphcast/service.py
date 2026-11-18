"""Resident Windows CUDA GraphCast worker. JSON-lines protocol on stdout."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "runtime" / "graphcast"
PROTOCOL = sys.stdout
sys.stdout = sys.stderr
os.environ["JAX_PLATFORMS"] = "cuda"
os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
sys.path[:0] = [str(ROOT / "vendor" / "upstream-gpu"), str(ROOT / "vendor" / "xarray-jax")]


def send(event, **values):
    PROTOCOL.write(json.dumps({"event": event, **values}, ensure_ascii=True) + "\n")
    PROTOCOL.flush()


class ResidentModel:
    def __init__(self):
        self.ready = False
        self.loads = 0
        self.signatures = {}

    def load(self):
        if self.ready:
            return
        send("loading", message="Загрузка модели в видеопамять")
        from gpu_runtime import prepare_native_cuda

        prepare_native_cuda()
        import haiku as hk
        import jax
        import xarray as xr
        from weathernext.utils import autoregressive, checkpoint, normalization
        from weathernext.weathernext1_graph import graphcast

        self.jax = jax
        self.xr = xr
        devices = jax.devices()
        if not devices or devices[0].platform != "gpu":
            raise RuntimeError("Для генерации требуется NVIDIA GPU. Переход на CPU отключён.")
        self.device = devices[0]
        with (ROOT / "assets" / "model.npz").open("rb") as stream:
            ckpt = checkpoint.load(stream, graphcast.CheckPoint)
        self.task = ckpt.task_config
        self.params = jax.device_put(ckpt.params, self.device)
        for leaf in jax.tree_util.tree_leaves(self.params):
            leaf.block_until_ready()
        stats = {}
        for name in ("diffs_stddev_by_level", "mean_by_level", "stddev_by_level"):
            with xr.open_dataset(ROOT / "assets" / f"{name}.nc", engine="scipy") as ds:
                stats[name] = ds.load()

        @hk.transform_with_state
        def forward(inputs, targets_template, forcings):
            model = graphcast.GraphCast(ckpt.model_config, ckpt.task_config)
            model = normalization.InputsAndResiduals(model, **stats)
            model = autoregressive.Predictor(model, gradient_checkpointing=False)
            return model(inputs, targets_template=targets_template, forcings=forcings)

        self.apply = jax.jit(forward.apply)
        self.loads += 1
        self.ready = True
        send("ready", model_loaded=True, model_load_count=self.loads,
             device=self.device.device_kind, pid=os.getpid())

    def generate(self, command):
        # Inspect/select input before allocating the model on the first request.
        import numpy as np
        import xarray as xr

        started = time.perf_counter()
        input_path = Path(command["input"])
        source_name = command.get("source_name", input_path.name)
        target = Path(command["output"])
        target.mkdir(parents=True, exist_ok=True)
        send("preparing", message="Проверка входных полей")
        from archive_input import open_netcdf

        with open_netcdf(input_path) as raw:
            aliases = {name: new for name, new in (("latitude", "lat"), ("longitude", "lon"),
                       ("pressure_level", "level")) if name in raw.dims}
            raw = raw.rename(aliases)
            required = ("2m_temperature", "mean_sea_level_pressure", "10m_u_component_of_wind",
                        "10m_v_component_of_wind", "total_precipitation_6hr", "temperature",
                        "geopotential", "u_component_of_wind", "v_component_of_wind",
                        "vertical_velocity", "specific_humidity", "land_sea_mask", "geopotential_at_surface")
            missing = [name for name in required if name not in raw]
            if missing:
                raise ValueError("Файл не содержит поля GraphCast: " + ", ".join(missing) +
                                 ". Файла только с LSP недостаточно.")
            if "time" not in raw.dims:
                raise ValueError("Нужна ось time с состояниями атмосферы через 6 часов.")
            if "datetime" in raw:
                stamps = raw.datetime.values.reshape(-1)
            elif "valid_time" in raw:
                stamps = raw.valid_time.values.reshape(-1)
            elif np.issubdtype(raw.time.dtype, np.datetime64):
                stamps = raw.time.values
            else:
                raise ValueError("В файле нет абсолютного времени UTC (datetime или valid_time).")
            stamps = np.asarray(stamps, dtype="datetime64[ns]")
            if stamps.size != raw.sizes["time"] or np.isnat(stamps).any():
                raise ValueError("Нужен один набор временных состояний без пропущенных дат.")
            reference = stamps.max()
            indices = []
            for stamp in (reference - np.timedelta64(6, "h"), reference):
                matches = np.flatnonzero(stamps == stamp)
                if len(matches) != 1:
                    raise ValueError("В файле нужны два разных состояния с интервалом ровно 6 часов.")
                indices.append(int(matches[0]))
            levels = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]
            selected = raw[list(required)].isel(time=indices).sel(level=levels)
            selected = selected.assign_coords(lon=(selected.lon % 360)).sortby("lon").sortby("lat")
            if selected.sizes.get("lat") != 181 or selected.sizes.get("lon") != 360:
                raise ValueError("Подготовьте глобальную сетку 1°: lat=181, lon=360.")
            if not np.allclose(selected.lat, np.arange(-90, 91)) or not np.allclose(selected.lon, np.arange(360)):
                raise ValueError("Нужна регулярная глобальная сетка 1°.")
            if "batch" not in selected.dims:
                selected = selected.expand_dims(batch=[0])
            if selected.sizes["batch"] != 1:
                raise ValueError("Нужен один набор состояний, batch=1.")
            selected = selected.load().astype(np.float32)
        if any(not np.isfinite(var.values).all() for var in selected.data_vars.values()):
            raise ValueError("Во входных полях есть пропуски или бесконечные значения.")
        selected = selected.drop_vars([name for name in ("datetime", "valid_time", "forecast_reference_time")
                                       if name in selected.coords], errors="ignore")
        selected = selected.assign_coords(time=np.array([-6, 0], dtype="timedelta64[h]"), batch=[0])
        selected = selected.assign_coords(lat=np.arange(-90, 91, dtype=np.float32),
                                          lon=np.arange(360, dtype=np.float32),
                                          level=np.array(levels, dtype=np.int32), batch=np.array([0], dtype=np.int32))
        selected.attrs = {}
        for var in selected.variables.values():
            var.attrs = {}
            var.encoding = {}
        self.load()
        from weathernext.utils import data_utils, rollout

        times = np.arange(-6, 25, 6).astype("timedelta64[h]")
        full = selected.reindex(time=times)
        full = full.assign_coords(datetime=(("batch", "time"), (reference + times)[None, :]))
        inputs, targets, forcings = data_utils.extract_inputs_targets_forcings(
            full, target_lead_times=slice("6h", "24h"), **dataclasses.asdict(self.task))
        send("generating", message="Расчёт прогноза", model_loaded=True,
             reference_utc=str(reference), model_load_count=self.loads, pid=os.getpid())

        def predict(**kwargs):
            # All requests use identical relative coordinates and GPU float32
            # leaves. Keep date-dependent forcings as data, never static JIT
            # metadata; changing the source day must not compile a new model.
            for key in ("inputs", "targets_template", "forcings"):
                dataset = kwargs[key]
                if key not in self.signatures:
                    self.signatures[key] = (
                        {name: coord.copy(deep=True) for name, coord in dataset.coords.items()
                         if name in ("batch", "time", "lat", "lon", "level")},
                        [(name, var.dims) for name, var in dataset.data_vars.items()],
                    )
                coordinates, variables = self.signatures[key]
                kwargs[key] = xr.Dataset({
                    name: xr.Variable(dims, self.jax.numpy.asarray(
                        dataset[name].transpose(*dims).data, dtype=self.jax.numpy.float32))
                    for name, dims in variables
                }, coords=coordinates)
            return self.apply(self.params, {}, **kwargs)[0]

        compile_count_before = self.apply._cache_size()
        chunks = []
        step_seconds = []
        calculation = time.perf_counter()
        previous = calculation
        for index, chunk in enumerate(rollout.chunked_prediction_generator(
                predictor_fn=predict, rng=self.jax.random.PRNGKey(0), inputs=inputs,
                targets_template=targets * np.float32(np.nan), forcings=forcings,
                num_steps_per_chunk=1), start=1):
            chunk = self.jax.device_get(chunk).compute()
            if any(not np.isfinite(var.values).all() for var in chunk.data_vars.values()):
                raise ValueError("Модель выдала некорректные значения.")
            chunks.append(chunk)
            now = time.perf_counter()
            step_seconds.append(now - previous)
            previous = now
            send("step", step=index, steps=4, lead_hours=index * 6,
                 seconds=time.perf_counter() - calculation)
        prediction = xr.concat(chunks, dim="time")
        if prediction.sizes["time"] != 4 or not np.array_equal(
                prediction.time.values, np.array([6, 12, 18, 24], dtype="timedelta64[h]")):
            raise ValueError("Суточный файл должен содержать ровно четыре шага: +6, +12, +18, +24 часа.")
        prediction = prediction.assign_coords(
            valid_time=("time", reference + prediction.time.values),
            forecast_reference_time=reference,
        )
        # Include the static fields so the next daily file can be generated
        # directly from this output without substituting unrelated inputs.
        for name in ("land_sea_mask", "geopotential_at_surface"):
            prediction[name] = selected[name]
        prediction.attrs.update({"title": "GrathCast: GraphCast_small forecast",
                                 "model": "GraphCast_small", "forecast_reference_time_utc": str(reference),
                                 "forecast_horizon_hours": 24,
                                 "precipitation_type": "total", "precipitation_interval_hours": 6,
                                 "source_file": source_name})
        for name in prediction.data_vars:
            prediction[name].encoding = {}
        prediction.total_precipitation_6hr.attrs.update(units="m", accumulation_hours=6)
        prediction["2m_temperature"].attrs["units"] = "K"
        path = target / "forecast.nc"
        prediction.to_netcdf(path, engine="scipy", format="NETCDF3_64BIT")
        with xr.open_dataset(path, engine="scipy") as saved:
            if saved.sizes["time"] != 4 or not np.isfinite(saved.total_precipitation_6hr.values).all():
                raise ValueError("Не удалось проверить сохранённый NetCDF.")
        longitude = ((prediction.lon.values + 180) % 360) - 180
        order = np.argsort(longitude)
        precipitation = prediction.total_precipitation_6hr.isel(batch=0).transpose("time", "lat", "lon").values
        frames = np.maximum(precipitation[:, :, order], 0) * 1000
        frames.astype("<f4").tofile(target / "frames.bin")

        def iso(stamp):
            return np.datetime_as_string(stamp, unit="s") + "Z"

        metadata = {
            "id": command["id"], "name": "grathcast-" + np.datetime_as_string(reference, unit="h").replace(":", "-") + ".nc",
            "file": "forecast.nc", "bytes": path.stat().st_size, "format": "NetCDF", "provider": "GrathCast",
            "start_utc": iso(reference), "end_utc": iso(reference + np.timedelta64(24, "h")),
            "valid_times": [iso(reference + np.timedelta64(hour, "h")) for hour in (6, 12, 18, 24)],
            "latitude": prediction.lat.values.tolist(), "longitude": longitude[order].tolist(),
            "grid_shape": [181, 360], "units": "mm/6h", "source_file": source_name,
            "duration_hours": 24, "step_hours": 6,
            "seconds": time.perf_counter() - started, "calculation_seconds": time.perf_counter() - calculation,
            "model_load_count": self.loads, "pid": os.getpid(), "device": self.device.device_kind,
            "compile_count_before": compile_count_before, "compile_count_after": self.apply._cache_size(),
            "step_seconds": step_seconds,
            "gpu_memory_stats": self.device.memory_stats(),
            "negative_precipitation_values": int((precipitation < 0).sum()),
            "map_note": "Суммарные осадки за 6 часов. Отрицательные значения на карте ограничены нулём; NetCDF содержит исходный выход модели.",
        }
        (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        send("completed", metadata=metadata, model_loaded=True, pid=os.getpid(), model_load_count=self.loads)


def main():
    import psutil

    parent_pid = int(sys.argv[sys.argv.index("--parent") + 1]) if "--parent" in sys.argv else os.getppid()
    parent = psutil.Process(parent_pid)

    def parent_watchdog():
        while parent.is_running():
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=parent_watchdog, daemon=True).start()
    model = ResidentModel()
    send("started", pid=os.getpid(), model_loaded=False)
    for line in sys.stdin:
        try:
            command = json.loads(line)
            model.generate(command)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            send("error", error=str(error), model_loaded=model.ready,
                 model_load_count=model.loads, pid=os.getpid())


if __name__ == "__main__":
    main()
