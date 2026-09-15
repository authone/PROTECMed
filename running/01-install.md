# 1. Install

Everything is built from source. There is **no installer, no package and no container
image** — those are milestone M5 and have not been built.

All commands run from the repository root.

## 1.1 Prerequisites

```bash
g++ --version        # C++17, tested with g++ 15.3.0
cmake --version      # >= 3.16.3
python3 --version    # >= 3.13
git --version
```

If `cmake` is missing and you cannot install it system-wide, a user-local copy works:

```bash
python -m venv .local/toolchain
.local/toolchain/bin/pip install cmake
export PATH="$PWD/.local/toolchain/bin:$PATH"
```

That is how the reference build for this repository was produced (CMake 4.4.3).

## 1.2 Build OpenFHE v1.5.1

The version is pinned. Do not substitute another release: the profile, the parameters and
the recorded evidence are all bound to this one.

```bash
git clone --branch v1.5.1 --depth 1 --recurse-submodules \
  https://github.com/openfheorg/openfhe-development.git vendor/openfhe

git -C vendor/openfhe rev-parse HEAD          # 1306d14f8c26bb6150d3e6ad54f28dfe1007689e
git -C vendor/openfhe submodule status --recursive
```

Stop here if the commit differs or any submodule is missing. Then:

```bash
cmake -S vendor/openfhe -B build/openfhe \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PWD/.local/openfhe" \
  -DBUILD_EXAMPLES=ON -DBUILD_UNITTESTS=OFF \
  -DBUILD_BENCHMARKS=OFF -DWITH_OPENMP=OFF -DNATIVE_SIZE=64
cmake --build build/openfhe --parallel 2
cmake --install build/openfhe
```

Check the configure output says `NATIVEINT is set to 64`. On a 2-core laptop this takes
roughly half an hour. `--parallel 2` is deliberate: an unbounded `--parallel` exhausts
memory on small machines.

`-DBUILD_EXAMPLES=ON` is only needed to run the upstream example programs. `OFF` builds
faster but was not used for the verified build recorded in `evidence/m0/`.

`vendor/`, `build/` and `.local/` are all git-ignored.

## 1.3 Build the worker

```bash
cmake -S cpp/fhe-core -B build/worker -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/worker --parallel 2
```

The CMake file **aborts** unless the pinned package reports OpenFHE 1.5.1 and native size
64, so a mismatched install fails here rather than silently producing a different profile.

Smoke-test it directly:

```bash
LD_LIBRARY_PATH="$PWD/.local/openfhe/lib" \
  ./build/worker/protecmed-worker context-create --parties 2 --out /tmp/ctx.bin
```

Expect a single JSON line reporting `"ring_dimension": 8192`,
`"security_level": "HEStd_128_classic"` and `"multiparty_mode": "NOISE_FLOODING_MULTIPARTY"`.

The services set `LD_LIBRARY_PATH` for the worker themselves; you only need it when
running the binary by hand.

## 1.4 Python environment

```bash
python -m venv .venv
.venv/bin/pip install \
  -r services/coordinator/requirements.txt \
  -r services/party-agent/requirements.txt \
  -r reference/python/requirements-reference.txt
```

All three files are needed. The third one (`defusedxml`) is only used by the delivered
reference audit utility, but the test suite imports it — without it the 57 reference tests
fail to load.

Every dependency is pinned exactly. Change a pin only with a review.

## 1.5 Verify the installation

```bash
.venv/bin/python -m unittest discover -s tests
```

Expect **311 tests, OK**. The count breaks down as 57 reference + 151 unit + 66
integration + 37 end-to-end.

If the worker binary is missing, the 66 integration and 37 end-to-end tests **skip** with
a message naming the expected path — they never pass silently. A run reporting far fewer
than 311 tests means the worker was not built or a dependency is missing.

## 1.6 Optional: screenshot tooling

Only needed to regenerate the documentation images. It is not a runtime dependency and is
deliberately absent from the service requirement files.

```bash
.local/toolchain/bin/pip install playwright    # plus any Chromium binary
python tools/ui-screenshots/capture.py --out running/images --state /tmp/protecmed-shots
```

Next: [Configure](02-configure.md).
