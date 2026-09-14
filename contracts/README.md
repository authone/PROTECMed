# Contract validation and hash rules

All schemas are JSON Schema 2020-12, version 2.0, with extra fields rejected where defined. The generic envelope schema is followed by the payload schema selected by purpose. `plan-acceptance` and `epoch-confirmation` use `acknowledgement`; their purpose and object hash determine what is accepted. A complete service must validate both layers and the semantic rules in Sections 4–5.

`fixtures/contract_examples.json` contains invented structural examples. Hashes and sizes in that file are illustrative placeholders, not a coherent signed OpenFHE transcript. Never upload those examples as real key/ciphertext artifacts. Tests generate temporary identity keys in memory; no private keys ship in this package.

Hash recipe: query, run-plan, each key-round payload, epoch-manifest, encrypted-count payload, input-set and decryption-request are SHA-256 of `protocol.canonical_bytes(payload)`, excluding envelope/signature. The key-round transcript is the canonical array of key-round payloads in roster order, with their signatures verified separately. Recipient-list hash is over the canonical ordered recipient-ID array. The mapping hash is SHA-256 of exact reviewed mapping-file bytes. Context, key, ciphertext and partial hashes are over the exact binary artifact bytes.

The run roster order is stable and defines lead/main and addition order. Require threshold == party_count == len(roster) in {2,3}. Check unique IDs, pinned identity fingerprints, same study/run/epoch/query, correct snapshots, complete sets, current state and role-specific authorization. These cross-object relationships are not established by JSON Schema.

Generate request IDs and snapshot tokens locally with secure randomness; generate the nonce with 32 random bytes, hex encoded. A snapshot token is opaque; keep clinical source hashes and source paths local. Use UTC timestamps exactly `YYYY-MM-DDTHH:MM:SSZ` and parse them as dates, not just regex matches.

Reject duplicate JSON keys before schema validation. The canonical profile permits only ASCII keys/strings, booleans/null, safe integers and bounded arrays/objects. Clinical display labels can be Romanian in the UI, outside the signed canonical payload. Use identity fingerprints calculated over an explicitly fixed raw public-key encoding, not a textual PEM representation that changes with whitespace.
