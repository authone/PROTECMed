# Running PROTECMed

How to install, configure and run the prototype, and what each role does once it is
running.

> **This is a prototype, not a clinical product.** Use synthetic data only. Do not point
> any part of it at a clinical workbook. See [What works today](#what-works-today) before
> planning anything around it.

## Contents

1. [Install](01-install.md) — build OpenFHE and the worker, create the Python environment
2. [Configure](02-configure.md) — configuration files, identities, enrolment, where data lives
3. [Run the demo](03-run-the-demo.md) — start the services and complete one release
4. [Role: local provider operator](04-role-provider.md) — the three browser screens, with screenshots
5. [Role: coordinator operator](05-role-coordinator.md) — the HTTP API
6. [Role: recipient](06-role-recipient.md) — reading an authorized result
7. [Troubleshooting](07-troubleshooting.md) — error tokens, exit codes, common failures

## What the prototype does

Two or three data providers count records matching the same approved cohort definition
**locally**, encrypt one integer each under a jointly generated public key, and let a
coordinator add the ciphertexts. The exact total is released only after **every** provider
approves that specific computation and produces its own partial decryption.

It does not do Kaplan–Meier, regression, machine learning, general SQL or arbitrary code
execution, and it is not a general encrypted database.

## What works today

| Capability | Status |
|---|---|
| OpenFHE v1.5.1 build and the nine-subcommand worker | Working, `linux/arm64` verified |
| Local import, query catalogue, frozen snapshots | Working |
| Signed protocol, approval gate, unanimous release | Working |
| Coordinator HTTP API + SQLite | Working |
| Local provider service and browser UI | Working |
| Single-host synthetic demo (D1) | Working |
| **Docker images, Compose, offline bundle** | **Not built** (milestone M5) |
| **Multi-machine deployment, TLS, private CA** | **Not implemented** (D2, milestone M6) |
| **Windows / macOS** | **Never run** |
| **amd64 / mixed-architecture exchange** | **Never tested** |
| **Clinical (IOCN) acceptance** | **Never run** |

So: today you can run everything on one Linux machine, over loopback HTTP, with invented
data. Three processes on one laptop are a reproducible **simulation**. They are not three
institutions — the host administrator can read every party's directory.

## Prerequisites

- Linux. Verified on `aarch64` (Kali rolling, g++ 15.3.0). Other Linux distributions
  should work; nothing else has been tried.
- A C++17 compiler and CMake ≥ 3.16.3.
- Python ≥ 3.13.
- Network access **once**, to clone OpenFHE.
- About 3 GB of disk for the OpenFHE build tree and 2 CPU cores (the build is the slow
  part; the application itself is not demanding).

## Quick start

```bash
# 1. build the cryptographic core (once, slow)
git clone --branch v1.5.1 --depth 1 --recurse-submodules \
  https://github.com/openfheorg/openfhe-development.git vendor/openfhe
cmake -S vendor/openfhe -B build/openfhe -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PWD/.local/openfhe" -DBUILD_EXAMPLES=ON \
  -DBUILD_UNITTESTS=OFF -DBUILD_BENCHMARKS=OFF -DWITH_OPENMP=OFF -DNATIVE_SIZE=64
cmake --build build/openfhe --parallel 2 && cmake --install build/openfhe

# 2. build the worker
cmake -S cpp/fhe-core -B build/worker -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/worker --parallel 2

# 3. Python environment
python -m venv .venv
.venv/bin/pip install -r services/coordinator/requirements.txt \
  -r services/party-agent/requirements.txt \
  -r reference/python/requirements-reference.txt

# 4. check it
.venv/bin/python -m unittest discover -s tests

# 5. run the single-host demo
.venv/bin/python deployment/synthetic_demo.py --parties 2 --state /tmp/protecmed-demo
```

Step 5 prints the URLs and one-time tokens. Open a provider UI in a browser and follow
[Run the demo](03-run-the-demo.md).

## Screenshots

The images in `running/images/` are regenerated from the live application with:

```bash
python tools/ui-screenshots/capture.py --out running/images --state /tmp/protecmed-shots
```

That tool drives the real UI through a real Chromium — nothing in the screenshots is
mocked up.
