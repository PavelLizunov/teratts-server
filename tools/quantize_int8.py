#!/usr/bin/env python3
"""Phase C1 (perf spec): offline static INT8 quantization for the two safe
TeraTTSv2 graphs (text_encoder, duration_predictor).

Produces `<stem>.int8.onnx` next to the FP32 model. The Rust server picks the
INT8 variant only when TERATTS_INT8=1, so FP32 stays the default/fallback.

Usage:
    python3 tools/quantize_int8.py <models_dir> [--calib-dir DIR]

Requires: pip install onnxruntime==1.27.0 onnx numpy

Calibration: feeds a set of phoneme-diverse token-id sequences through the
FP32 graph to capture activation ranges. If --calib-dir is omitted, a synthetic
uniform distribution over the vocab is used (adequate for the two conditioning
graphs; validate mel-MSE <1% vs FP32 before deploying).
"""
import argparse
import sys

import numpy as np

SAFE_GRAPHS = ["text_encoder", "duration_predictor"]


def _concrete_shape(dims, seq_len: int):
    """Replace dynamic dims (str/None) with seq_len; keep static ints."""
    shape = []
    for dim in dims:
        if isinstance(dim, int) and dim > 0:
            shape.append(dim)
        else:
            shape.append(seq_len)
    return shape


def build_calibration(model_path: str, n: int = 64, seq_len: int = 48):
    """Yield representative inputs shaped from the graph's declared inputs."""
    import onnx

    onnx_model = onnx.load(model_path)
    inputs = [
        (i.name, [d.dim_value if d.HasField("dim_value") else d.dim_param for d in i.type.tensor_type.shape.dim])
        for i in onnx_model.graph.input
    ]
    rng = np.random.default_rng(0)
    for _ in range(n):
        feed = {}
        for name, dims in inputs:
            shape = _concrete_shape(dims, seq_len)
            if "ids" in name:
                # Tera char-embedder vocab is 135; keep indices in [0, 134].
                feed[name] = rng.integers(0, 135, shape).astype(np.int64)
            elif "mask" in name:
                feed[name] = np.ones(shape, dtype=np.float32)
            else:
                feed[name] = rng.normal(0, 1, shape).astype(np.float32)
        yield feed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("models_dir")
    args = parser.parse_args()

    from onnxruntime.quantization import QuantFormat, QuantType, quantize_static
    from onnxruntime.quantization.calibrate import CalibrationDataReader

    for stem in SAFE_GRAPHS:
        fp32 = f"{args.models_dir}/{stem}.onnx"
        out = f"{args.models_dir}/{stem}.int8.onnx"

        class Reader(CalibrationDataReader):
            def __init__(self):
                self.data = list(build_calibration(fp32))
                self.idx = 0

            def get_next(self):
                if self.idx >= len(self.data):
                    return None
                item = self.data[self.idx]
                self.idx += 1
                return item

        quantize_static(
            fp32,
            out,
            Reader(),
            quant_format=QuantFormat.QDQ,
            per_channel=True,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
        )
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
