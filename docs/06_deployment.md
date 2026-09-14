# 6. Build, installation and operator deployment

## 6.1 What is provided versus what is to be built

This delivery includes a C++ smoke source and a CMake template. It does not include OpenFHE binaries, container images, an application installer or completed services. The programmer produces and tests those in M0–M6. Do not hand the documentation ZIP to IOCN as though it were an installable application.

The recommended implementation is a C++17 OpenFHE CLI, Python FastAPI services, SQLite and server-rendered HTML. A separate minimal Linux image for each role keeps operations reproducible. No GPU is required by the specified additive circuit. Resource requests are measured during the first build/run; start builds with two parallel jobs on memory-constrained laptops rather than an unbounded `--parallel`.

## 6.2 Pinned upstream build gate

Run on a Linux developer environment or inside the build image with network access:

```bash
git clone --branch v1.5.1 --depth 1 --recurse-submodules \
  https://github.com/openfheorg/openfhe-development.git vendor/openfhe

git -C vendor/openfhe rev-parse HEAD
git -C vendor/openfhe submodule status --recursive

cmake -S vendor/openfhe -B build/openfhe \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PWD/.local/openfhe" \
  -DBUILD_EXAMPLES=ON -DBUILD_UNITTESTS=OFF \
  -DBUILD_BENCHMARKS=OFF -DWITH_OPENMP=OFF -DNATIVE_SIZE=64
cmake --build build/openfhe --parallel 2
cmake --install build/openfhe

cmake -S reference/cpp -B build/smoke \
  -DCMAKE_PREFIX_PATH="$PWD/.local/openfhe"
cmake --build build/smoke --parallel 2
ctest --test-dir build/smoke --output-on-failure
```

These are source-informed build instructions; they were not executed in this environment because the OpenFHE checkout was unavailable. M0 must reject missing submodules, version mismatch or unsupported flags rather than continuing silently. Store the resolved full commit, CMake cache, compiler version and build log. Check that CMake actually reports 64-bit native arithmetic. Re-enable OpenMP only as a separately benchmarked build change.

Link using the variables/exported libraries from the pinned OpenFHE CMake package and preserve its compile flags. The supplied CMake template follows the upstream user-project pattern [S13]. Do not guess imported target names or omit required library/ABI flags. Run the official BGV threshold and serialization examples before the project smoke tests; locate their generated executable paths in the build output.

The smoke program is intentionally an **in-process mathematical test using invented counts**. It holds separate party keys in one process to test API sequencing, not to demonstrate security isolation. It must not be packaged into the coordinator service or used with clinical data.

## 6.3 Two deployment profiles

**D1 — synthetic single-host demonstration.** Compose starts coordinator, A, B and optional C. Use separate role-specific volumes, local ports 8080/8081/8082/8083 and one private Docker network. Host-published ports are `127.0.0.1:<port>:<container-port>`. HTTP is acceptable only for this local simulation. Do not claim independent institutional trust boundaries.

**D2 — restricted IOCN validation.** Coordinator runs on an approved machine/VM; A, B and optionally C run on distinct provider-controlled Windows/macOS computers. Each party has its own local data directory, tmpfs keys, credentials and local UI. Only the coordinator HTTPS endpoint is reachable over the approved network. Providers use the correct network hostname, not `localhost`, to contact it. The coordinator is not allowed to mount provider data/key directories.

For a minimum 3/3 distributed validation, three distinct provider endpoints can participate while the coordinator shares a machine with a disclosed trusted operator if that topology is explicitly accepted. The strongest separation places the coordinator on its own host. Report actual machines and administrators rather than counting processes as independent hospitals.

## 6.4 Container requirements

Build from a pinned base-image digest, pin Python dependencies in a reviewed lock file, verify source commits and include an SBOM and license notices. Use non-root runtime users, no Docker socket mounts, no privileged containers, no writable host-root mounts, no cloud telemetry and no debug mode. Mount data read-only and tmpfs keys owner-only. Log only allowlisted fields.

The ephemeral-key profile must ensure that the service and its worker run under compatible UIDs and can read their own tmpfs, but not another provider's directory. A chmod instruction applied to a host bind mount is not a complete Windows/macOS permission model; test the container view. Store local audit/outbox state separately from ephemeral secrets.

Produce `linux/amd64` and `linux/arm64` images. They share the source/profile release but have different platform-specific digests. A run must use the approved platform digest from that release; requiring byte-identical image digests across architectures would be wrong. Test serialization round trips and a mixed-architecture 2/2 or 3/3 run before calling the release interoperable.

No prebuilt image is included here. The application build should fail when required source files, version locks or runtime permissions are missing, rather than run a mock/no-crypto fallback.

## 6.5 Windows and Mac preparation

The operator should not compile C++ on an IOCN laptop. IT installs a supported container runtime and the programmer supplies tested role images plus short start/stop scripts. Docker Desktop on Windows requires its documented virtualization/WSL or supported backend prerequisites; on Mac choose the correct Apple Silicon or Intel installation. Check current support and institutional licensing before deployment; do not assume every existing machine or every institutional use qualifies [S14a, S14b].

A practical starting machine has enough memory for its assigned service(s) and container VM; the release report must record measured RAM rather than convert a guess into a mandatory hardware specification. Avoid putting three simulated providers and a native build into the same memory budget during clinical validation.

The programmer supplies `start-demo.ps1`, `start-demo.command`, `stop-demo` equivalents and a D2 per-party starter. Each starter checks the runtime, architecture, image checksums, expected services, free disk, port conflicts, required config and read-only mounts. It opens the local UI and shows an explicit “synthetic demo” or “restricted IOCN validation” banner. A restart warning explains that unfinished ephemeral-key epochs cannot be resumed.

## 6.6 Offline bundle and credentials

The offline application bundle produced in M6 contains architecture-specific image archives, Compose files, scripts, a release manifest, SHA-256 checksums and a Romanian operator guide. Dependency installation and image pulling must not occur during an offline clinical demonstration. Offline image loading does not install or license Docker Desktop itself.

Generate all private keys and local operator credentials on the target endpoint at runtime, never embed them in the image/archive. The baseline may use an ephemeral random local operator token shown through a local-only provisioning command, exchanged for an authenticated session. Keep tokens out of coordinator logs, URLs, screenshots and shared `.env` files. Clear local sessions when the agent restarts.

For D2, configure an IT-approved private CA and HTTPS at the coordinator. Distribute only the CA certificate and correct public identity fingerprints; never distribute the coordinator's private TLS key or all party credentials. Plaintext patient files stay in IOCN-approved storage and are not copied into the software bundle.

## 6.7 Operator path to demonstrate unanimity

1. Start the approved release; confirm the mode, roster and fingerprints locally.
2. Select the local shard/approved data file. Accept the reviewed formula-cache mode only when justified. Confirm mapping and validation status.
3. Accept Q004 and the recipients. Complete the local key step and final epoch confirmation.
4. Compute the local count and encrypt/submit it. The coordinator shows a received status, never this count.
5. Review the verified aggregate request on each provider screen. In 3/3 approve A and B only; show the coordinator's blocked state and no result value.
6. Disconnect C and verify that the state remains blocked. Reconnect C without restarting its key-holding container, or start a fresh epoch if keys were lost.
7. C approves the same verified request. The correct aggregate appears. Export the sanitized evidence bundle.

Distinguish network disconnection from container restart: the first can preserve the ephemeral key; the second intentionally cannot. Use synthetic data for training. Restricted IOCN Q004 should produce 11 only for the verified source and splitting rule.
