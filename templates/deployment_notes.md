# Deployment template limitations

`compose.synthetic.example.yaml` is an implementation template for synthetic single-host D1, not a tested launcher. It intentionally requires already-built reviewed image references. Services must implement the listed environment variables and listen on container port 8080. Entry points and health checks belong in those images. Production state volumes must be initialized with the runtime UID; do not solve permission failures by using privileged mode or chmod 777.

Before use, the developer must populate A/B/C import volumes with only their respective SYNTHETIC canonical shards; no shard creation is performed by this template. File population uses an authorized initialization step before switching each provider to a read-only mount. Images must be preloaded when the network is internal/offline. Add measured CPU/memory/process limits and health checks in M5.

The optional `three` profile starts C but does not by itself set a cryptographic threshold: the signed application roster and SetThresholdNumOfParties must still both be set to 3. Two-provider mode uses A/B only. Plain HTTP is restricted to this one-host simulation, whose administrator can access all containers. Do not reuse this profile for clinical separate-host D2; implement approved HTTPS/identity provisioning and role-local data storage instead.

No `docker compose up` success, Windows/Mac compatibility or container security validation is claimed by shipping YAML. Run `docker compose config` and the M5 tests only once the actual images and host prerequisites exist.
