// PROTECMed v2 — isolated OpenFHE worker (milestone M2).
//
// The service owns policy, authentication, signatures, immutable state and
// authorization. This worker only validates cryptographic inputs and performs the
// nine subcommands of blueprint 5.2. It must never be exposed over HTTP, never be
// given network access and never be handed coordinator credentials.
//
// It computes no hashes and verifies no signatures: artifact digests and signed
// envelopes are the service's responsibility (blueprint 5.6). Errors leave this
// program as an exit code plus one uppercase symbolic token on stderr.
#ifndef PROTECMED_WORKER_H
#define PROTECMED_WORKER_H

#include "openfhe.h"

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace protecmed {

// Exit-code registry, blueprint 5.3.
enum ExitCode : int {
    kOk = 0,
    kInvalidCommand = 10,
    kProfileMismatch = 11,
    kSerializationFailure = 12,
    kShapeMismatch = 13,
    kCryptoFailure = 14,
    kRoleFailure = 15,
    kRangeFailure = 16,
    kAggregateMismatch = 17,
    kFilesystemFailure = 20,
    kResourceLimit = 21,
};

// Application bounds, blueprint 2.2 / 2.3.
constexpr std::int64_t kMaxLocalCount = 10000;
constexpr std::uint32_t kMinRingDimension = 8192;
constexpr std::uint64_t kMaxArtifactBytes = 64ull * 1024 * 1024;

class WorkerError : public std::runtime_error {
public:
    WorkerError(ExitCode code, const std::string& token)
        : std::runtime_error(token), code_(code) {}
    ExitCode code() const { return code_; }

private:
    ExitCode code_;
};

[[noreturn]] void Fail(ExitCode code, const std::string& token);

// --- profile.cpp -----------------------------------------------------------
lbcrypto::CryptoContext<lbcrypto::DCRTPoly> MakeCountContext(std::uint32_t parties);
// Checks a context (generated or deserialized) against the compiled profile.
void VerifyProfile(const lbcrypto::CryptoContext<lbcrypto::DCRTPoly>& context);
std::uint32_t ContextParties(const lbcrypto::CryptoContext<lbcrypto::DCRTPoly>& context);
std::string DescribeProfile(const lbcrypto::CryptoContext<lbcrypto::DCRTPoly>& context);

// --- artifact_io.cpp -------------------------------------------------------
// Reads are size-limited and never follow a symlink. Writes are create-new,
// owner-only, then atomically renamed into place.
lbcrypto::CryptoContext<lbcrypto::DCRTPoly> LoadContext(const std::string& path);
void StoreContext(const std::string& path,
                  const lbcrypto::CryptoContext<lbcrypto::DCRTPoly>& context);

lbcrypto::PublicKey<lbcrypto::DCRTPoly> LoadPublicKey(const std::string& path);
void StorePublicKey(const std::string& path,
                    const lbcrypto::PublicKey<lbcrypto::DCRTPoly>& key);

lbcrypto::PrivateKey<lbcrypto::DCRTPoly> LoadPrivateKey(const std::string& path);
// Refuses a group- or world-accessible destination directory.
void StorePrivateShare(const std::string& path,
                       const lbcrypto::PrivateKey<lbcrypto::DCRTPoly>& key);

lbcrypto::Ciphertext<lbcrypto::DCRTPoly> LoadCiphertext(const std::string& path);
void StoreCiphertext(const std::string& path,
                     const lbcrypto::Ciphertext<lbcrypto::DCRTPoly>& ciphertext);

std::string ReadFileBytes(const std::string& path);

// --- commands.cpp ----------------------------------------------------------
struct Arguments {
    std::string command;
    std::vector<std::string> inputs;    // repeatable --input / --partial
    std::string inputFlag;              // which of the two was actually used
    std::string context;
    std::string incoming;
    std::string publicKey;
    std::string secret;
    std::string ciphertext;
    std::string candidate;
    std::string publicOut;
    std::string secretOut;
    std::string out;
    std::string role;
    std::string artifact;
    std::string type;
    std::string expectKeyTag;
    std::uint32_t parties = 0;
    bool countStdin = false;
    bool haveParties = false;
};

int Dispatch(const Arguments& arguments);

}  // namespace protecmed

#endif  // PROTECMED_WORKER_H
