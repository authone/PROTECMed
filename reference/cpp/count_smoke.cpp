// PROTECMed v2 — API smoke source, NOT COMPILED OR RUN in this delivery.
// Synthetic-only, in-process correctness test. All separate keys are held here
// for testing; this is NOT a distributed deployment or an authorization layer.
// Never deploy this program as the coordinator; never give it clinical data.
// API sources: OpenFHE v1.5.1 threshold-fhe.cpp and cryptocontext.h.
#include "openfhe.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lbcrypto;

static CryptoContext<DCRTPoly> MakeCountContext(std::uint32_t n) {
    if (n != 2 && n != 3) throw std::invalid_argument("party count");
    CCParams<CryptoContextBGVRNS> p;
    p.SetPlaintextModulus(65537);
    p.SetMultiplicativeDepth(0);
    p.SetThresholdNumOfParties(n);
    p.SetSecurityLevel(HEStd_128_classic);
    p.SetSecretKeyDist(UNIFORM_TERNARY);
    p.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY);
    p.SetScalingTechnique(FLEXIBLEAUTOEXT);
    p.SetKeySwitchTechnique(BV);
    p.SetDigitSize(10);
    p.SetEvalAddCount(5);
    p.SetKeySwitchCount(0);
    auto cc = GenCryptoContext(p);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);
    cc->Enable(MULTIPARTY);
    return cc;
}

static void Run(const std::vector<std::int64_t>& counts) {
    const auto n = static_cast<std::uint32_t>(counts.size());
    for (const auto x : counts)
        if (x < 0 || x > 10000) throw std::invalid_argument("local count range");
    auto cc = MakeCountContext(n);
    std::vector<KeyPair<DCRTPoly>> parties;
    parties.reserve(n);
    for (std::uint32_t i = 0; i < n; ++i) {
        // Explicitly use PUBLIC-key overload. Never add/recover private shares.
        auto next = i == 0 ? cc->KeyGen() :
            cc->MultipartyKeyGen(parties.back().publicKey, false, false);
        if (!next.good()) throw std::runtime_error("key generation failed");
        parties.push_back(next);
    }
    const auto jointPublic = parties.back().publicKey;
    std::vector<Ciphertext<DCRTPoly>> inputs;
    std::int64_t expected = 0;
    for (const auto x : counts) {
        auto pt = cc->MakePackedPlaintext(std::vector<std::int64_t>{x});
        inputs.push_back(cc->Encrypt(jointPublic, pt));
        if (!inputs.back()) throw std::runtime_error("null ciphertext");
        expected += x;
    }
    auto sum = cc->EvalAdd(inputs[0], inputs[1]);
    if (n == 3) sum = cc->EvalAdd(sum, inputs[2]);
    std::vector<Ciphertext<DCRTPoly>> partials;
    for (std::uint32_t i = 0; i < n; ++i) {
        auto partial = i == 0 ? cc->MultipartyDecryptLead({sum}, parties[i].secretKey) :
                               cc->MultipartyDecryptMain({sum}, parties[i].secretKey);
        if (partial.size() != 1 || !partial[0]) throw std::runtime_error("partial shape");
        partials.push_back(partial[0]);
    }
    if (partials.size() != n) throw std::runtime_error("missing partial");
    // This size check is not the production signed-roster/consent gate.
    Plaintext out;
    const auto status = cc->MultipartyDecryptFusion(partials, &out);
    if (!status.isValid || !out) throw std::runtime_error("fusion failed");
    out->SetLength(cc->GetRingDimension());
    const auto& decoded = out->GetPackedValue();
    if (decoded.empty() || decoded[0] != expected) throw std::runtime_error("wrong sum");
    for (std::size_t i = 1; i < decoded.size(); ++i)
        if (decoded[i] != 0) throw std::runtime_error("nonzero extra slot");
    std::cout << "PASS synthetic n=" << n << " result=" << expected
              << " ring=" << cc->GetRingDimension() << '\n';
}

int main(int argc, char** argv) {
    try {
        if (argc != 2 || (std::string(argv[1]) != "2" && std::string(argv[1]) != "3"))
            throw std::invalid_argument("usage: count_smoke 2|3");
        const bool two = std::string(argv[1]) == "2";
        Run(two ? std::vector<std::int64_t>{5, 6} : std::vector<std::int64_t>{3, 2, 6});
        Run(two ? std::vector<std::int64_t>{0, 0} : std::vector<std::int64_t>{0, 0, 0});
        Run(two ? std::vector<std::int64_t>{10000, 10000} :
                  std::vector<std::int64_t>{10000, 10000, 10000});
        return 0;
    } catch (const std::exception& e) {
        // Synthetic-only smoke. Production returns sanitized error codes.
        std::cerr << "FAIL: " << e.what() << '\n';
        return 1;
    }
}
